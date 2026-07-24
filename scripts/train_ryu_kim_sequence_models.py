import argparse
import csv
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


def _bootstrap_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "python" / "src"))
    return repo_root


REPO_ROOT = _bootstrap_path()

from openrdw_ai.ryu_kim_fms.dynamic_baseline import (  # noqa: E402
    DynamicStandardizer,
    assert_raw_pa_and_session_disjoint,
    fms_bin,
    load_raw_sessions,
    mean,
    rmse,
    select_curve_sessions,
    stdev,
    write_csv,
    write_json,
)
from openrdw_ai.ryu_kim_fms.schema import DYNAMIC_FEATURES, DatasetConfig  # noqa: E402
from openrdw_ai.ryu_kim_fms.sequence_models import (  # noqa: E402
    assert_sequence_input_names,
    build_causal_tcn_model,
    build_lstm_model,
    count_trainable_parameters,
    require_torch,
)


SEQUENCE_INPUT_NAMES = tuple(DYNAMIC_FEATURES) + tuple(f"{name}_missing_mask" for name in DYNAMIC_FEATURES)
FMS_BINS = ("0-5", "5-10", "10-15", "15-20", "outside")


def set_seed(torch, seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_split_assignments(path: Path) -> Dict[str, int]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("split_name") != "raw_pa_id-group-disjoint split":
        raise RuntimeError(f"Unexpected split name in {path}: {data.get('split_name')}")
    assignments = {str(k): int(v) for k, v in data["fold_assignments"].items()}
    if not assignments:
        raise RuntimeError(f"No fold assignments found in {path}")
    return assignments


def split_windows_by_frozen_fold(
    windows: Sequence[Mapping[str, object]],
    fold_assignments: Mapping[str, int],
    fold: int,
) -> Tuple[List[Mapping[str, object]], List[Mapping[str, object]]]:
    train, test = [], []
    for window in windows:
        group = str(window["raw_pa_id"])
        if group not in fold_assignments:
            raise RuntimeError(f"Window raw_pa_id {group} is missing from the frozen split")
        if fold_assignments[group] == fold:
            test.append(window)
        else:
            train.append(window)
    assert_raw_pa_and_session_disjoint(train, test)
    return train, test


def make_sequence_windows(
    sessions: Sequence[Mapping[str, object]],
    duration_seconds: float,
    sample_interval_seconds: float,
    max_missing_fraction: float,
    stride_steps: int = 1,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    length = round(duration_seconds / sample_interval_seconds)
    if length <= 0:
        raise ValueError("Window length must be positive")
    windows: List[Dict[str, object]] = []
    excluded = 0
    excluded_sessions = set()
    excluded_groups = set()
    candidate_windows = 0
    for session in sessions:
        rows = [r for r in session["rows"] if r.get("timestamp") is not None]
        rows = sorted(rows, key=lambda r: (float(r["timestamp"]), int(r.get("row_index", 0))))
        for end_index in range(length - 1, len(rows), stride_steps):
            chunk = rows[end_index - length + 1 : end_index + 1]
            if len(chunk) != length:
                continue
            terminal = chunk[-1]
            if terminal.get("fms") is None:
                continue
            candidate_windows += 1
            x_dynamic = []
            missing_mask = []
            missing_count = 0
            raw_feature_stats = []
            for row in chunk:
                values = []
                mask_row = []
                for feature in DYNAMIC_FEATURES:
                    value = row.get(feature)
                    missing = value is None
                    values.append(float(value) if value is not None else None)
                    mask_row.append(1 if missing else 0)
                    missing_count += 1 if missing else 0
                x_dynamic.append(values)
                missing_mask.append(mask_row)
            for feature_index in range(len(DYNAMIC_FEATURES)):
                observed = [
                    row[feature_index]
                    for row, mask_row in zip(x_dynamic, missing_mask)
                    if not mask_row[feature_index] and row[feature_index] is not None
                ]
                raw_feature_stats.append(
                    {
                        "count": len(observed),
                        "sum": sum(observed),
                        "sumsq": sum(value * value for value in observed),
                    }
                )
            missing_fraction = missing_count / (length * len(DYNAMIC_FEATURES))
            if missing_fraction > max_missing_fraction:
                excluded += 1
                excluded_sessions.add(str(session["session_uid"]))
                excluded_groups.add(str(session["raw_pa_id"]))
                continue
            windows.append(
                {
                    "raw_pa_id": session["raw_pa_id"],
                    "session_uid": session["session_uid"],
                    "timestamps": [float(row["timestamp"]) for row in chunk],
                    "start_time": float(chunk[0]["timestamp"]),
                    "end_time": float(terminal["timestamp"]),
                    "source_row_start": int(chunk[0].get("row_index", 0)),
                    "source_row_end": int(terminal.get("row_index", end_index)),
                    "x_dynamic_feature_names": list(DYNAMIC_FEATURES),
                    "x_dynamic": x_dynamic,
                    "missing_mask": missing_mask,
                    "raw_feature_stats": raw_feature_stats,
                    "window_length_steps": length,
                    "dynamic_missing_fraction": missing_fraction,
                    "has_missing_dynamic": missing_count > 0,
                    "y_fms": float(terminal["fms"]),
                }
            )
    return (
        windows,
        {
            "candidate_windows": candidate_windows,
            "effective_windows": len(windows),
            "excluded_windows_missing_fraction_gt_threshold": excluded,
            "excluded_sessions": len(excluded_sessions),
            "excluded_raw_pa_id_groups": len(excluded_groups),
            "window_length_steps": length,
        },
    )


def assert_windows_do_not_cross_session(windows: Sequence[Mapping[str, object]]) -> None:
    for window in windows:
        if not window.get("session_uid"):
            raise AssertionError("Window missing session_uid")
        if "session_uids" in window and len(set(window["session_uids"])) != 1:
            raise AssertionError("Window crosses session boundaries")


def tensorize_windows(torch, windows: Sequence[Mapping[str, object]], standardizer: DynamicStandardizer, device):
    assert_sequence_input_names(SEQUENCE_INPUT_NAMES)
    rows = []
    labels = []
    for window in windows:
        values = standardizer.transform_window(window)
        masks = window["missing_mask"]
        rows.append([list(v) + [float(m) for m in mask] for v, mask in zip(values, masks)])
        labels.append(float(window["y_fms"]))
    return (
        torch.tensor(rows, dtype=torch.float32, device=device),
        torch.tensor(labels, dtype=torch.float32, device=device),
    )


def iter_batches(torch, x, y, batch_size: int, shuffle: bool, seed: int):
    indices = list(range(x.shape[0]))
    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(indices)
    for start in range(0, len(indices), batch_size):
        idx = torch.tensor(indices[start : start + batch_size], dtype=torch.long, device=x.device)
        yield x.index_select(0, idx), y.index_select(0, idx)


def build_model(model_name: str, args):
    if model_name == "lstm":
        return build_lstm_model(
            input_size=12,
            hidden_size=args.lstm_hidden_size,
            num_layers=args.lstm_layers,
            dropout=args.lstm_dropout,
        )
    if model_name == "causal_tcn":
        return build_causal_tcn_model(
            input_channels=12,
            channels=args.tcn_channels,
            levels=args.tcn_levels,
            kernel_size=args.tcn_kernel_size,
            dropout=args.tcn_dropout,
        )
    raise ValueError(model_name)


def tiny_overfit_check(torch, model, x, y, device, max_steps: int = 80) -> None:
    subset = min(32, int(x.shape[0]))
    if subset < 4:
        raise RuntimeError("Not enough windows for tiny-overfit check")
    model.to(device)
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = torch.nn.MSELoss()
    x_small = x[:subset]
    y_small = y[:subset]
    with torch.no_grad():
        start_loss = float(criterion(model(x_small), y_small).detach().cpu())
    for _ in range(max_steps):
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(x_small), y_small)
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        end_loss = float(criterion(model(x_small), y_small).detach().cpu())
    if not math.isfinite(end_loss) or end_loss >= start_loss * 0.95:
        raise RuntimeError(f"Tiny-overfit check failed: start_loss={start_loss:.6f}, end_loss={end_loss:.6f}")


def single_batch_gradient_check(torch, model, x, y, device) -> None:
    model.to(device)
    model.train()
    criterion = torch.nn.MSELoss()
    model.zero_grad(set_to_none=True)
    pred = model(x[: min(16, x.shape[0])])
    loss = criterion(pred, y[: pred.shape[0]])
    loss.backward()
    nonzero = 0
    for param in model.parameters():
        if param.grad is not None and float(param.grad.abs().sum().detach().cpu()) > 0:
            nonzero += 1
    if nonzero == 0:
        raise RuntimeError("Single-batch gradient check failed: no nonzero gradients")


def train_one_fold(torch, model, train_x, train_y, args, device) -> float:
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    criterion = torch.nn.MSELoss()
    start = time.perf_counter()
    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        seen = 0
        for batch_x, batch_y in iter_batches(torch, train_x, train_y, args.batch_size, True, args.seed + epoch):
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
            optimizer.step()
            total_loss += float(loss.detach().cpu()) * int(batch_x.shape[0])
            seen += int(batch_x.shape[0])
        print(f"    epoch {epoch + 1}/{args.epochs}: train_mse={total_loss / max(seen, 1):.6f}", flush=True)
    return time.perf_counter() - start


def predict(torch, model, x, batch_size: int, device) -> Tuple[List[float], float]:
    model.to(device)
    model.eval()
    predictions: List[float] = []
    if device.type == "cuda":
        torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.no_grad():
        for start_index in range(0, int(x.shape[0]), batch_size):
            batch = x[start_index : start_index + batch_size]
            predictions.extend(float(v) for v in model(batch).detach().cpu().tolist())
    if device.type == "cuda":
        torch.cuda.synchronize()
    return predictions, time.perf_counter() - start


def basic_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> Dict[str, float]:
    errors = [p - t for t, p in zip(y_true, y_pred)]
    abs_errors = [abs(e) for e in errors]
    y_mean = mean(y_true)
    ss_tot = sum((t - y_mean) ** 2 for t in y_true)
    ss_res = sum((p - t) ** 2 for t, p in zip(y_true, y_pred))
    return {
        "mae": mean(abs_errors),
        "rmse": rmse(errors),
        "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan"),
        "bias": mean(errors),
    }


