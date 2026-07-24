import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence


def _bootstrap_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "python" / "src"))
    return repo_root


REPO_ROOT = _bootstrap_path()

from openrdw_ai.ryu_kim_fms.dynamic_baseline import load_raw_sessions, mean, stdev, write_csv, write_json  # noqa: E402
from openrdw_ai.ryu_kim_fms.schema import DatasetConfig  # noqa: E402
from scripts.train_ryu_kim_sequence_models import load_split_assignments  # noqa: E402


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


def summarize(values: Sequence[float]) -> Dict[str, float]:
    return {
        "count": len(values),
        "mean": mean(values),
        "std": stdev(values),
        "p25": percentile(values, 0.25),
        "median": percentile(values, 0.50),
        "p75": percentile(values, 0.75),
        "max": max(values) if values else float("nan"),
    }


def nearest_future_index(rows: Sequence[Mapping[str, object]], start_index: int, seconds: float) -> int:
    target = float(rows[start_index]["timestamp"]) + seconds
    best = None
    best_gap = float("inf")
    for idx in range(start_index + 1, len(rows)):
        gap = abs(float(rows[idx]["timestamp"]) - target)
        if gap < best_gap:
            best = idx
            best_gap = gap
        if float(rows[idx]["timestamp"]) >= target and gap > best_gap:
            break
    return best if best is not None else -1


def session_events(session: Mapping[str, object], fold_assignments: Mapping[str, int]) -> Dict[str, object]:
    rows = [r for r in session["rows"] if r.get("timestamp") is not None and r.get("fms") is not None]
    rows = sorted(rows, key=lambda r: (float(r["timestamp"]), int(r.get("row_index", 0))))
    raw_pa_id = str(session["raw_pa_id"])
    fold = fold_assignments.get(raw_pa_id, "")
    events = []
    plateau_lengths = []
    last_event_time = float(rows[0]["timestamp"]) if rows else 0.0
    for i in range(1, len(rows)):
        prev = float(rows[i - 1]["fms"])
        curr = float(rows[i]["fms"])
        delta = curr - prev
        if abs(delta) <= 1e-12:
            continue
        now = float(rows[i]["timestamp"])
        plateau = now - last_event_time
        last_event_time = now
        plateau_lengths.append(plateau)
        idx5 = nearest_future_index(rows, i, 5.0)
        idx10 = nearest_future_index(rows, i, 10.0)
        events.append(
            {
                "raw_pa_id": raw_pa_id,
                "session_uid": session["session_uid"],
                "fold": fold,
                "timestamp": now,
                "source_row_end": rows[i].get("row_index", i),
                "fms_before": prev,
                "fms_after": curr,
                "update_direction": "up" if delta > 0 else "down",
                "update_magnitude": delta,
                "abs_update_magnitude": abs(delta),
                "is_high_fms_event": curr >= 15.0 or prev >= 15.0,
                "stair_duration_seconds": plateau,
                "future_5s_delta_fms": float(rows[idx5]["fms"]) - curr if idx5 >= 0 else "",
                "future_10s_delta_fms": float(rows[idx10]["fms"]) - curr if idx10 >= 0 else "",
            }
        )
    return {"events": events, "plateau_lengths": plateau_lengths, "row_count": len(rows)}


def aggregate(events: Sequence[Mapping[str, object]], key: str) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for event in events:
        grouped[str(event[key])].append(event)
    rows = []
    for group, items in sorted(grouped.items()):
        magnitudes = [float(e["abs_update_magnitude"]) for e in items]
        plateaus = [float(e["stair_duration_seconds"]) for e in items]
        rows.append(
            {
                key: group,
                "event_count": len(items),
                "up_count": sum(1 for e in items if e["update_direction"] == "up"),
                "down_count": sum(1 for e in items if e["update_direction"] == "down"),
                "high_fms_event_count": sum(1 for e in items if e["is_high_fms_event"]),
                "abs_update_magnitude_mean": mean(magnitudes),
                "abs_update_magnitude_p95": percentile(magnitudes, 0.95),
                "stair_duration_mean_seconds": mean(plateaus),
                "stair_duration_median_seconds": percentile(plateaus, 0.50),
                "stair_duration_p95_seconds": percentile(plateaus, 0.95),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Ryu-Kim Stage 4 FMS label/update diagnostics.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--split-json", default="reports/ryu_kim_dynamic_baseline/baseline_v1_review/frozen_splits/splits_10s.json")
    parser.add_argument("--output-dir", default="shared/data/exports/stage4/fms_label_diagnostics")
    args = parser.parse_args()
    repo = Path(args.repo_root)
    output_dir = repo / args.output_dir
    config = DatasetConfig(repo_root=repo)
    folds = load_split_assignments(repo / args.split_json)
    sessions = load_raw_sessions(config)
    all_events = []
    all_plateaus = []
    session_rows = []
    for session in sessions:
        result = session_events(session, folds)
        all_events.extend(result["events"])
        all_plateaus.extend(result["plateau_lengths"])
        session_rows.append(
            {
                "raw_pa_id": session["raw_pa_id"],
                "session_uid": session["session_uid"],
                "fold": folds.get(str(session["raw_pa_id"]), ""),
                "row_count": result["row_count"],
                "event_count": len(result["events"]),
                "up_count": sum(1 for e in result["events"] if e["update_direction"] == "up"),
                "down_count": sum(1 for e in result["events"] if e["update_direction"] == "down"),
                "high_fms_event_count": sum(1 for e in result["events"] if e["is_high_fms_event"]),
                "stair_duration_median_seconds": percentile(result["plateau_lengths"], 0.5),
                "stair_duration_p95_seconds": percentile(result["plateau_lengths"], 0.95),
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(all_events, output_dir / "fms_update_events.csv")
    write_csv(session_rows, output_dir / "fms_update_by_session.csv")
    write_csv(aggregate(all_events, "raw_pa_id"), output_dir / "fms_update_by_raw_pa_id.csv")
    write_csv(aggregate(all_events, "fold"), output_dir / "fms_update_by_fold.csv")
    summary = {
        "session_count": len(sessions),
        "event_count": len(all_events),
        "up_count": sum(1 for e in all_events if e["update_direction"] == "up"),
        "down_count": sum(1 for e in all_events if e["update_direction"] == "down"),
        "high_fms_event_count": sum(1 for e in all_events if e["is_high_fms_event"]),
        "stair_duration_seconds": summarize(all_plateaus),
        "update_abs_magnitude": summarize([float(e["abs_update_magnitude"]) for e in all_events]),
    }
    write_json(summary, output_dir / "summary.json")
    readme = [
        "# Stage 4 FMS Label Diagnostics",
        "",
        "Future 5s/10s FMS deltas are diagnostic/supervision targets only and must not be used as model inputs.",
        "",
        f"- Sessions: {summary['session_count']}",
        f"- FMS update events: {summary['event_count']}",
        f"- Up / down updates: {summary['up_count']} / {summary['down_count']}",
        f"- High-FMS events: {summary['high_fms_event_count']}",
        f"- Median stair duration: {summary['stair_duration_seconds']['median']:.3f}s",
        f"- 95th percentile stair duration: {summary['stair_duration_seconds']['p75']:.3f}s p75, {summary['stair_duration_seconds']['max']:.3f}s max",
        "",
        "Generated files: `fms_update_events.csv`, `fms_update_by_session.csv`, `fms_update_by_raw_pa_id.csv`, `fms_update_by_fold.csv`, `summary.json`.",
    ]
    (output_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(f"wrote FMS label diagnostics to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
