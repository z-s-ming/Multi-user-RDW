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
    set_seed,
    single_batch_gradient_check,
    slice_metric_rows,
    split_windows_by_frozen_fold,
    summarize_rows,
    tiny_overfit_check,
)


STATIC_INPUT_NAMES = ("age", "mssq", "gender_f", "gender_m", "age_missing_mask", "mssq_missing_mask", "gender_missing_mask")
DOSE_NAMES = (
    "accel_abs_integral",
    "gyro_abs_integral",
    "motion_energy",
    "jerk_integral",
    "angular_accel_integral",
    "high_stim_duration",
) + tuple(f"energy_ewma_half_life_{h}s" for h in (5, 15, 30, 60, 120))
STAT_NAMES = tuple(f"{name}_{stat}" for name in DYNAMIC_FEATURES for stat in ("mean", "std", "min", "max", "first", "last"))
STAGE4_FORBIDDEN_INPUTS = {
    "fms",
    "fms_history",
    "future_5s_delta_fms",
    "future_10s_delta_fms",
    "update_event",
    "raw_pa_id",
    "participant_id",
    "session_id",
    "session_uid",
    "condition",
    "condition_id",
    "filename",
    "source_file",
}


def assert_stage4_input_names(names: Sequence[str]) -> None:
    forbidden = STAGE4_FORBIDDEN_INPUTS.intersection(set(names))
    if forbidden:
        raise AssertionError(f"Forbidden Stage 4 model input features present: {sorted(forbidden)}")


def make_windows_with_targets(sessions, duration_seconds, sample_interval_seconds, max_missing_fraction):
    windows, exclusion = make_sequence_windows(sessions, duration_seconds, sample_interval_seconds, max_missing_fraction)
    by_session = {str(s["session_uid"]): sorted([r for r in s["rows"] if r.get("timestamp") is not None and r.get("fms") is not None], key=lambda r: (float(r["timestamp"]), int(r.get("row_index", 0)))) for s in sessions}
    row_maps = {sid: {int(r.get("row_index", idx)): idx for idx, r in enumerate(rows)} for sid, rows in by_session.items()}
    for w in windows:
        rows = by_session[str(w["session_uid"])]
        idx = row_maps[str(w["session_uid"])].get(int(w["source_row_end"]), -1)
        prev = float(rows[idx - 1]["fms"]) if idx > 0 else float(w["y_fms"])
        now = float(w["y_fms"])
        w["update_event"] = 1.0 if abs(now - prev) > 1e-12 else 0.0
        w["future_5s_delta_fms"] = future_delta(rows, idx, 5.0)
        w["future_10s_delta_fms"] = future_delta(rows, idx, 10.0)
    return windows, exclusion


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def future_delta(rows, idx: int, seconds: float) -> float:
    if idx < 0:
        return 0.0
    target = float(rows[idx]["timestamp"]) + seconds
    best = idx
    best_gap = float("inf")
    for j in range(idx + 1, len(rows)):
        gap = abs(float(rows[j]["timestamp"]) - target)
        if gap < best_gap:
            best = j
            best_gap = gap
        if float(rows[j]["timestamp"]) >= target and gap > best_gap:
            break
    return float(rows[best]["fms"]) - float(rows[idx]["fms"])


class VectorStandardizer:
    def __init__(self):
        self.mean_ = []
        self.scale_ = []

    def fit(self, rows: Sequence[Sequence[float]]):
        width = len(rows[0]) if rows else 0
        self.mean_ = []
        self.scale_ = []
        for i in range(width):
            col = [float(r[i]) for r in rows]
            m = mean(col)
            var = mean([(x - m) ** 2 for x in col])
            self.mean_.append(m)
            self.scale_.append(math.sqrt(var) or 1.0)
        return self

    def transform(self, rows: Sequence[Sequence[float]]) -> List[List[float]]:
        return [[(float(v) - self.mean_[i]) / self.scale_[i] for i, v in enumerate(row)] for row in rows]


