import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shared/data/exports/stage5_result_synthesis"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def mean(values):
    return sum(values) / len(values) if values else ""


def add_resource(resources, exp_id, rows):
    if not rows:
        return

    def avg(column):
        vals = [float(row[column]) for row in rows if row.get(column) not in ("", None)]
        return mean(vals)

    resources[exp_id] = {
        "train_time_seconds_mean": avg("train_time_seconds"),
        "inference_latency_ms_per_window_mean": avg("inference_latency_ms_per_window"),
        "peak_gpu_memory_mb_mean": avg("peak_gpu_memory_mb"),
        "parameter_count_resource": rows[0].get("parameter_count", ""),
    }


def build_resources():
    resources = {}
    stage1 = read_csv(ROOT / "shared/data/exports/stage1/reports/ryu_kim_dynamic_baseline/metrics_by_fold.csv")
    for duration in ("10.0", "30.0", "60.0"):
        d = int(float(duration))
        for model in ("mean_fms", "ridge_window_stats", "causal_tcn_linear"):
            add_resource(
                resources,
                f"stage1_{d}s_{model}",
                [r for r in stage1 if r.get("duration_seconds") == duration and r.get("model") == model and not r.get("metric_slice")],
            )
    stage2 = read_csv(ROOT / "shared/data/exports/stage2/reports/ryu_kim_sequence_models_10s/metrics_by_fold.csv")
    for model in ("lstm", "causal_tcn"):
        add_resource(resources, f"stage2_10s_{model}", [r for r in stage2 if r.get("model") == model])
    high = read_csv(ROOT / "shared/data/exports/stage3/high_fms_experiments/metrics_by_fold.csv")
    for variant in ("standard_huber_lstm", "weighted_huber_lstm", "multitask_high_fms_lstm"):
        add_resource(resources, f"stage3_high_{variant}", [r for r in high if r.get("variant") == variant or r.get("model") == variant])
    miss = read_csv(ROOT / "shared/data/exports/stage3/missingness_experiments/metrics_by_fold.csv")
    for variant in ("zero_mask_lstm", "ffill_mask_lstm", "ffill_mask_time_lstm"):
        add_resource(resources, f"stage3_missing_{variant}", [r for r in miss if r.get("variant") == variant or r.get("model") == variant])
    static = read_csv(ROOT / "shared/data/exports/stage4/stage4/static_diagnostics/metrics_by_fold.csv")
    for variant in ("static_only", "dynamic", "cumulative_dose", "static_dose", "static_dynamic", "static_dynamic_dose"):
        add_resource(resources, f"stage4_static_{variant}", [r for r in static if r.get("variant") == variant])
    dose = read_csv(ROOT / "shared/data/exports/stage4/stage4/dose_diagnostics/metrics_by_fold.csv")
    for variant in ("local_sequence", "cumulative_dose", "window_stats", "sequence_plus_dose"):
        add_resource(resources, f"stage4_dose_{variant}", [r for r in dose if r.get("variant") == variant])
    multitask = read_csv(ROOT / "shared/data/exports/stage4/stage4/multitask_diagnostics/metrics_by_fold.csv")
    for variant in ("dynamic", "multitask"):
        add_resource(resources, f"stage4_multitask_{variant}", [r for r in multitask if r.get("variant") == variant])
    return resources