def macro_metrics(prediction_rows: Sequence[Mapping[str, object]], key: str) -> Dict[str, float]:
    groups: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in prediction_rows:
        groups[str(row[key])].append(row)
    maes, rmses = [], []
    for rows in groups.values():
        metrics = basic_metrics([float(r["y_true"]) for r in rows], [float(r["y_pred"]) for r in rows])
        maes.append(metrics["mae"])
        rmses.append(metrics["rmse"])
    return {"mae": mean(maes), "rmse": mean(rmses), "count": len(groups)}


def summarize_rows(
    prediction_rows: Sequence[Mapping[str, object]],
    model_name: str,
    fold: int,
    train_time: float,
    inference_time: float,
    params: int,
    trainable_params: int,
    peak_memory_mb: float,
) -> Dict[str, object]:
    y_true = [float(row["y_true"]) for row in prediction_rows]
    y_pred = [float(row["y_pred"]) for row in prediction_rows]
    window = basic_metrics(y_true, y_pred)
    session = macro_metrics(prediction_rows, "session_uid")
    group = macro_metrics(prediction_rows, "raw_pa_id")
    return {
        "model": model_name,
        "fold": fold,
        "window_count": len(prediction_rows),
        "window_mae": window["mae"],
        "window_rmse": window["rmse"],
        "window_r2": window["r2"],
        "window_bias": window["bias"],
        "session_macro_mae": session["mae"],
        "session_macro_rmse": session["rmse"],
        "raw_pa_id_group_macro_mae": group["mae"],
        "raw_pa_id_group_macro_rmse": group["rmse"],
        "train_time_seconds": train_time,
        "inference_latency_ms_per_window": inference_time / max(len(prediction_rows), 1) * 1000.0,
        "parameter_count": params,
        "trainable_parameters": trainable_params,
        "peak_gpu_memory_mb": peak_memory_mb,
    }