def sequence_tensor(torch, windows, standardizer, device):
    assert_sequence_input_names(SEQUENCE_INPUT_NAMES)
    x = []
    for w in windows:
        values = standardizer.transform_window(w)
        x.append([list(v) + [float(m) for m in mask] for v, mask in zip(values, w["missing_mask"])])
    return torch.tensor(x, dtype=torch.float32, device=device)


def window_stats(w) -> List[float]:
    out = []
    for i in range(len(DYNAMIC_FEATURES)):
        col = [row[i] for row, mask in zip(w["x_dynamic"], w["missing_mask"]) if not mask[i] and row[i] is not None]
        if not col:
            out.extend([0.0] * 6)
        else:
            m = mean(col)
            out.extend([m, math.sqrt(mean([(v - m) ** 2 for v in col])), min(col), max(col), col[0], col[-1]])
    return out


def dose_features(w, dt: float = 0.5) -> List[float]:
    vals = w["x_dynamic"]
    masks = w["missing_mask"]
    clean = []
    last = [0.0] * len(DYNAMIC_FEATURES)
    for row, mask in zip(vals, masks):
        now = []
        for i, (v, miss) in enumerate(zip(row, mask)):
            if miss or v is None:
                now.append(last[i])
            else:
                now.append(float(v))
                last[i] = float(v)
        clean.append(now)
    accel_abs = sum(sum(abs(v) for v in row[:3]) * dt for row in clean)
    gyro_abs = sum(sum(abs(v) for v in row[3:]) * dt for row in clean)
    energy_series = [sum(v * v for v in row) for row in clean]
    energy = sum(e * dt for e in energy_series)
    jerk = 0.0
    angular_accel = 0.0
    for a, b in zip(clean, clean[1:]):
        jerk += sum(abs(b[i] - a[i]) / dt for i in range(3)) * dt
        angular_accel += sum(abs(b[i] - a[i]) / dt for i in range(3, 6)) * dt
    high_stim = sum(1 for e in energy_series if e >= percentile(energy_series, 0.75)) * dt if energy_series else 0.0
    ewmas = []
    for half_life in (5, 15, 30, 60, 120):
        alpha = 1.0 - math.exp(math.log(0.5) * dt / half_life)
        state = 0.0
        for e in energy_series:
            state = (1 - alpha) * state + alpha * e
        ewmas.append(state)
    return [accel_abs, gyro_abs, energy, jerk, angular_accel, high_stim] + ewmas


def static_features(w) -> List[float]:
    rows = w.get("source_rows") or []
    age = w.get("age")
    mssq = w.get("mssq")
    gender = str(w.get("gender", "")).lower()
    age_missing = 1.0 if age in (None, "") else 0.0
    mssq_missing = 1.0 if mssq in (None, "") else 0.0
    gender_missing = 1.0 if not gender else 0.0
    return [
        float(age) if not age_missing else 0.0,
        float(mssq) if not mssq_missing else 0.0,
        1.0 if gender in ("f", "female") else 0.0,
        1.0 if gender in ("m", "male") else 0.0,
        age_missing,
        mssq_missing,
        gender_missing,
    ]


def attach_static_from_sessions(windows, sessions):
    terminal = {}
    consistency_rows = []
    for s in sessions:
        ages = {r.get("age") for r in s["rows"] if r.get("age") is not None}
        mssqs = {r.get("mssq") for r in s["rows"] if r.get("mssq") is not None}
        genders = {str(r.get("gender")).lower() for r in s["rows"] if r.get("gender")}
        consistency_rows.append({"session_uid": s["session_uid"], "raw_pa_id": s["raw_pa_id"], "age_values": len(ages), "mssq_values": len(mssqs), "gender_values": len(genders), "consistent": len(ages) <= 1 and len(mssqs) <= 1 and len(genders) <= 1})
        terminal[str(s["session_uid"])] = {
            "age": next(iter(ages), None),
            "mssq": next(iter(mssqs), None),
            "gender": next(iter(genders), ""),
        }
    for w in windows:
        w.update(terminal.get(str(w["session_uid"]), {}))
    return consistency_rows


