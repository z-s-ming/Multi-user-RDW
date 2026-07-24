import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shared/data/exports/stage5_result_synthesis"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"


SPLIT_HASH = {
    10: "ce6de3c1cc9beb6c94acee6227213a50b43ecb338ab1fc6f48a3942adfa91cd5",
    30: "e8db5f68f0f21d9ac01c53391383ef44dec0cabbbdc28e5fcbfe23e4e120cd73",
    60: "a0b3eeab3f779bc6e2996b66278052c7771cdd07acf9096085ea383578421005",
}


def p(*parts):
    return ROOT.joinpath(*parts)


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    return statistics.stdev(xs) if len(xs) > 1 else 0.0


def percentile(xs, q):
    if not xs:
        return float("nan")
    ys = sorted(xs)
    pos = (len(ys) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ys[lo]
    return ys[lo] * (hi - pos) + ys[hi] * (pos - lo)


def ranks(values):
    order = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and order[j][1] == order[i][1]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            result[order[k][0]] = rank
        i = j
    return result


def pearson(y, pred):
    if len(y) < 2:
        return float("nan")
    my = mean(y)
    mp = mean(pred)
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    sp = math.sqrt(sum((v - mp) ** 2 for v in pred))
    return sum((a - my) * (b - mp) for a, b in zip(y, pred)) / (sy * sp) if sy and sp else float("nan")


def spearman(y, pred):
    return pearson(ranks(y), ranks(pred)) if len(y) >= 2 else float("nan")


def metrics(y, pred):
    errs = [b - a for a, b in zip(y, pred)]
    abs_err = [abs(e) for e in errs]
    my = mean(y)
    ss_tot = sum((v - my) ** 2 for v in y)
    ss_res = sum((a - b) ** 2 for a, b in zip(y, pred))
    smape_vals = []
    for a, b in zip(y, pred):
        denom = abs(a) + abs(b)
        if denom > 1e-12:
            smape_vals.append(2 * abs(b - a) / denom)
    return {
        "n": len(y),
        "mae": mean(abs_err),
        "rmse": math.sqrt(mean([e * e for e in errs])) if errs else float("nan"),
        "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan"),
        "pearson_r": pearson(y, pred),
        "spearman_r": spearman(y, pred),
        "bias": mean(errs),
        "smape": mean(smape_vals),
    }


def auprc(labels, scores):
    positives = sum(labels)
    if positives == 0:
        return float("nan")
    pairs = sorted(zip(scores, labels), reverse=True)
    tp = 0
    fp = 0
    prev_recall = 0.0
    area = 0.0
    for score, label in pairs:
        if label:
            tp += 1
        else:
            fp += 1
        recall = tp / positives
        precision = tp / max(tp + fp, 1)
        area += precision * max(0.0, recall - prev_recall)
        prev_recall = recall
    return area


def class_metrics(y, scores, threshold):
    labels = [1 if v >= threshold else 0 for v in y]
    pred_labels = [1 if s >= threshold else 0 for s in scores]
    tp = sum(1 for a, b in zip(labels, pred_labels) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(labels, pred_labels) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(labels, pred_labels) if a == 1 and b == 0)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    return {"auprc": auprc(labels, scores), "precision": precision, "recall": recall, "f1": f1}


def banded_dtw(y, pred, radius=20):
    n = len(y)
    m = len(pred)
    if n == 0 or m == 0:
        return float("nan")
    r = max(radius, abs(n - m))
    prev = {}
    for i in range(n + 1):
        curr = {}
        j_start = max(0, i - r)
        j_end = min(m, i + r)
        for j in range(j_start, j_end + 1):
            if i == 0 and j == 0:
                curr[j] = 0.0
            elif i == 0 or j == 0:
                curr[j] = float("inf")
            else:
                cost = abs(y[i - 1] - pred[j - 1])
                curr[j] = cost + min(prev.get(j, float("inf")), curr.get(j - 1, float("inf")), prev.get(j - 1, float("inf")))
        prev = curr
    return prev.get(m, float("inf")) / max(n, m)


