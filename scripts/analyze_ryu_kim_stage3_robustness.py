import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple


def _bootstrap_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "python" / "src"))
    return repo_root


REPO_ROOT = _bootstrap_path()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def stdev(values: Sequence[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def wilcoxon_signed_rank(diffs: Sequence[float]) -> Dict[str, float]:
    nonzero = [d for d in diffs if abs(d) > 1e-12]
    n = len(nonzero)
    if n == 0:
        return {"n": 0, "w_plus": 0.0, "w_minus": 0.0, "z": 0.0, "p_two_sided": 1.0}
    ranked = sorted((abs(d), d) for d in nonzero)
    ranks = []
    i = 0
    while i < n:
        j = i + 1
        while j < n and abs(ranked[j][0] - ranked[i][0]) <= 1e-12:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks.append((avg_rank, ranked[k][1]))
        i = j
    w_plus = sum(rank for rank, diff in ranks if diff > 0)
    w_minus = sum(rank for rank, diff in ranks if diff < 0)
    expected = n * (n + 1) / 4.0
    variance = n * (n + 1) * (2 * n + 1) / 24.0
    z = (w_plus - expected) / math.sqrt(variance) if variance else 0.0
    p = 2.0 * min(normal_cdf(z), 1.0 - normal_cdf(z))
    return {"n": n, "w_plus": w_plus, "w_minus": w_minus, "z": z, "p_two_sided": max(0.0, min(1.0, p))}


def bootstrap_ci(values: Sequence[float], seed: int, iterations: int) -> Tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = []
    n = len(values)
    for _ in range(iterations):
        means.append(mean([values[rng.randrange(n)] for _ in range(n)]))
    return percentile(means, 0.025), percentile(means, 0.975)


def paired_effect_size(diffs: Sequence[float]) -> float:
    sd = stdev(diffs)
    return mean(diffs) / sd if sd and math.isfinite(sd) else float("nan")


def load_predictions(seq_path: Path, ridge_path: Path) -> List[Dict[str, object]]:
    rows = []
    ridge_lookup = {}
    for row in read_csv(ridge_path):
        if row.get("model") == "ridge_window_stats" and row.get("duration_seconds") in ("10.0", "10"):
            ridge_lookup[(row["fold"], row["session_uid"], row["source_row_end"])] = row
    for row in read_csv(seq_path):
        rows.append(row)
    for row in ridge_lookup.values():
        ridge_row = dict(row)
        ridge_row["model"] = "ridge"
        rows.append(ridge_row)
    return rows


def grouped_mae(rows: Sequence[Mapping[str, object]], model: str, group_key: str, filter_key: str, filter_value: str) -> Dict[str, float]:
    grouped: Dict[str, List[float]] = defaultdict(list)
    for row in rows:
        if row["model"] != model:
            continue
        if filter_key and row[filter_key] != filter_value:
            continue
        grouped[str(row[group_key])].append(abs(float(row["y_pred"]) - float(row["y_true"])))
    return {key: mean(values) for key, values in grouped.items()}


def paired_summary(
    rows: Sequence[Mapping[str, object]],
    model_a: str,
    model_b: str,
    filter_key: str,
    filter_value: str,
    seed: int,
    bootstrap_iterations: int,
) -> Dict[str, object]:
    a = grouped_mae(rows, model_a, "session_uid", filter_key, filter_value)
    b = grouped_mae(rows, model_b, "session_uid", filter_key, filter_value)
    common = sorted(set(a).intersection(b))
    # Negative diff means model_a has lower MAE than model_b.
    diffs = [a[key] - b[key] for key in common]
    ci_low, ci_high = bootstrap_ci(diffs, seed, bootstrap_iterations)
    wilcoxon = wilcoxon_signed_rank(diffs)
    return {
        "comparison": f"{model_a}_minus_{model_b}",
        "scope": filter_value if filter_key else "overall",
        "paired_session_count": len(common),
        "mean_mae_diff": mean(diffs),
        "median_mae_diff": percentile(diffs, 0.5),
        "improved_session_fraction": sum(1 for d in diffs if d < 0) / len(diffs) if diffs else float("nan"),
        "bootstrap_95ci_low": ci_low,
        "bootstrap_95ci_high": ci_high,
        "wilcoxon_n": wilcoxon["n"],
        "wilcoxon_w_plus": wilcoxon["w_plus"],
        "wilcoxon_w_minus": wilcoxon["w_minus"],
        "wilcoxon_z_normal_approx": wilcoxon["z"],
        "wilcoxon_p_two_sided_normal_approx": wilcoxon["p_two_sided"],
        "paired_effect_size_dz": paired_effect_size(diffs),
    }


def session_diff_rows(
    rows: Sequence[Mapping[str, object]],
    model_a: str,
    model_b: str,
    filter_key: str,
    filter_value: str,
) -> List[Dict[str, object]]:
    a = grouped_mae(rows, model_a, "session_uid", filter_key, filter_value)
    b = grouped_mae(rows, model_b, "session_uid", filter_key, filter_value)
    output = []
    for session_uid in sorted(set(a).intersection(b)):
        output.append(
            {
                "comparison": f"{model_a}_minus_{model_b}",
                "scope": filter_value if filter_key else "overall",
                "session_uid": session_uid,
                "mae_a": a[session_uid],
                "mae_b": b[session_uid],
                "mae_diff": a[session_uid] - b[session_uid],
                "improved": a[session_uid] < b[session_uid],
            }
        )
    return output


def fold_diffs(
    rows: Sequence[Mapping[str, object]],
    model_a: str,
    model_b: str,
    filter_key: str = "",
    filter_value: str = "",
) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for row in rows:
        if filter_key and row[filter_key] != filter_value:
            continue
        grouped[(row["model"], row["fold"])].append(abs(float(row["y_pred"]) - float(row["y_true"])))
    output = []
    for fold in sorted({row["fold"] for row in rows}, key=int):
        if (model_a, fold) in grouped and (model_b, fold) in grouped:
            output.append(
                {
                    "comparison": f"{model_a}_minus_{model_b}",
                    "scope": filter_value if filter_key else "overall",
                    "fold": fold,
                    "mae_diff": mean(grouped[(model_a, fold)]) - mean(grouped[(model_b, fold)]),
                }
            )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 3 paired robustness analysis from frozen predictions.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default="shared/data/exports/stage3/robustness_analysis")
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    repo = Path(args.repo_root)
    out = repo / args.output_dir
    rows = load_predictions(
        repo / "shared/data/exports/stage2/predictions/ryu_kim_sequence_models_10s/predictions_10s_sequence_models.csv",
        repo / "shared/data/exports/stage1/predictions/ryu_kim_dynamic_baseline/predictions_10s.csv",
    )
    scopes = [("", ""), ("fms_bin", "0-5"), ("fms_bin", "5-10"), ("fms_bin", "10-15"), ("fms_bin", "15-20"), ("missing_slice", "complete_dynamic"), ("missing_slice", "missing_dynamic")]
    comparisons = [("lstm", "ridge"), ("causal_tcn", "ridge"), ("lstm", "causal_tcn")]
    summaries = []
    session_rows = []
    for model_a, model_b in comparisons:
        for filter_key, filter_value in scopes:
            summaries.append(paired_summary(rows, model_a, model_b, filter_key, filter_value, args.seed, args.bootstrap_iterations))
            session_rows.extend(session_diff_rows(rows, model_a, model_b, filter_key, filter_value))
    fold_rows = []
    for model_a, model_b in comparisons:
        for filter_key, filter_value in scopes:
            fold_rows.extend(fold_diffs(rows, model_a, model_b, filter_key, filter_value))
    write_csv(
        out / "paired_session_robustness.csv",
        summaries,
        [
            "comparison",
            "scope",
            "paired_session_count",
            "mean_mae_diff",
            "median_mae_diff",
            "improved_session_fraction",
            "bootstrap_95ci_low",
            "bootstrap_95ci_high",
            "wilcoxon_n",
            "wilcoxon_w_plus",
            "wilcoxon_w_minus",
            "wilcoxon_z_normal_approx",
            "wilcoxon_p_two_sided_normal_approx",
            "paired_effect_size_dz",
        ],
    )
    write_csv(
        out / "paired_session_mae_differences.csv",
        session_rows,
        ["comparison", "scope", "session_uid", "mae_a", "mae_b", "mae_diff", "improved"],
    )
    write_csv(out / "paired_fold_mae_differences.csv", fold_rows, ["comparison", "scope", "fold", "mae_diff"])
    overall = [row for row in summaries if row["scope"] == "overall"]
    readme = [
        "# Stage 3 Robustness Analysis",
        "",
        "This analysis uses frozen Stage 2 sequence predictions and Baseline v1 Ridge predictions only.",
        "Negative MAE differences mean the first model has lower paired session MAE.",
        "",
        "| comparison | mean session MAE diff | bootstrap 95% CI | improved session fraction | Wilcoxon p | effect dz |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in overall:
        readme.append(
            f"| {row['comparison']} | {row['mean_mae_diff']:.4f} | "
            f"[{row['bootstrap_95ci_low']:.4f}, {row['bootstrap_95ci_high']:.4f}] | "
            f"{row['improved_session_fraction']:.3f} | {row['wilcoxon_p_two_sided_normal_approx']:.4g} | "
            f"{row['paired_effect_size_dz']:.4f} |"
        )
    readme.extend(
        [
            "",
            "Interpretation separates three claims: average metric movement, the pre-set 3% practical threshold, and paired statistical robustness.",
        ]
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    with (out / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump({"overall": overall, "bootstrap_iterations": args.bootstrap_iterations}, handle, indent=2)
        handle.write("\n")
    print(f"wrote robustness analysis to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