def tabular_rows(windows, kind: str) -> Tuple[List[List[float]], List[str]]:
    rows = []
    names = []
    for w in windows:
        parts = []
        if "static" in kind:
            parts.extend(static_features(w))
        if "dose" in kind:
            parts.extend(dose_features(w))
        if "stats" in kind:
            parts.extend(window_stats(w))
        rows.append(parts)
    if "static" in kind:
        names.extend(STATIC_INPUT_NAMES)
    if "dose" in kind:
        names.extend(DOSE_NAMES)
    if "stats" in kind:
        names.extend(STAT_NAMES)
    return rows, names


def build_model(torch, mode: str, seq_input: int, tab_input: int, multitask: bool = False):
    _, nn, _ = require_torch()

    class Hybrid(nn.Module):
        def __init__(self):
            super().__init__()
            self.has_seq = seq_input > 0
            self.has_tab = tab_input > 0
            if self.has_seq:
                self.lstm = nn.LSTM(seq_input, 32, batch_first=True, bidirectional=False)
            if self.has_tab:
                self.tab = nn.Sequential(nn.Linear(tab_input, 32), nn.ReLU(), nn.Linear(32, 16), nn.ReLU())
            width = (32 if self.has_seq else 0) + (16 if self.has_tab else 0)
            self.head = nn.Linear(width, 1)
            self.multitask = multitask
            if multitask:
                self.event_head = nn.Linear(width, 1)
                self.delta5_head = nn.Linear(width, 1)
                self.delta10_head = nn.Linear(width, 1)

        def encode(self, seq, tab):
            parts = []
            if self.has_seq:
                out, _ = self.lstm(seq)
                parts.append(out[:, -1, :])
            if self.has_tab:
                parts.append(self.tab(tab))
            return torch.cat(parts, dim=1) if len(parts) > 1 else parts[0]

        def forward(self, seq=None, tab=None):
            z = self.encode(seq, tab)
            if not self.multitask:
                return self.head(z).squeeze(-1)
            return self.head(z).squeeze(-1), self.event_head(z).squeeze(-1), self.delta5_head(z).squeeze(-1), self.delta10_head(z).squeeze(-1)

    return Hybrid()


def metric_rows(pred_rows, variant, fold, train_time, infer_time, params):
    y_true = [float(r["y_true"]) for r in pred_rows]
    y_pred = [float(r["y_pred"]) for r in pred_rows]
    m = basic_metrics(y_true, y_pred)
    by_session = defaultdict(list)
    by_group = defaultdict(list)
    for r in pred_rows:
        by_session[r["session_uid"]].append(r)
        by_group[r["raw_pa_id"]].append(r)
    sess_mae = [basic_metrics([float(x["y_true"]) for x in xs], [float(x["y_pred"]) for x in xs])["mae"] for xs in by_session.values()]
    group_mae = [basic_metrics([float(x["y_true"]) for x in xs], [float(x["y_pred"]) for x in xs])["mae"] for xs in by_group.values()]
    return {"variant": variant, "fold": fold, "window_count": len(pred_rows), "window_mae": m["mae"], "window_rmse": m["rmse"], "window_bias": m["bias"], "session_macro_mae": mean(sess_mae), "raw_pa_id_group_macro_mae": mean(group_mae), "train_time_seconds": train_time, "inference_latency_ms_per_window": infer_time / max(len(pred_rows), 1) * 1000, "parameter_count": params}


def auprc(labels: Sequence[int], scores: Sequence[float]) -> float:
    pairs = sorted(zip(scores, labels), reverse=True)
    positives = sum(labels)
    if positives == 0:
        return float("nan")
    tp = 0
    fp = 0
    area = 0.0
    prev_recall = 0.0
    for _, label in pairs:
        if label:
            tp += 1
        else:
            fp += 1
        recall = tp / positives
        precision = tp / max(tp + fp, 1)
        area += precision * max(0.0, recall - prev_recall)
        prev_recall = recall
    return area


def binary_metrics(labels: Sequence[int], scores: Sequence[float], threshold: float = 0.5) -> Dict[str, float]:
    preds = [1 if s >= threshold else 0 for s in scores]
    tp = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(labels, preds) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 0)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    return {"auprc": auprc(labels, scores), "precision": precision, "recall": recall, "f1": f1}