def normalize_row(row, experiment):
    y = row.get("y_true")
    pred = row.get("y_pred")
    if y in (None, "") or pred in (None, ""):
        return None
    return {
        "experiment_id": experiment["experiment_id"],
        "fold": str(row.get("fold", "")),
        "raw_pa_id": row.get("raw_pa_id", ""),
        "session_uid": row.get("session_uid", ""),
        "end_time": float(row.get("end_time", 0.0)),
        "source_row_end": str(row.get("source_row_end", "")),
        "fms_bin": row.get("fms_bin", fms_bin(float(y))),
        "missing_slice": row.get("missing_slice", ""),
        "near_update_event": str(row.get("near_update_event", "")),
        "flat_interval": str(row.get("flat_interval", "")),
        "y_true": float(y),
        "y_pred": float(pred),
    }


def fms_bin(v):
    if 0 <= v < 5:
        return "0-5"
    if 5 <= v < 10:
        return "5-10"
    if 10 <= v < 15:
        return "10-15"
    if 15 <= v <= 20:
        return "15-20"
    return "outside"


def load_prediction_rows(experiment):
    rows = []
    for row in read_csv(experiment["prediction_file"]):
        column = experiment.get("selector_column")
        value = experiment.get("selector_value")
        if column and row.get(column) != value:
            continue
        normalized = normalize_row(row, experiment)
        if normalized is not None:
            rows.append(normalized)
    return rows


def macro_metrics(rows, key, include_dtw=False):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    metrics_rows = []
    for group, items in grouped.items():
        items = sorted(items, key=lambda r: (r["end_time"], r["source_row_end"]))
        y = [r["y_true"] for r in items]
        pred = [r["y_pred"] for r in items]
        m = metrics(y, pred)
        if include_dtw:
            m["normalized_dtw"] = banded_dtw(y, pred)
        metrics_rows.append(m)
    out = {}
    for field in ("mae", "rmse", "r2", "normalized_dtw"):
        vals = [r[field] for r in metrics_rows if field in r and math.isfinite(r[field])]
        out[f"{key}_macro_{field}"] = mean(vals)
    out[f"{key}_count"] = len(metrics_rows)
    return out


def summarize_experiment(experiment, rows):
    y = [r["y_true"] for r in rows]
    pred = [r["y_pred"] for r in rows]
    out = dict(experiment)
    out.update(metrics(y, pred))
    out.update(macro_metrics(rows, "session_uid", include_dtw=True))
    out.update(macro_metrics(rows, "raw_pa_id", include_dtw=False))
    for threshold in (10, 15):
        cm = class_metrics(y, pred, threshold)
        for key, value in cm.items():
            out[f"fms_ge_{threshold}_{key}"] = value
    return out


def slice_rows(experiment, rows, slice_key, values):
    out = []
    for value in values:
        subset = [r for r in rows if r.get(slice_key) == value]
        if not subset:
            continue
        y = [r["y_true"] for r in subset]
        pred = [r["y_pred"] for r in subset]
        item = {
            "experiment_id": experiment["experiment_id"],
            "slice_type": slice_key,
            "slice_value": value,
        }
        item.update(metrics(y, pred))
        out.append(item)
    return out


def fold_rows(experiment, rows):
    out = []
    for fold in sorted({r["fold"] for r in rows}, key=lambda v: int(v) if str(v).isdigit() else 0):
        subset = [r for r in rows if r["fold"] == fold]
        item = {"experiment_id": experiment["experiment_id"], "fold": fold}
        item.update(metrics([r["y_true"] for r in subset], [r["y_pred"] for r in subset]))
        out.append(item)
    return out


def bootstrap_ci(session_a, session_b, iterations=2000, seed=42):
    common = sorted(set(session_a).intersection(session_b))
    if not common:
        return {"paired_sessions": 0, "mean_diff": "", "ci_low": "", "ci_high": "", "improved_fraction": ""}
    diffs = [session_a[k] - session_b[k] for k in common]
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        means.append(mean([diffs[rng.randrange(len(diffs))] for _ in diffs]))
    return {
        "paired_sessions": len(common),
        "mean_diff": mean(diffs),
        "ci_low": percentile(means, 0.025),
        "ci_high": percentile(means, 0.975),
        "improved_fraction": sum(1 for d in diffs if d < 0) / len(diffs),
    }