def slice_metric_rows(prediction_rows: Sequence[Mapping[str, object]], model_name: str, fold: int) -> List[Dict[str, object]]:
    rows = []
    for key, values in (("fms_bin", FMS_BINS), ("missing_slice", ("complete_dynamic", "missing_dynamic"))):
        for value in values:
            subset = [row for row in prediction_rows if row[key] == value]
            if not subset:
                continue
            metrics = basic_metrics([float(r["y_true"]) for r in subset], [float(r["y_pred"]) for r in subset])
            rows.append(
                {
                    "model": model_name,
                    "fold": fold,
                    "slice_type": key,
                    "slice_value": value,
                    "window_count": len(subset),
                    "mae": metrics["mae"],
                    "rmse": metrics["rmse"],
                    "bias": metrics["bias"],
                }
            )
    return rows


def load_ridge_predictions(path: Path) -> Dict[Tuple[str, str, str], float]:
    if not path.exists():
        print(f"[warn] Ridge prediction file not found; paired Ridge comparison will be unavailable: {path}", flush=True)
        return {}
    lookup: Dict[Tuple[str, str, str], float] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("model") == "ridge_window_stats" and str(float(row.get("duration_seconds", "10"))) == "10.0":
                key = (str(row["fold"]), row["session_uid"], str(row["source_row_end"]))
                lookup[key] = float(row["y_pred"])
    return lookup