def write_history_common_anchor_metrics(output_dir: Path, pred_rows: Sequence[Mapping[str, object]]) -> None:
    by_key = defaultdict(dict)
    for row in pred_rows:
        key = (row["fold"], row["session_uid"], row["source_row_end"])
        by_key[key][str(int(float(row["duration_seconds"])))] = row
    durations = sorted({str(int(float(row["duration_seconds"]))) for row in pred_rows}, key=int)
    common = [items for items in by_key.values() if all(d in items for d in durations)]
    rows = []
    for duration in durations:
        subset = [items[duration] for items in common]
        if not subset:
            continue
        m = basic_metrics([float(r["y_true"]) for r in subset], [float(r["y_pred"]) for r in subset])
        rows.append({"duration_seconds": duration, "common_anchor_count": len(subset), "mae": m["mae"], "rmse": m["rmse"], "bias": m["bias"]})
    write_csv(rows, output_dir / "history_common_anchor_metrics.csv")


def write_multitask_aux_metrics(output_dir: Path, pred_rows: Sequence[Mapping[str, object]]) -> None:
    rows = []
    grouped = defaultdict(list)
    for row in pred_rows:
        if row.get("event_score") not in ("", None):
            grouped[(row["variant"], row["fold"])].append(row)
    for (variant, fold), items in sorted(grouped.items(), key=lambda x: (x[0][0], int(x[0][1]))):
        labels = [int(float(r["update_event_true"])) for r in items]
        scores = [float(r["event_score"]) for r in items]
        bm = binary_metrics(labels, scores)
        d5 = basic_metrics([float(r["future_5s_delta_true"]) for r in items], [float(r["future_5s_delta_pred"]) for r in items])
        d10 = basic_metrics([float(r["future_10s_delta_true"]) for r in items], [float(r["future_10s_delta_pred"]) for r in items])
        rows.append({"variant": variant, "fold": fold, "event_auprc": bm["auprc"], "event_f1": bm["f1"], "event_recall": bm["recall"], "future_5s_delta_mae": d5["mae"], "future_10s_delta_mae": d10["mae"]})
    write_csv(rows, output_dir / "multitask_auxiliary_metrics.csv")


