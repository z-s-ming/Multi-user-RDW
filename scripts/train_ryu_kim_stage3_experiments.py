import argparse
import csv
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple


def _bootstrap_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "python" / "src"))
    return repo_root


REPO_ROOT = _bootstrap_path()

from openrdw_ai.ryu_kim_fms.dynamic_baseline import (  # noqa: E402
    DynamicStandardizer,
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
from openrdw_ai.ryu_kim_fms.sequence_models import assert_sequence_input_names, require_torch  # noqa: E402
from scripts.train_ryu_kim_sequence_models import (  # noqa: E402
    SEQUENCE_INPUT_NAMES,
    basic_metrics,
    build_lstm_model,
    load_split_assignments,
    make_sequence_windows,
    predict,
    set_seed,
    single_batch_gradient_check,
    slice_metric_rows,
    split_windows_by_frozen_fold,
    summarize_rows,
    tiny_overfit_check,
)


HIGH_FMS_INPUTS = SEQUENCE_INPUT_NAMES
TIME_SINCE_INPUTS = SEQUENCE_INPUT_NAMES + tuple(f"{name}_time_since_observed" for name in DYNAMIC_FEATURES)


def bin_weight_map(train_windows: Sequence[Mapping[str, object]], max_weight: float) -> Dict[str, float]:
    counts = Counter(fms_bin(float(w["y_fms"])) for w in train_windows)
    total = sum(counts.values())
    bins = [name for name in ("0-5", "5-10", "10-15", "15-20") if counts[name]]
    weights = {}
    for name in bins:
        weights[name] = min(max_weight, total / (len(bins) * counts[name]))
    return weights


def pos_weight_for_high_fms(torch, train_windows: Sequence[Mapping[str, object]], max_weight: float, device):
    positives = sum(1 for w in train_windows if float(w["y_fms"]) >= 15.0)
    negatives = len(train_windows) - positives
    value = min(max_weight, negatives / positives) if positives else max_weight
    return torch.tensor([value], dtype=torch.float32, device=device)


def _standardized_value(value, missing: int, mean_value: float, scale_value: float) -> float:
    if missing or value is None:
        return 0.0
    return (float(value) - mean_value) / scale_value


def tensorize_with_strategy(torch, windows, standardizer, device, missing_strategy: str):
    input_names = TIME_SINCE_INPUTS if missing_strategy == "ffill_mask_time" else HIGH_FMS_INPUTS
    assert_sequence_input_names(input_names)
    rows = []
    labels = []
    for window in windows:
        last_observed = [0.0 for _ in DYNAMIC_FEATURES]
        time_since = [0.0 for _ in DYNAMIC_FEATURES]
        sample_rows = []
        for values, mask in zip(window["x_dynamic"], window["missing_mask"]):
            dynamic = []
            since = []
            for index, (value, missing) in enumerate(zip(values, mask)):
                if missing:
                    if missing_strategy.startswith("ffill"):
                        dynamic.append(last_observed[index])
                        time_since[index] += 1.0
                    else:
                        dynamic.append(0.0)
                else:
                    z = _standardized_value(value, missing, standardizer.mean_[index], standardizer.scale_[index])
                    dynamic.append(z)
                    last_observed[index] = z
                    time_since[index] = 0.0
                since.append(time_since[index])
            row = dynamic + [float(v) for v in mask]
            if missing_strategy == "ffill_mask_time":
                row += since
            sample_rows.append(row)
        rows.append(sample_rows)
        labels.append(float(window["y_fms"]))
    return (
        torch.tensor(rows, dtype=torch.float32, device=device),
        torch.tensor(labels, dtype=torch.float32, device=device),
    )


def missing_block_class(window: Mapping[str, object]) -> str:
    max_run = 0
    current = 0
    for mask in window["missing_mask"]:
        if any(int(v) for v in mask):
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    if max_run == 0:
        return "no_missing"
    if max_run <= 2:
        return "short_contiguous_missing"
    return "long_contiguous_missing"


def build_multitask_lstm(torch, input_size: int, hidden_size: int, num_layers: int, dropout: float):
    _, nn, _ = require_torch()

    class MultiTaskLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=dropout if num_layers > 1 else 0.0,
                bidirectional=False,
            )
            self.regression_head = nn.Linear(hidden_size, 1)
            self.high_fms_head = nn.Linear(hidden_size, 1)

        def forward(self, x):
            output, _ = self.lstm(x)
            hidden = output[:, -1, :]
            return self.regression_head(hidden).squeeze(-1), self.high_fms_head(hidden).squeeze(-1)

    return MultiTaskLSTM()