def paired_ridge_rows(prediction_rows: Sequence[Mapping[str, object]], ridge_lookup: Mapping[Tuple[str, str, str], float]) -> List[Dict[str, object]]:
    rows = []
    by_fold: Dict[str, List[float]] = defaultdict(list)
    for row in prediction_rows:
        key = (str(row["fold"]), str(row["session_uid"]), str(row["source_row_end"]))
        if key not in ridge_lookup:
            continue
        model_abs = abs(float(row["y_pred"]) - float(row["y_true"]))
        ridge_abs = abs(float(ridge_lookup[key]) - float(row["y_true"]))
        by_fold[str(row["fold"])].append(model_abs - ridge_abs)
    for fold, diffs in sorted(by_fold.items(), key=lambda item: int(item[0])):
        rows.append(
            {
                "fold": fold,
                "paired_window_count": len(diffs),
                "mean_abs_error_difference_vs_ridge": mean(diffs),
                "median_abs_error_difference_vs_ridge": sorted(diffs)[len(diffs) // 2],
            }
        )
    return rows


def write_summary_readme(summary_rows: Sequence[Mapping[str, object]], paired_rows: Sequence[Mapping[str, object]], output_dir: Path) -> None:
    by_model: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in summary_rows:
        by_model[str(row["model"])].append(row)
    lines = [
        "# Ryu-Kim 10s Sequence Models",
        "",
        "Scope: Baseline v1 fixed-split sequence-model experiment. Inputs are six dynamic channels plus six missing masks only.",
        "",
        "- Split: raw_pa_id-group-disjoint split frozen from Baseline v1.",
        "- Static personalization: false.",
        "- Cross-dataset transfer or Unity real-time deployment claim: false.",
        "- FMS history, static fields, identifiers, condition, filename and future frames are excluded from model inputs.",
        "",
        "## Mean +/- Std Across Folds",
        "",
        "| model | window MAE | session MAE | group MAE | latency ms/window | params | peak GPU MB |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, rows in sorted(by_model.items()):
        lines.append(
            f"| {model} | "
            f"{mean([float(r['window_mae']) for r in rows]):.4f} +/- {stdev([float(r['window_mae']) for r in rows]):.4f} | "
            f"{mean([float(r['session_macro_mae']) for r in rows]):.4f} +/- {stdev([float(r['session_macro_mae']) for r in rows]):.4f} | "
            f"{mean([float(r['raw_pa_id_group_macro_mae']) for r in rows]):.4f} +/- {stdev([float(r['raw_pa_id_group_macro_mae']) for r in rows]):.4f} | "
            f"{mean([float(r['inference_latency_ms_per_window']) for r in rows]):.4f} | "
            f"{int(mean([float(r['parameter_count']) for r in rows]))} | "
            f"{mean([float(r['peak_gpu_memory_mb']) for r in rows]):.1f} |"
        )
    lines.extend(["", "## Ridge Pairing", ""])
    if paired_rows:
        lines.append("Negative paired differences mean the sequence model has lower absolute error than Ridge on identical windows.")
    else:
        lines.append("Ridge pairing was unavailable because the Baseline v1 Ridge prediction file was not found.")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args) -> None:
    torch, _, _ = require_torch()
    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    set_seed(torch, args.seed)
    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    print(f"[setup] device={device}", flush=True)

    config = DatasetConfig(repo_root=repo_root)
    split_path = repo_root / args.split_json
    fold_assignments = load_split_assignments(split_path)
    print(f"[setup] loaded frozen split from {split_path}", flush=True)
    sessions = load_raw_sessions(config)
    print(f"[setup] loaded {len(sessions)} raw sessions", flush=True)
    windows, exclusion = make_sequence_windows(
        sessions,
        duration_seconds=10.0,
        sample_interval_seconds=config.expected_interval_seconds,
        max_missing_fraction=args.max_missing_fraction,
    )
    assert_windows_do_not_cross_session(windows)
    print(
        f"[10s] windows={len(windows)}, excluded_missing>{args.max_missing_fraction:.0%}="
        f"{exclusion['excluded_windows_missing_fraction_gt_threshold']}",
        flush=True,
    )

    model_names = [item.strip() for item in args.models.split(",") if item.strip()]
    ridge_lookup = load_ridge_predictions(repo_root / args.ridge_predictions)
    all_metric_rows: List[Dict[str, object]] = []
    all_slice_rows: List[Dict[str, object]] = []
    all_predictions: List[Dict[str, object]] = []
    all_paired_rows: List[Dict[str, object]] = []

    for model_name in model_names:
        model_predictions: List[Dict[str, object]] = []
        print(f"[{model_name}] starting checks and folds", flush=True)
        for fold in range(args.folds):
            print(f"[{model_name}][fold {fold + 1}/{args.folds}] preparing data", flush=True)
            train_windows, test_windows = split_windows_by_frozen_fold(windows, fold_assignments, fold)
            standardizer = DynamicStandardizer().fit(windows, sorted({str(w["raw_pa_id"]) for w in train_windows}))
            train_x, train_y = tensorize_windows(torch, train_windows, standardizer, device)
            test_x, test_y = tensorize_windows(torch, test_windows, standardizer, device)
            if fold == 0:
                print(f"[{model_name}] actual input tensor: {tuple(train_x.shape)}", flush=True)
                check_model = build_model(model_name, args)
                tiny_overfit_check(torch, check_model, train_x, train_y, device)
                check_model = build_model(model_name, args)
                single_batch_gradient_check(torch, check_model, train_x, train_y, device)
                print(f"[{model_name}] tiny-overfit and gradient checks passed", flush=True)
            if device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(device)
            model = build_model(model_name, args)
            trainable = count_trainable_parameters(model)
            params = sum(p.numel() for p in model.parameters())
            print(f"[{model_name}][fold {fold + 1}/{args.folds}] params={params}", flush=True)
            train_time = train_one_fold(torch, model, train_x, train_y, args, device)
            y_pred, infer_time = predict(torch, model, test_x, args.batch_size, device)
            peak_mb = torch.cuda.max_memory_allocated(device) / (1024 * 1024) if device.type == "cuda" else 0.0
            y_true = [float(v) for v in test_y.detach().cpu().tolist()]
            prediction_rows = []
            for window, true, pred in zip(test_windows, y_true, y_pred):
                prediction_rows.append(
                    {
                        "model": model_name,
                        "duration_seconds": 10.0,
                        "fold": fold,
                        "raw_pa_id": window["raw_pa_id"],
                        "session_uid": window["session_uid"],
                        "end_time": window["end_time"],
                        "source_row_end": window["source_row_end"],
                        "missing_slice": "missing_dynamic" if window["has_missing_dynamic"] else "complete_dynamic",
                        "fms_bin": fms_bin(float(true)),
                        "y_true": true,
                        "y_pred": pred,
                    }
                )
            metrics = summarize_rows(
                prediction_rows,
                model_name,
                fold,
                train_time,
                infer_time,
                params,
                trainable,
                peak_mb,
            )
            all_metric_rows.append(metrics)
            all_slice_rows.extend(slice_metric_rows(prediction_rows, model_name, fold))
            all_predictions.extend(prediction_rows)
            model_predictions.extend(prediction_rows)
            curves = select_curve_sessions(prediction_rows)
            write_csv(curves, output_dir / f"prediction_curves_10s_fold{fold}_{model_name}.csv")
            print(
                f"[{model_name}][fold {fold + 1}/{args.folds}] "
                f"MAE={metrics['window_mae']:.4f}, sessionMAE={metrics['session_macro_mae']:.4f}, "
                f"train={train_time:.1f}s, latency={metrics['inference_latency_ms_per_window']:.4f}ms/window",
                flush=True,
            )
        all_paired_rows.extend({**row, "model": model_name} for row in paired_ridge_rows(model_predictions, ridge_lookup))

    metric_fields = [
        "model",
        "fold",
        "window_count",
        "window_mae",
        "window_rmse",
        "window_r2",
        "window_bias",
        "session_macro_mae",
        "session_macro_rmse",
        "raw_pa_id_group_macro_mae",
        "raw_pa_id_group_macro_rmse",
        "train_time_seconds",
        "inference_latency_ms_per_window",
        "parameter_count",
        "trainable_parameters",
        "peak_gpu_memory_mb",
    ]
    write_csv(all_metric_rows, output_dir / "metrics_by_fold.csv", metric_fields)
    write_csv(all_slice_rows, output_dir / "slice_metrics_by_fold.csv")
    write_csv(all_predictions, output_dir / "predictions_10s_sequence_models.csv")
    write_csv(
        all_paired_rows,
        output_dir / "paired_error_difference_vs_ridge.csv",
        [
            "model",
            "fold",
            "paired_window_count",
            "mean_abs_error_difference_vs_ridge",
            "median_abs_error_difference_vs_ridge",
        ],
    )
    write_json(
        {
            "declarations": {
                "split_name": "raw_pa_id-group-disjoint split frozen from Baseline v1",
                "true_participant_identity_confirmed": False,
                "static_personalization": False,
                "cross_dataset_or_unity_realtime_claim": False,
                "window_seconds": 10,
                "input_names": list(SEQUENCE_INPUT_NAMES),
            },
            "window_exclusion": exclusion,
        },
        output_dir / "summary.json",
    )
    write_summary_readme(all_metric_rows, all_paired_rows, output_dir)
    print(f"[final] wrote sequence-model reports to {output_dir}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train true 10s causal sequence models for Ryu-Kim FMS.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default="reports/ryu_kim_sequence_models_10s")
    parser.add_argument("--split-json", default="reports/ryu_kim_dynamic_baseline/baseline_v1_review/frozen_splits/splits_10s.json")
    parser.add_argument("--ridge-predictions", default="shared/data/exports/stage1/predictions/ryu_kim_dynamic_baseline/predictions_10s.csv")
    parser.add_argument("--models", default="lstm,causal_tcn")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--grad-clip", type=float, default=1.0)
    parser.add_argument("--max-missing-fraction", type=float, default=0.20)
    parser.add_argument("--device", default="")
    parser.add_argument("--lstm-hidden-size", type=int, default=32)
    parser.add_argument("--lstm-layers", type=int, default=1)
    parser.add_argument("--lstm-dropout", type=float, default=0.0)
    parser.add_argument("--tcn-channels", type=int, default=32)
    parser.add_argument("--tcn-levels", type=int, default=3)
    parser.add_argument("--tcn-kernel-size", type=int, default=3)
    parser.add_argument("--tcn-dropout", type=float, default=0.05)
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