def run_variant(args, torch, device, windows, sessions, fold_assignments, variant: str, duration: float, output_dir: Path):
    metric_out, slice_out, pred_out = [], [], []
    attach_static_from_sessions(windows, sessions)
    for fold in range(args.folds):
        train_windows, test_windows = split_windows_by_frozen_fold(windows, fold_assignments, fold)
        seq_kind = variant in ("dynamic", "dynamic_dose", "static_dynamic", "static_dynamic_dose", "local_sequence", "sequence_plus_dose", "multitask")
        tab_kind = ""
        if variant in ("dose", "dose_only", "cumulative_dose", "static_dose", "static_dynamic_dose", "sequence_plus_dose", "multitask"):
            tab_kind += "dose"
        if variant in ("stats", "window_stats"):
            tab_kind += "stats"
        if variant in ("static", "static_only", "static_dynamic", "static_dose", "static_dynamic_dose"):
            tab_kind += "_static" if tab_kind else "static"
        dyn_std = DynamicStandardizer().fit(windows, sorted({str(w["raw_pa_id"]) for w in train_windows})) if seq_kind else None
        train_seq = sequence_tensor(torch, train_windows, dyn_std, device) if seq_kind else None
        test_seq = sequence_tensor(torch, test_windows, dyn_std, device) if seq_kind else None
        train_tab = test_tab = None
        feature_names = []
        if tab_kind:
            train_rows, feature_names = tabular_rows(train_windows, tab_kind)
            test_rows, _ = tabular_rows(test_windows, tab_kind)
            assert_stage4_input_names(feature_names)
            tab_std = VectorStandardizer().fit(train_rows)
            train_tab = torch.tensor(tab_std.transform(train_rows), dtype=torch.float32, device=device)
            test_tab = torch.tensor(tab_std.transform(test_rows), dtype=torch.float32, device=device)
        if fold == 0:
            check_model = build_model(torch, variant, 12 if seq_kind else 0, len(feature_names), multitask=variant == "multitask")
            tiny_y = torch.tensor([float(w["y_fms"]) for w in train_windows], dtype=torch.float32, device=device)
            # A compact smoke check for hybrid models.
            check_model.to(device)
            out = check_model(train_seq[:16] if seq_kind else None, train_tab[:16] if tab_kind else None)
            pred = out[0] if isinstance(out, tuple) else out
            loss = ((pred - tiny_y[:16]) ** 2).mean()
            loss.backward()
        model = build_model(torch, variant, 12 if seq_kind else 0, len(feature_names), multitask=variant == "multitask").to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
        huber = torch.nn.HuberLoss()
        bce = torch.nn.BCEWithLogitsLoss(pos_weight=train_event_weight(torch, train_windows, device)) if variant == "multitask" else None
        indices = list(range(len(train_windows)))
        start = time.perf_counter()
        for epoch in range(args.epochs):
            random.Random(args.seed + epoch).shuffle(indices)
            for off in range(0, len(indices), args.batch_size):
                batch = indices[off : off + args.batch_size]
                idx = torch.tensor(batch, dtype=torch.long, device=device)
                y = torch.tensor([float(train_windows[i]["y_fms"]) for i in batch], dtype=torch.float32, device=device)
                optimizer.zero_grad(set_to_none=True)
                out = model(train_seq.index_select(0, idx) if seq_kind else None, train_tab.index_select(0, idx) if tab_kind else None)
                if variant == "multitask":
                    pred, event_logit, d5, d10 = out
                    event_y = torch.tensor([float(train_windows[i]["update_event"]) for i in batch], dtype=torch.float32, device=device)
                    d5_y = torch.tensor([float(train_windows[i]["future_5s_delta_fms"]) for i in batch], dtype=torch.float32, device=device)
                    d10_y = torch.tensor([float(train_windows[i]["future_10s_delta_fms"]) for i in batch], dtype=torch.float32, device=device)
                    loss = huber(pred, y) + args.event_loss_weight * bce(event_logit, event_y) + args.delta_loss_weight * (huber(d5, d5_y) + huber(d10, d10_y))
                else:
                    pred = out
                    loss = huber(pred, y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
        train_time = time.perf_counter() - start
        if device.type == "cuda":
            torch.cuda.synchronize()
        start = time.perf_counter()
        aux = {}
        with torch.no_grad():
            out = model(test_seq if seq_kind else None, test_tab if tab_kind else None)
            if isinstance(out, tuple):
                pred, event_logit, d5_pred, d10_pred = out
                aux["event_score"] = [float(v) for v in torch.sigmoid(event_logit).detach().cpu().tolist()]
                aux["future_5s_delta_pred"] = [float(v) for v in d5_pred.detach().cpu().tolist()]
                aux["future_10s_delta_pred"] = [float(v) for v in d10_pred.detach().cpu().tolist()]
            else:
                pred = out
            y_pred = [float(v) for v in pred.detach().cpu().tolist()]
        if device.type == "cuda":
            torch.cuda.synchronize()
        infer = time.perf_counter() - start
        rows = []
        for idx_row, (w, yp) in enumerate(zip(test_windows, y_pred)):
            item = {"variant": variant, "duration_seconds": duration, "fold": fold, "raw_pa_id": w["raw_pa_id"], "session_uid": w["session_uid"], "end_time": w["end_time"], "source_row_end": w["source_row_end"], "fms_bin": fms_bin(float(w["y_fms"])), "missing_slice": "missing_dynamic" if w["has_missing_dynamic"] else "complete_dynamic", "near_update_event": int(float(w["update_event"]) > 0), "flat_interval": int(float(w["update_event"]) == 0), "y_true": float(w["y_fms"]), "y_pred": yp, "update_event_true": float(w["update_event"]), "future_5s_delta_true": float(w["future_5s_delta_fms"]), "future_10s_delta_true": float(w["future_10s_delta_fms"])}
            for key, values in aux.items():
                item[key] = values[idx_row]
            rows.append(item)
        metric_out.append(metric_rows(rows, variant, fold, train_time, infer, sum(p.numel() for p in model.parameters())))
        slice_out.extend(slice_metric_rows(rows, variant, fold))
        pred_out.extend(rows)
        write_csv(select_curve_sessions(rows), output_dir / f"prediction_curves_{int(duration)}s_fold{fold}_{variant}.csv")
        print(f"[{variant}][{duration:.0f}s][fold {fold + 1}] MAE={metric_out[-1]['window_mae']:.4f}", flush=True)
        if args.smoke_fold_only:
            break
    return metric_out, slice_out, pred_out


def train_event_weight(torch, train_windows, device):
    pos = sum(1 for w in train_windows if float(w.get("update_event", 0.0)) > 0.0)
    neg = len(train_windows) - pos
    return torch.tensor([min(10.0, neg / pos) if pos else 1.0], dtype=torch.float32, device=device)


def write_summary(output_dir: Path, metric_rows: Sequence[Mapping[str, object]], title: str):
    by = defaultdict(list)
    for r in metric_rows:
        by[str(r["variant"])].append(r)
    lines = [f"# Stage 4 {title}", "", "| variant | window MAE | session MAE | group MAE | params |", "| --- | ---: | ---: | ---: | ---: |"]
    for variant, rows in sorted(by.items()):
        lines.append(f"| {variant} | {mean([float(r['window_mae']) for r in rows]):.4f} +/- {stdev([float(r['window_mae']) for r in rows]):.4f} | {mean([float(r['session_macro_mae']) for r in rows]):.4f} | {mean([float(r['raw_pa_id_group_macro_mae']) for r in rows]):.4f} | {int(float(rows[0]['parameter_count']))} |")
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Ryu-Kim Stage 4 data-limit and dynamic modeling diagnostics.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--experiment", choices=["history", "dose", "static", "multitask"], required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--max-missing-fraction", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke-fold-only", action="store_true")
    parser.add_argument("--event-loss-weight", type=float, default=0.25)
    parser.add_argument("--delta-loss-weight", type=float, default=0.10)
    args = parser.parse_args()
    torch, _, _ = require_torch()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    set_seed(torch, args.seed)
    repo = Path(args.repo_root)
    config = DatasetConfig(repo_root=repo)
    folds = load_split_assignments(repo / "reports/ryu_kim_dynamic_baseline/baseline_v1_review/frozen_splits/splits_10s.json")
    sessions = load_raw_sessions(config)
    out = repo / "shared/data/exports/stage4" / f"{args.experiment}_diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    all_metrics, all_slices, all_preds = [], [], []
    if args.experiment == "history":
        variants = ["dynamic"]
        durations = [10, 20, 40, 60, 120]
    elif args.experiment == "dose":
        variants = ["local_sequence", "cumulative_dose", "window_stats", "sequence_plus_dose"]
        durations = [10]
    elif args.experiment == "static":
        variants = ["static_only", "dynamic", "cumulative_dose", "static_dynamic", "static_dose", "static_dynamic_dose"]
        durations = [10]
    else:
        variants = ["dynamic", "multitask"]
        durations = [10]
    for duration in durations:
        windows, exclusion = make_windows_with_targets(sessions, float(duration), config.expected_interval_seconds, args.max_missing_fraction)
        write_json(exclusion, out / f"window_exclusion_{int(duration)}s.json")
        if args.experiment == "static":
            write_csv(attach_static_from_sessions(windows, sessions), out / "static_consistency_by_session.csv")
        for variant in variants:
            m, s, p = run_variant(args, torch, device, windows, sessions, folds, variant, float(duration), out)
            all_metrics.extend(m)
            all_slices.extend(s)
            all_preds.extend(p)
    write_csv(all_metrics, out / "metrics_by_fold.csv")
    write_csv(all_slices, out / "slice_metrics_by_fold.csv")
    write_csv(all_preds, out / "predictions_stage4.csv")
    if args.experiment == "history":
        write_history_common_anchor_metrics(out, all_preds)
    if args.experiment == "multitask":
        write_multitask_aux_metrics(out, all_preds)
    write_summary(out, all_metrics, args.experiment)
    print(f"[final] wrote Stage 4 {args.experiment} outputs to {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