def build_stage3_model(torch, variant: str, input_size: int, args):
    if variant == "multitask_high_fms_lstm":
        return build_multitask_lstm(torch, input_size, args.lstm_hidden_size, args.lstm_layers, args.lstm_dropout)
    return build_lstm_model(input_size=input_size, hidden_size=args.lstm_hidden_size, num_layers=args.lstm_layers, dropout=args.lstm_dropout)


def model_predict(torch, model, variant: str, x, batch_size: int, device) -> Tuple[List[float], float]:
    model.to(device)
    model.eval()
    predictions = []
    if device.type == "cuda":
        torch.cuda.synchronize()
    start = time.perf_counter()
    with torch.no_grad():
        for start_index in range(0, int(x.shape[0]), batch_size):
            batch = x[start_index : start_index + batch_size]
            output = model(batch)
            pred = output[0] if isinstance(output, tuple) else output
            predictions.extend(float(v) for v in pred.detach().cpu().tolist())
    if device.type == "cuda":
        torch.cuda.synchronize()
    return predictions, time.perf_counter() - start


def train_stage3_fold(torch, model, variant: str, train_x, train_y, train_windows, args, device) -> float:
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    huber = torch.nn.HuberLoss(delta=args.huber_delta, reduction="none")
    bce = None
    if variant == "multitask_high_fms_lstm":
        bce = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight_for_high_fms(torch, train_windows, args.max_aux_pos_weight, device), reduction="none")
    weights_by_bin = bin_weight_map(train_windows, args.max_bin_weight) if variant == "weighted_huber_lstm" else {}
    sample_weights = torch.tensor(
        [weights_by_bin.get(fms_bin(float(w["y_fms"])), 1.0) for w in train_windows],
        dtype=torch.float32,
        device=device,
    )
    indices = list(range(int(train_x.shape[0])))
    start = time.perf_counter()
    for epoch in range(args.epochs):
        random.Random(args.seed + epoch).shuffle(indices)
        total_loss = 0.0
        seen = 0
        for offset in range(0, len(indices), args.batch_size):
            batch_indices = indices[offset : offset + args.batch_size]
            idx = torch.tensor(batch_indices, dtype=torch.long, device=device)
            x = train_x.index_select(0, idx)
            y = train_y.index_select(0, idx)
            optimizer.zero_grad(set_to_none=True)
            output = model(x)
            if isinstance(output, tuple):
                pred, high_logit = output
            else:
                pred, high_logit = output, None
            losses = huber(pred, y)
            if variant == "weighted_huber_lstm":
                losses = losses * sample_weights.index_select(0, idx)
            loss = losses.mean()
            if high_logit is not None and bce is not None:
                high_target = (y >= 15.0).float()
                loss = loss + args.aux_loss_weight * bce(high_logit, high_target).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
            optimizer.step()
            total_loss += float(loss.detach().cpu()) * len(batch_indices)
            seen += len(batch_indices)
        print(f"    epoch {epoch + 1}/{args.epochs}: train_loss={total_loss / max(seen, 1):.6f}", flush=True)
    return time.perf_counter() - start