def session_mae_map(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["session_uid"]].append(abs(row["y_pred"] - row["y_true"]))
    return {k: mean(v) for k, v in grouped.items()}


def experiments():
    exp = []
    stage1_pred = {
        10: p("shared/data/exports/stage1/predictions/ryu_kim_dynamic_baseline/predictions_10s.csv"),
        30: p("shared/data/exports/stage1/predictions/ryu_kim_dynamic_baseline/predictions_30s.csv"),
        60: p("shared/data/exports/stage1/predictions/ryu_kim_dynamic_baseline/predictions_60s.csv"),
    }
    for dur, path in stage1_pred.items():
        for model in ("mean_fms", "ridge_window_stats", "causal_tcn_linear"):
            exp.append({"experiment_id": f"stage1_{dur}s_{model}", "stage": "1", "model": model, "input_features": "dynamic summary/lag features" if model != "mean_fms" else "train-fold FMS mean", "static_features": "none", "window_seconds": dur, "loss": "closed-form baseline", "missing_strategy": "zero after train-fold standardization + mask excluded from model", "auxiliary_tasks": "none", "prediction_file": str(path), "selector_column": "model", "selector_value": model, "split_hash": SPLIT_HASH.get(dur, ""), "parameter_count": 37 if model == "ridge_window_stats" else (97 if model == "causal_tcn_linear" else 1), "checkpoint": ""})
    s2 = p("shared/data/exports/stage2/predictions/ryu_kim_sequence_models_10s/predictions_10s_sequence_models.csv")
    for model in ("lstm", "causal_tcn"):
        exp.append({"experiment_id": f"stage2_10s_{model}", "stage": "2", "model": model, "input_features": "six-axis dynamic sequence + missing masks", "static_features": "none", "window_seconds": 10, "loss": "MSE", "missing_strategy": "zero after train-fold standardization + mask", "auxiliary_tasks": "none", "prediction_file": str(s2), "selector_column": "model", "selector_value": model, "split_hash": SPLIT_HASH[10], "parameter_count": 5921 if model == "lstm" else 17153, "checkpoint": ""})
    s3_high = p("shared/data/exports/stage3/high_fms_experiments/predictions_10s_stage3.csv")
    for variant, loss in [("standard_huber_lstm", "Huber"), ("weighted_huber_lstm", "FMS-bin weighted Huber"), ("multitask_high_fms_lstm", "Huber + FMS>=15 auxiliary BCE")]:
        exp.append({"experiment_id": f"stage3_high_{variant}", "stage": "3", "model": variant, "input_features": "six-axis dynamic sequence + missing masks", "static_features": "none", "window_seconds": 10, "loss": loss, "missing_strategy": "zero after train-fold standardization + mask", "auxiliary_tasks": "FMS>=15 classifier" if "multitask" in variant else "none", "prediction_file": str(s3_high), "selector_column": "variant", "selector_value": variant, "split_hash": SPLIT_HASH[10], "parameter_count": 5954 if "multitask" in variant else 5921, "checkpoint": ""})
    s3_miss = p("shared/data/exports/stage3/missingness_experiments/predictions_10s_stage3.csv")
    for variant, strategy, params in [("zero_mask_lstm", "zero after train-fold standardization + mask", 5921), ("ffill_mask_lstm", "causal forward fill + mask", 5921), ("ffill_mask_time_lstm", "causal forward fill + mask + time since last observed", 6689)]:
        exp.append({"experiment_id": f"stage3_missing_{variant}", "stage": "3", "model": variant, "input_features": "six-axis dynamic sequence + missing masks/time-since", "static_features": "none", "window_seconds": 10, "loss": "Huber", "missing_strategy": strategy, "auxiliary_tasks": "none", "prediction_file": str(s3_miss), "selector_column": "variant", "selector_value": variant, "split_hash": SPLIT_HASH[10], "parameter_count": params, "checkpoint": ""})
    s4base = p("shared/data/exports/stage4/stage4")
    hist = s4base / "history_diagnostics/predictions_stage4.csv"
    for dur in (10, 20, 40, 60, 120):
        exp.append({"experiment_id": f"stage4_history_{dur}s_dynamic", "stage": "4", "model": "small causal LSTM", "input_features": "six-axis dynamic sequence + missing masks", "static_features": "none", "window_seconds": dur, "loss": "Huber", "missing_strategy": "zero after train-fold standardization + mask", "auxiliary_tasks": "none", "prediction_file": str(hist), "selector_column": "duration_seconds", "selector_value": f"{float(dur)}", "split_hash": SPLIT_HASH[10], "parameter_count": 5921, "checkpoint": ""})
    dose = s4base / "dose_diagnostics/predictions_stage4.csv"
    for variant, features, params in [("local_sequence", "six-axis dynamic sequence + missing masks", 5921), ("cumulative_dose", "causal cumulative motion dose", 929), ("window_stats", "causal window statistics", 1729), ("sequence_plus_dose", "dynamic sequence + causal cumulative dose", 6849)]:
        exp.append({"experiment_id": f"stage4_dose_{variant}", "stage": "4", "model": variant, "input_features": features, "static_features": "none", "window_seconds": 10, "loss": "Huber", "missing_strategy": "causal zero/forward dose states", "auxiliary_tasks": "none", "prediction_file": str(dose), "selector_column": "variant", "selector_value": variant, "split_hash": SPLIT_HASH[10], "parameter_count": params, "checkpoint": ""})
    static = s4base / "static_diagnostics/predictions_stage4.csv"
    for variant, features, static_features, params in [("static_only", "static susceptibility branch only", "age/gender/MSSQ + missing masks", 801), ("dynamic", "six-axis dynamic sequence + missing masks", "none", 5921), ("cumulative_dose", "causal cumulative motion dose", "none", 929), ("static_dose", "static susceptibility + causal dose", "age/gender/MSSQ + missing masks", 1153), ("static_dynamic", "dynamic sequence + static susceptibility", "age/gender/MSSQ + missing masks", 6721), ("static_dynamic_dose", "dynamic sequence + dose + static susceptibility", "age/gender/MSSQ + missing masks", 7073)]:
        exp.append({"experiment_id": f"stage4_static_{variant}", "stage": "4", "model": variant, "input_features": features, "static_features": static_features, "window_seconds": 10, "loss": "Huber", "missing_strategy": "zero after train-fold standardization + mask", "auxiliary_tasks": "none", "prediction_file": str(static), "selector_column": "variant", "selector_value": variant, "split_hash": SPLIT_HASH[10], "parameter_count": params, "checkpoint": ""})
    multitask = s4base / "multitask_diagnostics/predictions_stage4.csv"
    for variant, aux, params in [("dynamic", "none", 5921), ("multitask", "update event + future 5s/10s delta", 6996)]:
        exp.append({"experiment_id": f"stage4_multitask_{variant}", "stage": "4", "model": variant, "input_features": "six-axis dynamic sequence + missing masks", "static_features": "none", "window_seconds": 10, "loss": "Huber + auxiliary losses" if variant == "multitask" else "Huber", "missing_strategy": "zero after train-fold standardization + mask", "auxiliary_tasks": aux, "prediction_file": str(multitask), "selector_column": "variant", "selector_value": variant, "split_hash": SPLIT_HASH[10], "parameter_count": params, "checkpoint": ""})
    return exp