def main():
    protocol = [
        {"item": "public_snapshot_session_count", "value": "428", "note": "Stage 1-4 all use frozen public snapshot"},
        {"item": "raw_pa_id_groups", "value": "86", "note": "Conservative identifier grouping; not confirmed participants"},
        {"item": "split_name", "value": "raw_pa_id-group-disjoint split", "note": "Do not call confirmed participant-disjoint"},
        {"item": "split_10s_sha256", "value": "ce6de3c1cc9beb6c94acee6227213a50b43ecb338ab1fc6f48a3942adfa91cd5", "note": "Frozen Baseline v1 split"},
        {"item": "split_30s_sha256", "value": "e8db5f68f0f21d9ac01c53391383ef44dec0cabbbdc28e5fcbfe23e4e120cd73", "note": "Frozen Baseline v1 split"},
        {"item": "split_60s_sha256", "value": "a0b3eeab3f779bc6e2996b66278052c7771cdd07acf9096085ea383578421005", "note": "Frozen Baseline v1 split"},
        {"item": "primary_target", "value": "current terminal FMS", "note": "Future FMS deltas are supervision-only targets in Stage 4"},
        {"item": "primary_selection_metric", "value": "session-macro MAE", "note": "Secondary: raw_pa_id-group macro, RMSE, R2, Pearson, bias/slices"},
        {"item": "forbidden_inputs", "value": "FMS history, raw_pa_id, session ID, condition, filename, future frames", "note": "Static susceptibility features allowed only in Stage 4/5 final candidate"},
        {"item": "missing_threshold", "value": "exclude dynamic missing fraction > 20% windows", "note": "Missing values handled causally"},
        {"item": "smape_note", "value": "computed but not primary", "note": "sMAPE unstable when FMS is near 0"},
    ]
    write_csv(TABLES / "table_dataset_protocol.csv", protocol)

    resources = build_resources()
    all_rows = read_csv(TABLES / "table_all_unified_metrics.csv")
    for row in all_rows:
        row.update(resources.get(row["experiment_id"], {}))
    write_csv(TABLES / "table_all_unified_metrics.csv", all_rows)
    subsets = {
        "table_model_comparison.csv": {"stage1_10s_mean_fms", "stage1_10s_ridge_window_stats", "stage2_10s_lstm", "stage2_10s_causal_tcn", "stage4_static_static_dynamic"},
        "table_history_ablation.csv": {r["experiment_id"] for r in all_rows if r["experiment_id"].startswith("stage4_history_")},
        "table_feature_ablation.csv": {r["experiment_id"] for r in all_rows if r["experiment_id"].startswith("stage4_static_") or r["experiment_id"].startswith("stage4_dose_")},
        "table_loss_task_ablation.csv": {r["experiment_id"] for r in all_rows if r["experiment_id"].startswith("stage3_high_") or r["experiment_id"].startswith("stage4_multitask_")},
        "table_missingness_ablation.csv": {r["experiment_id"] for r in all_rows if r["experiment_id"].startswith("stage3_missing_")},
        "table_final_model_metrics.csv": {"stage4_static_static_dynamic"},
    }
    for filename, ids in subsets.items():
        write_csv(TABLES / filename, [r for r in all_rows if r["experiment_id"] in ids])
    write_csv(TABLES / "table_resource_metrics.csv", [{"experiment_id": k, **v} for k, v in sorted(resources.items())])

    reps = json.loads((OUT / "representative_sessions.json").read_text(encoding="utf-8"))
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" viewBox="0 0 1200 260">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="30" y="30" font-size="20" font-family="Arial">第10、50、90百分位误差 session 的OOF预测曲线索引</text>',
    ]
    for index, key in enumerate(["p10_error", "p50_error", "p90_error"]):
        x = 30 + index * 390
        info = reps[key]
        svg.extend(
            [
                f'<rect x="{x}" y="55" width="360" height="160" fill="#f8f8f8" stroke="#333"/>',
                f'<text x="{x + 15}" y="85" font-size="16" font-family="Arial">{key}</text>',
                f'<text x="{x + 15}" y="115" font-size="12" font-family="Arial">session: {info["session_uid"]}</text>',
                f'<text x="{x + 15}" y="140" font-size="12" font-family="Arial">MAE={info["mae"]:.3f}; RMSE={info["rmse"]:.3f}; bias={info["bias"]:.3f}</text>',
                f'<text x="{x + 15}" y="165" font-size="12" font-family="Arial">完整曲线: figures/{key}_final_model.svg</text>',
                f'<text x="{x + 15}" y="190" font-size="12" font-family="Arial">纵轴固定0-20，橙线为FMS update事件。</text>',
            ]
        )
    svg.append("</svg>")
    (FIGURES / "p10_p50_p90_error_sessions.svg").write_text("\n".join(svg), encoding="utf-8")

    manifest = json.loads((OUT / "reproducibility_manifest.json").read_text(encoding="utf-8"))
    manifest["generated_tables"] = sorted(str(p.relative_to(OUT)) for p in TABLES.glob("*.csv"))
    manifest["generated_figures"] = sorted(str(p.relative_to(OUT)) for p in FIGURES.glob("*.svg"))
    manifest["resource_metric_note"] = "Stage 4 training scripts did not record peak GPU memory; those cells are intentionally blank."
    (OUT / "reproducibility_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    report = OUT / "final_report.md"
    text = report.read_text(encoding="utf-8")
    if "table_dataset_protocol.csv" not in text:
        text += "\n## 补充说明\n\n- 已补充 `tables/table_dataset_protocol.csv`。\n- 已补充 `tables/table_resource_metrics.csv`；Stage 4 未记录峰值显存，因此相应单元格留空。\n- 已补充三百分位误差 session 的并列索引图：`figures/p10_p50_p90_error_sessions.svg`。\n"
    report.write_text(text, encoding="utf-8")
    print("postprocess complete")


if __name__ == "__main__":
    main()