def summarize_experiment(
    rows: Sequence[Mapping[str, object]],
    variant: str,
    fold: int,
    train_time: float,
    inference_time: float,
    params: int,
    trainable: int,
    peak_mb: float,
) -> Dict[str, object]:
    base = summarize_rows(rows, variant, fold, train_time, inference_time, params, trainable, peak_mb)
    base["variant"] = variant
    return base


def write_experiment_readme(output_dir: Path, metric_rows: Sequence[Mapping[str, object]], experiment: str) -> None:
    by_variant = defaultdict(list)
    for row in metric_rows:
        by_variant[str(row["variant"])].append(row)
    lines = [
        f"# Stage 3 {experiment.replace('_', ' ').title()}",
        "",
        "All runs reuse the Stage 2 frozen 10s split and test samples.",
        "",
        "| variant | window MAE | session MAE | group MAE | params | peak GPU MB |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant, rows in sorted(by_variant.items()):
        lines.append(
            f"| {variant} | "
            f"{mean([float(r['window_mae']) for r in rows]):.4f} +/- {stdev([float(r['window_mae']) for r in rows]):.4f} | "
            f"{mean([float(r['session_macro_mae']) for r in rows]):.4f} +/- {stdev([float(r['session_macro_mae']) for r in rows]):.4f} | "
            f"{mean([float(r['raw_pa_id_group_macro_mae']) for r in rows]):.4f} +/- {stdev([float(r['raw_pa_id_group_macro_mae']) for r in rows]):.4f} | "
            f"{int(float(rows[0]['parameter_count']))} | "
            f"{mean([float(r['peak_gpu_memory_mb']) for r in rows]):.1f} |"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiment(args) -> None:
    torch, _, _ = require_torch()
    repo = Path(args.repo_root).resolve()
    set_seed(torch, args.seed)
    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    config = DatasetConfig(repo_root=repo)
    fold_assignments = load_split_assignments(repo / args.split_json)
    sessions = load_raw_sessions(config)
    windows, exclusion = make_sequence_windows(sessions, 10.0, config.expected_interval_seconds, args.max_missing_fraction)
    print(f"[setup] device={device}, windows={len(windows)}, excluded={exclusion['excluded_windows_missing_fraction_gt_threshold']}", flush=True)

    if args.experiment == "high_fms":
        variants = ["standard_huber_lstm", "weighted_huber_lstm", "multitask_high_fms_lstm"]
        output_dir = repo / "shared/data/exports/stage3/high_fms_experiments"
    elif args.experiment == "missingness":
        variants = ["zero_mask_lstm", "ffill_mask_lstm", "ffill_mask_time_lstm"]
        output_dir = repo / "shared/data/exports/stage3/missingness_experiments"
    else:
        raise ValueError(args.experiment)
    output_dir.mkdir(parents=True, exist_ok=True)
    metric_rows = []
    slice_rows = []
    prediction_rows_all = []

    for variant in variants:
        print(f"[{variant}] starting", flush=True)
        strategy = "zero"
        if variant == "ffill_mask_lstm":
            strategy = "ffill"
        elif variant == "ffill_mask_time_lstm":
            strategy = "ffill_mask_time"
        input_size = 18 if strategy == "ffill_mask_time" else 12
        for fold in range(args.folds):
            train_windows, test_windows = split_windows_by_frozen_fold(windows, fold_assignments, fold)
            standardizer = DynamicStandardizer().fit(windows, sorted({str(w["raw_pa_id"]) for w in train_windows}))
            train_x, train_y = tensorize_with_strategy(torch, train_windows, standardizer, device, strategy)
            test_x, test_y = tensorize_with_strategy(torch, test_windows, standardizer, device, strategy)
            if fold == 0:
                check_model = build_stage3_model(torch, "standard_huber_lstm", input_size, args)
                tiny_overfit_check(torch, check_model, train_x, train_y, device)
                check_model = build_stage3_model(torch, "standard_huber_lstm", input_size, args)
                single_batch_gradient_check(torch, check_model, train_x, train_y, device)
                print(f"[{variant}] tiny-overfit and gradient checks passed; input={tuple(train_x.shape)}", flush=True)
            if args.smoke_fold_only and fold > 0:
                continue
            if device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(device)
            model_variant = "multitask_high_fms_lstm" if variant == "multitask_high_fms_lstm" else variant
            model = build_stage3_model(torch, model_variant, input_size, args)
            params = sum(p.numel() for p in model.parameters())
            trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
            train_time = train_stage3_fold(torch, model, model_variant, train_x, train_y, train_windows, args, device)
            y_pred, inference_time = model_predict(torch, model, model_variant, test_x, args.batch_size, device)
            peak_mb = torch.cuda.max_memory_allocated(device) / (1024 * 1024) if device.type == "cuda" else 0.0
            y_true = [float(v) for v in test_y.detach().cpu().tolist()]
            prediction_rows = []
            for window, true, pred in zip(test_windows, y_true, y_pred):
                missing_class = missing_block_class(window)
                prediction_rows.append(
                    {
                        "variant": variant,
                        "model": variant,
                        "fold": fold,
                        "raw_pa_id": window["raw_pa_id"],
                        "session_uid": window["session_uid"],
                        "end_time": window["end_time"],
                        "source_row_end": window["source_row_end"],
                        "missing_slice": "missing_dynamic" if window["has_missing_dynamic"] else "complete_dynamic",
                        "missing_block_class": missing_class,
                        "fms_bin": fms_bin(true),
                        "y_true": true,
                        "y_pred": pred,
                    }
                )
            metric = summarize_experiment(prediction_rows, variant, fold, train_time, inference_time, params, trainable, peak_mb)
            metric_rows.append(metric)
            slice_rows.extend(slice_metric_rows(prediction_rows, variant, fold))
            for missing_class in ("no_missing", "short_contiguous_missing", "long_contiguous_missing"):
                subset = [row for row in prediction_rows if row["missing_block_class"] == missing_class]
                if subset:
                    m = basic_metrics([float(r["y_true"]) for r in subset], [float(r["y_pred"]) for r in subset])
                    slice_rows.append({"model": variant, "fold": fold, "slice_type": "missing_block_class", "slice_value": missing_class, "window_count": len(subset), "mae": m["mae"], "rmse": m["rmse"], "bias": m["bias"]})
            prediction_rows_all.extend(prediction_rows)
            write_csv(select_curve_sessions(prediction_rows), output_dir / f"prediction_curves_10s_fold{fold}_{variant}.csv")
            print(f"[{variant}][fold {fold + 1}/{args.folds}] MAE={metric['window_mae']:.4f}, sessionMAE={metric['session_macro_mae']:.4f}", flush=True)

    write_csv(metric_rows, output_dir / "metrics_by_fold.csv")
    write_csv(slice_rows, output_dir / "slice_metrics_by_fold.csv")
    write_csv(prediction_rows_all, output_dir / "predictions_10s_stage3.csv")
    write_json({"window_exclusion": exclusion, "experiment": args.experiment}, output_dir / "summary.json")
    write_experiment_readme(output_dir, metric_rows, args.experiment)
    print(f"[final] wrote {args.experiment} outputs to {output_dir}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 3 Ryu-Kim 10s LSTM experiments.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--split-json", default="reports/ryu_kim_dynamic_baseline/baseline_v1_review/frozen_splits/splits_10s.json")
    parser.add_argument("--experiment", choices=["high_fms", "missingness"], required=True)
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
    parser.add_argument("--huber-delta", type=float, default=1.0)
    parser.add_argument("--max-bin-weight", type=float, default=3.0)
    parser.add_argument("--max-aux-pos-weight", type=float, default=5.0)
    parser.add_argument("--aux-loss-weight", type=float, default=0.25)
    parser.add_argument("--smoke-fold-only", action="store_true")
    args = parser.parse_args()
    run_experiment(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