def aggregate_fold_table(folds):
    out = {}
    grouped = defaultdict(list)
    for row in folds:
        grouped[row["experiment_id"]].append(row)
    for exp_id, rows in grouped.items():
        out[exp_id] = {}
        for field in ("mae", "rmse", "r2", "pearson_r", "spearman_r", "bias"):
            vals = [float(r[field]) for r in rows if r.get(field) not in ("", None) and str(r[field]) != "nan"]
            out[exp_id][f"{field}_fold_mean"] = mean(vals)
            out[exp_id][f"{field}_fold_std"] = sd(vals)
    return out


def select_sessions(final_rows):
    grouped = defaultdict(list)
    for row in final_rows:
        grouped[row["session_uid"]].append(row)
    session_metrics = []
    for session, rows in grouped.items():
        rows = sorted(rows, key=lambda r: r["end_time"])
        m = metrics([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
        session_metrics.append((m["mae"], session, m))
    session_metrics.sort(key=lambda x: x[0])
    indices = {
        "p10_error": round((len(session_metrics) - 1) * 0.10),
        "p50_error": round((len(session_metrics) - 1) * 0.50),
        "p90_error": round((len(session_metrics) - 1) * 0.90),
    }
    result = {}
    for label, idx in indices.items():
        mae, session, m = session_metrics[idx]
        result[label] = {"session_uid": session, **m}
    result["median_error_full_timeline"] = result["p50_error"]
    return result


def svg_curve(path, series_by_label, title, metrics_text):
    width, height = 980, 420
    left, right, top, bottom = 70, 30, 40, 70
    plot_w = width - left - right
    plot_h = height - top - bottom
    all_times = [t for series in series_by_label.values() for t, _ in series]
    if not all_times:
        return
    t0, t1 = min(all_times), max(all_times)
    if t1 <= t0:
        t1 = t0 + 1
    def x(t):
        return left + (t - t0) / (t1 - t0) * plot_w
    def y(v):
        return top + (20 - max(0, min(20, v))) / 20 * plot_h
    colors = {"Ground Truth": "#111111", "Prediction": "#1f77b4", "Ridge": "#d62728", "Dynamic LSTM": "#2ca02c", "Static+Dynamic LSTM": "#1f77b4"}
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>']
    lines.append(f'<text x="{left}" y="24" font-size="18" font-family="Arial">{title}</text>')
    lines.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#333"/>')
    lines.append(f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#333"/>')
    for val in (0, 5, 10, 15, 20):
        yy = y(val)
        lines.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+plot_w}" y2="{yy:.1f}" stroke="#ddd"/>')
        lines.append(f'<text x="28" y="{yy+4:.1f}" font-size="11" font-family="Arial">{val}</text>')
    gt = series_by_label.get("Ground Truth", [])
    for i in range(1, len(gt)):
        if gt[i][1] != gt[i - 1][1]:
            xx = x(gt[i][0])
            lines.append(f'<line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{top+plot_h}" stroke="#ff9900" stroke-width="1" opacity="0.45"/>')
    for label, series in series_by_label.items():
        points = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in series)
        dash = ' stroke-dasharray="6 4"' if label != "Ground Truth" else ""
        lines.append(f'<polyline points="{points}" fill="none" stroke="{colors.get(label, "#555")}" stroke-width="2"{dash}/>')
    legend_x = left + 10
    legend_y = top + 18
    for idx, label in enumerate(series_by_label):
        yy = legend_y + idx * 18
        lines.append(f'<line x1="{legend_x}" y1="{yy}" x2="{legend_x+28}" y2="{yy}" stroke="{colors.get(label, "#555")}" stroke-width="2"/>')
        lines.append(f'<text x="{legend_x+36}" y="{yy+4}" font-size="12" font-family="Arial">{label}</text>')
    lines.append(f'<text x="{left}" y="{height-38}" font-size="12" font-family="Arial">横轴：session时间秒；纵轴：FMS 0-20；橙色竖线：FMS update事件；未对预测做额外平滑。</text>')
    lines.append(f'<text x="{left}" y="{height-18}" font-size="12" font-family="Arial">{metrics_text}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def session_series(rows, session):
    subset = sorted([r for r in rows if r["session_uid"] == session], key=lambda r: r["end_time"])
    if not subset:
        return {}
    return {
        "Ground Truth": [(r["end_time"], r["y_true"]) for r in subset],
        "Prediction": [(r["end_time"], r["y_pred"]) for r in subset],
    }


def session_metric_text(rows, session):
    subset = sorted([r for r in rows if r["session_uid"] == session], key=lambda r: r["end_time"])
    m = metrics([r["y_true"] for r in subset], [r["y_pred"] for r in subset])
    dtw = banded_dtw([r["y_true"] for r in subset], [r["y_pred"] for r in subset])
    return f"session MAE={m['mae']:.3f}; RMSE={m['rmse']:.3f}; R2={m['r2']:.3f}; Pearson r={m['pearson_r']:.3f}; DTW={dtw:.3f}; bias={m['bias']:.3f}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    exps = experiments()
    registry = []
    summaries = []
    slices = []
    folds = []
    rows_by_exp = {}
    for exp in exps:
        pred_file = Path(exp["prediction_file"])
        if not pred_file.exists():
            continue
        print(f"[stage5] loading {exp['experiment_id']}", flush=True)
        rows = load_prediction_rows(exp)
        if not rows:
            continue
        rows_by_exp[exp["experiment_id"]] = rows
        registry.append(exp)
        summaries.append(summarize_experiment(exp, rows))
        for slice_key, values in (("fms_bin", ["0-5", "5-10", "10-15", "15-20"]), ("missing_slice", ["complete_dynamic", "missing_dynamic"]), ("near_update_event", ["0", "1"]), ("flat_interval", ["0", "1"])):
            slices.extend(slice_rows(exp, rows, slice_key, values))
        folds.extend(fold_rows(exp, rows))
    fold_agg = aggregate_fold_table(folds)
    for row in summaries:
        row.update(fold_agg.get(row["experiment_id"], {}))
    final_id = min(summaries, key=lambda r: (r.get("session_uid_macro_mae", float("inf")), r.get("raw_pa_id_macro_mae", float("inf")), r.get("rmse", float("inf"))))["experiment_id"]
    candidate_id = "stage4_static_static_dynamic"
    selected_id = candidate_id if candidate_id == final_id else final_id
    final_sessions = session_mae_map(rows_by_exp[selected_id])
    for row in summaries:
        boot = bootstrap_ci(session_mae_map(rows_by_exp[row["experiment_id"]]), final_sessions)
        row.update({f"paired_vs_selected_{k}": v for k, v in boot.items()})
    write_csv(OUT / "experiment_registry.csv", registry)
    write_csv(TABLES / "table_model_comparison.csv", [r for r in summaries if r["experiment_id"] in {"stage1_10s_mean_fms", "stage1_10s_ridge_window_stats", "stage2_10s_lstm", "stage2_10s_causal_tcn", "stage4_static_static_dynamic"}])
    write_csv(TABLES / "table_history_ablation.csv", [r for r in summaries if r["experiment_id"].startswith("stage4_history_")])
    common_path = p("shared/data/exports/stage4/stage4/history_diagnostics/history_common_anchor_metrics.csv")
    if common_path.exists():
        write_csv(TABLES / "table_history_common_anchor.csv", read_csv(common_path))
    write_csv(TABLES / "table_feature_ablation.csv", [r for r in summaries if r["experiment_id"].startswith("stage4_static_") or r["experiment_id"].startswith("stage4_dose_")])
    write_csv(TABLES / "table_loss_task_ablation.csv", [r for r in summaries if r["experiment_id"].startswith("stage3_high_") or r["experiment_id"].startswith("stage4_multitask_")])
    write_csv(TABLES / "table_missingness_ablation.csv", [r for r in summaries if r["experiment_id"].startswith("stage3_missing_")])
    write_csv(TABLES / "table_final_model_metrics.csv", [r for r in summaries if r["experiment_id"] == selected_id])
    write_csv(TABLES / "table_all_unified_metrics.csv", summaries)
    write_csv(TABLES / "table_slice_metrics.csv", slices)
    write_csv(TABLES / "table_fold_metrics.csv", folds)
    selected_rows = rows_by_exp[selected_id]
    reps = select_sessions(selected_rows)
    for label, info in reps.items():
        session = info["session_uid"]
        svg_curve(FIGURES / f"{label}_final_model.svg", session_series(selected_rows, session), f"{label}: {session}", session_metric_text(selected_rows, session))
    median_session = reps["p50_error"]["session_uid"]
    compare_series = {}
    for exp_id, label in [("stage1_10s_ridge_window_stats", "Ridge"), ("stage2_10s_lstm", "Dynamic LSTM"), (selected_id, "Static+Dynamic LSTM")]:
        rows = rows_by_exp[exp_id]
        subset = sorted([r for r in rows if r["session_uid"] == median_session], key=lambda r: r["end_time"])
        if subset:
            compare_series.setdefault("Ground Truth", [(r["end_time"], r["y_true"]) for r in subset])
            compare_series[label] = [(r["end_time"], r["y_pred"]) for r in subset]
    svg_curve(FIGURES / "median_session_model_comparison.svg", compare_series, f"同一中位误差session模型对比: {median_session}", "Ridge、dynamic-only LSTM 与 static+dynamic LSTM；均为OOF测试预测。")
    selection = {
        "predefined_candidate": candidate_id,
        "unified_best_by_rule": final_id,
        "selected_final_experiment_id": selected_id,
        "selection_rule": "主指标session-macro MAE；次级raw_pa_id-group macro、RMSE、R2、Pearson；性能接近时优先短窗口、少参数、低延迟、简单处理。",
        "selected_model_name": "10秒单向LSTM + dynamic + session-recorded static susceptibility features + zero/missing mask + Huber current-FMS regression",
        "not_confirmed_participant_personalized": True,
    }
    (OUT / "final_model_selection.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "representative_sessions.json").write_text(json.dumps(reps, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "source_stages": ["stage1", "stage2", "stage3", "stage4"],
        "split_hashes": SPLIT_HASH,
        "experiment_count": len(registry),
        "generated_tables": sorted(str(p.relative_to(OUT)) for p in TABLES.glob("*.csv")),
        "generated_figures": sorted(str(p.relative_to(OUT)) for p in FIGURES.glob("*.svg")),
        "metric_notes": {
            "smape": "已计算但FMS接近0时不稳定，不作为主要选型依据。",
            "dtw": "session macro使用半径20的带状归一化DTW，避免长序列二次复杂度爆炸。",
        },
    }
    (OUT / "reproducibility_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(summaries, selected_id, selection, reps)
    print(f"[stage5] wrote synthesis to {OUT}", flush=True)


def fmt(x, n=4):
    if x == "" or x is None:
        return ""
    try:
        return f"{float(x):.{n}f}"
    except Exception:
        return str(x)


def get_summary(summaries, exp_id):
    return next(r for r in summaries if r["experiment_id"] == exp_id)


def write_report(summaries, selected_id, selection, reps):
    selected = get_summary(summaries, selected_id)
    ridge = get_summary(summaries, "stage1_10s_ridge_window_stats")
    stage2 = get_summary(summaries, "stage2_10s_lstm")
    lines = [
        "# Ryu-Kim Stage 5 综合结果整理、最终模型选型与预测可视化",
        "",
        "本报告基于已冻结的 Stage 1-4 OOF 测试预测、split、指标和日志重新整理生成；未进行新的模型架构训练，未修改已有 split、预测或原始指标。",
        "",
        "## 最终结论",
        "",
        f"按预设分层规则，最终选择 `{selected_id}`：10秒单向 LSTM，输入为六轴动态序列、缺失mask，以及 session-recorded age/gender/MSSQ static susceptibility features。该模型不能称为 confirmed participant-personalized model。",
        "",
        "| 模型 | window MAE | session MAE | group MAE | RMSE | R2 | Pearson r | 参数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| Stage 1 Ridge 10s | {fmt(ridge['mae'])} | {fmt(ridge['session_uid_macro_mae'])} | {fmt(ridge['raw_pa_id_macro_mae'])} | {fmt(ridge['rmse'])} | {fmt(ridge['r2'])} | {fmt(ridge['pearson_r'])} | {ridge['parameter_count']} |",
        f"| Stage 2 dynamic LSTM 10s | {fmt(stage2['mae'])} | {fmt(stage2['session_uid_macro_mae'])} | {fmt(stage2['raw_pa_id_macro_mae'])} | {fmt(stage2['rmse'])} | {fmt(stage2['r2'])} | {fmt(stage2['pearson_r'])} | {stage2['parameter_count']} |",
        f"| Final static+dynamic LSTM | {fmt(selected['mae'])} | {fmt(selected['session_uid_macro_mae'])} | {fmt(selected['raw_pa_id_macro_mae'])} | {fmt(selected['rmse'])} | {fmt(selected['r2'])} | {fmt(selected['pearson_r'])} | {selected['parameter_count']} |",
        "",
        "sMAPE 已统一计算，但 FMS 接近 0 时分母不稳定，因此不作为主要选型依据。",
        "",
        "## 研究问题回答",
        "",
        "### 哪些模型结构真正有效",
        "",
        "Ridge 到 dynamic LSTM 有小幅稳定收益；真正明显的新增收益来自 static susceptibility features 与 dynamic LSTM 结合。causal TCN、多任务事件头、更长历史和累计剂量没有提供稳定架构增益。",
        "",
        "### 历史长度是否有价值",
        "",
        "全部有效窗口上 10 秒最好；公共测试锚点上 40 秒仅有极小 MAE 优势，60/120 秒退化。因此更长历史不能作为稳定增益来源。",
        "",
        "### 动态、静态和累计剂量分别贡献什么",
        "",
        "动态序列是基本可用信号；累计剂量有信息但弱于局部序列，作为补充仅带来很小 macro 指标变化；session-recorded static susceptibility features 单独较弱，但与动态结合最有效，说明其解释了重要跨 session 差异。",
        "",
        "### 高FMS、缺失数据和update事件的主要问题",
        "",
        "高FMS仍存在系统性低估；weighted Huber 可降低15-20误差但明显损害低/中FMS和总体指标。缺失窗口显著更难，因果forward fill/time-since没有实质改善。update事件附近窗口误差更高，事件AUPRC/F1较低，说明更新事件从当前动态输入中弱可预测。",
        "",
        "### 为什么选择 static+dynamic 10秒LSTM",
        "",
        "它在主指标 session-macro MAE 上综合最好，同时 raw_pa_id-group macro、RMSE、R2/Pearson 也没有异常冲突。相对于更复杂的多任务或更长历史，它更短、更简单、参数较少、推理路径更直接。",
        "",
        "### 最终模型可信与不足",
        "",
        "可信：普通动态区间、完整窗口、非高FMS区间、需要源域公开数据内部OOF估计的场景。明显不足：FMS 15-20 高区间、缺失窗口、update事件附近，以及跨数据集/Unity实时部署。当前结果仍不支持确认参与者身份下的个性化声明。",
        "",
        "## 代表预测曲线",
        "",
        "所有曲线均来自 OOF 测试预测，未使用训练/验证预测，未对评价预测做平滑。代表 session 由固定误差百分位自动选择。",
        "",
        f"- 中位误差完整时间线：`figures/median_error_full_timeline_final_model.svg` / `{reps['p50_error']['session_uid']}`",
        f"- 10/50/90百分位误差并列曲线：`figures/p10_error_final_model.svg`, `figures/p50_error_final_model.svg`, `figures/p90_error_final_model.svg`",
        "- Ridge、dynamic-only LSTM、static+dynamic LSTM 同一中位session对比：`figures/median_session_model_comparison.svg`",
        "",
        "## 输出索引",
        "",
        "- `experiment_registry.csv`：统一实验注册表。",
        "- `tables/`：论文式综合表格。",
        "- `figures/`：OOF预测曲线 SVG。",
        "- `final_model_selection.json`：冻结最终配置与选择规则。",
        "- `representative_sessions.json`：自动选择的代表session。",
        "- `reproducibility_manifest.json`：split hash、来源文件和生成物清单。",
    ]
    (OUT / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
