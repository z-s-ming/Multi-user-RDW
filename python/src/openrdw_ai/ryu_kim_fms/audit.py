import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .io import discover_csv_files, parse_filename_metadata, read_rows
from .schema import CANONICAL_COLUMNS, DYNAMIC_FEATURES, DatasetConfig


def _summary(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"count": 0}
    sorted_values = sorted(values)
    n = len(sorted_values)
    return {
        "count": n,
        "min": sorted_values[0],
        "p25": sorted_values[int((n - 1) * 0.25)],
        "median": statistics.median(sorted_values),
        "p75": sorted_values[int((n - 1) * 0.75)],
        "max": sorted_values[-1],
        "mean": statistics.fmean(sorted_values),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_dataset(config: DatasetConfig) -> Dict[str, object]:
    raw_dir = config.raw_dir_abs
    files = discover_csv_files(raw_dir)
    field_mapping = config.field_mapping
    audit: Dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_data_dir": str(raw_dir),
        "readme_path": str(config.resolve(config.readme_path)),
        "file_count": len(files),
        "field_mapping": {
            "columns": list(field_mapping.canonical_columns),
            "units": field_mapping.units,
            "source_note": field_mapping.source_note,
        },
        "ambiguities": [
            "Acceleration unit is not stated in the local dataset readme.",
            "Angular velocity unit is not stated in the local dataset readme.",
            "FMS legal range is not stated in the local dataset readme.",
            "Session ID is derived from each filename stem; no separate authoritative session column exists.",
            "Condition ID is parsed heuristically from filenames by removing PA id and trailing clock time where present.",
            "Static feature linkage is inferred from repeated per-row gender/MSSQ/age values; no separate participant table exists.",
        ],
        "blocked_for_formal_preprocessing": True,
    }

    participant_files: Dict[str, List[str]] = defaultdict(list)
    condition_counts: Counter = Counter()
    file_summaries: List[Dict[str, object]] = []
    missing_counts: Counter = Counter()
    invalid_column_counts: Counter = Counter()
    fms_counter: Counter = Counter()
    gender_counter: Counter = Counter()
    age_values: List[float] = []
    mssq_values: List[float] = []
    sequence_lengths: List[int] = []
    durations: List[float] = []
    intervals: List[float] = []
    duplicate_row_count_total = 0
    duplicate_timestamp_count_total = 0
    large_gap_count_total = 0
    non_monotonic_files: List[str] = []
    static_conflicts: Dict[str, List[str]] = defaultdict(list)
    participant_static_values: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))

    for path in files:
        meta = parse_filename_metadata(path)
        participant_id = meta["participant_id"]
        condition_id = meta["condition_id"]
        participant_files[participant_id].append(path.name)
        condition_counts[condition_id] += 1
        rows = list(read_rows(path))
        sequence_lengths.append(len(rows))
        timestamps = [r["timestamp"] for r in rows if isinstance(r["timestamp"], float)]
        fms_values = [r["fms"] for r in rows if isinstance(r["fms"], float)]
        row_tuples = []
        timestamp_counter: Counter = Counter()
        previous_t = None
        file_intervals: List[float] = []
        non_monotonic = False
        large_gaps = 0

        for row in rows:
            row_tuple = tuple(row.get(c) for c in CANONICAL_COLUMNS)
            row_tuples.append(row_tuple)
            if not isinstance(row["timestamp"], float):
                missing_counts["timestamp"] += 1
            else:
                timestamp_counter[row["timestamp"]] += 1
                if previous_t is not None:
                    dt = row["timestamp"] - previous_t
                    file_intervals.append(dt)
                    intervals.append(dt)
                    if dt <= 0:
                        non_monotonic = True
                    if dt > config.maximum_allowed_gap_seconds:
                        large_gaps += 1
                previous_t = row["timestamp"]

            for col in CANONICAL_COLUMNS:
                if row.get(col) is None or row.get(col) == "":
                    missing_counts[col] += 1
            for col in DYNAMIC_FEATURES + ("fms", "age", "mssq"):
                value = row.get(col)
                if isinstance(value, float) and not math.isfinite(value):
                    invalid_column_counts[col] += 1

            if isinstance(row.get("fms"), float):
                fms_counter[str(row["fms"])] += 1
            if row.get("gender"):
                gender_counter[str(row["gender"])] += 1
            if isinstance(row.get("age"), float):
                age_values.append(float(row["age"]))
                participant_static_values[participant_id]["age"].add(float(row["age"]))
            if isinstance(row.get("mssq"), float):
                mssq_values.append(float(row["mssq"]))
                participant_static_values[participant_id]["mssq"].add(float(row["mssq"]))
            if row.get("gender"):
                participant_static_values[participant_id]["gender"].add(str(row["gender"]))

        duplicate_rows = len(row_tuples) - len(set(row_tuples))
        duplicate_timestamps = sum(count - 1 for count in timestamp_counter.values() if count > 1)
        duplicate_row_count_total += duplicate_rows
        duplicate_timestamp_count_total += duplicate_timestamps
        large_gap_count_total += large_gaps
        if non_monotonic:
            non_monotonic_files.append(path.name)
        if timestamps:
            durations.append(max(timestamps) - min(timestamps))

        file_summaries.append(
            {
                "filename": path.name,
                "sha256": _sha256(path),
                "participant_id": participant_id,
                "session_id": meta["session_id"],
                "condition_id": condition_id,
                "rows": len(rows),
                "duration_seconds": (max(timestamps) - min(timestamps)) if timestamps else None,
                "duplicate_rows": duplicate_rows,
                "duplicate_timestamps": duplicate_timestamps,
                "large_gaps": large_gaps,
                "non_monotonic_timestamps": non_monotonic,
                "sampling_interval_seconds": _summary(file_intervals),
                "fms_min": min(fms_values) if fms_values else None,
                "fms_max": max(fms_values) if fms_values else None,
            }
        )

    for participant_id, values_by_field in participant_static_values.items():
        for field, values in values_by_field.items():
            if len(values) > 1:
                static_conflicts[participant_id].append(f"{field}: {sorted(values)}")

    audit.update(
        {
            "participant_count": len([p for p in participant_files if p]),
            "session_count": len(files),
            "condition_count": len(condition_counts),
            "participants": sorted(participant_files),
            "conditions": dict(sorted(condition_counts.items())),
            "total_rows": sum(sequence_lengths),
            "sequence_length_distribution": _summary(sequence_lengths),
            "session_duration_seconds_distribution": _summary(durations),
            "sampling_interval_seconds_distribution": _summary(intervals),
            "missing_value_count_by_column": dict(missing_counts),
            "invalid_value_count_by_column": dict(invalid_column_counts),
            "duplicate_rows": duplicate_row_count_total,
            "duplicate_timestamps": duplicate_timestamp_count_total,
            "large_gap_count": large_gap_count_total,
            "non_monotonic_timestamp_files": non_monotonic_files,
            "fms_distribution": dict(sorted(fms_counter.items(), key=lambda kv: float(kv[0]))),
            "fms_observed_min": min((float(k) for k in fms_counter), default=None),
            "fms_observed_max": max((float(k) for k in fms_counter), default=None),
            "gender_distribution": dict(gender_counter),
            "age_distribution": _summary(age_values),
            "mssq_distribution": _summary(mssq_values),
            "static_feature_conflicts_by_participant": dict(static_conflicts),
            "files": file_summaries,
        }
    )
    return audit


def write_json(audit: Dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_markdown_report(audit: Dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ambiguities = audit.get("ambiguities", [])
    field_mapping = audit["field_mapping"]
    lines = [
        "# Ryu-Kim FMS Data Audit",
        "",
        "This report is generated by `python/scripts/audit_ryu_kim_fms.py`.",
        "No raw dataset files are modified.",
        "",
        "## Gate Status",
        "",
        "**Blocked for formal preprocessing/training:** yes.",
        "",
        "Blocking ambiguities:",
    ]
    lines.extend(f"- {item}" for item in ambiguities)
    lines.extend(
        [
            "",
            "## Field Mapping",
            "",
            "| Canonical field | Raw position | Unit/status | Role |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for index, name in enumerate(field_mapping["columns"], start=1):
        role = "target" if name == "fms" else "input" if name not in ("timestamp",) else "time"
        if name in ("participant_id", "session_id"):
            role = "grouping"
        lines.append(f"| `{name}` | {index} | {field_mapping['units'].get(name, 'UNKNOWN')} | {role} |")
    lines.extend(
        [
            "",
            "FMS is retained only as the supervised target. It is not included in motion or static input tensors.",
            "",
            "## Dataset Inventory",
            "",
            f"- Raw directory: `{audit['raw_data_dir']}`",
            f"- CSV files/sessions: {audit['session_count']}",
            f"- Participants: {audit['participant_count']}",
            f"- Parsed conditions: {audit['condition_count']}",
            f"- Total rows: {audit['total_rows']}",
            "",
            "## Time Series",
            "",
            f"- Expected sampling interval: 0.5 seconds from local readme/config.",
            f"- Observed interval distribution: `{audit['sampling_interval_seconds_distribution']}`",
            f"- Sequence length distribution: `{audit['sequence_length_distribution']}`",
            f"- Session duration distribution: `{audit['session_duration_seconds_distribution']}`",
            f"- Large timestamp gaps: {audit['large_gap_count']}",
            f"- Files with non-monotonic timestamps: {len(audit['non_monotonic_timestamp_files'])}",
            "",
            "## Data Quality",
            "",
            f"- Missing values by column: `{audit['missing_value_count_by_column']}`",
            f"- Invalid numeric values by column: `{audit['invalid_value_count_by_column']}`",
            f"- Exact duplicate rows: {audit['duplicate_rows']}",
            f"- Duplicate timestamps within sessions: {audit['duplicate_timestamps']}",
            f"- Static feature conflicts by participant: `{audit['static_feature_conflicts_by_participant']}`",
            "",
            "## Labels And Static Features",
            "",
            f"- Observed FMS min/max: {audit['fms_observed_min']} / {audit['fms_observed_max']}",
            f"- FMS distribution: `{audit['fms_distribution']}`",
            f"- Gender distribution: `{audit['gender_distribution']}`",
            f"- Age distribution: `{audit['age_distribution']}`",
            f"- MSSQ distribution: `{audit['mssq_distribution']}`",
            "",
            "## Reproducibility Notes",
            "",
            "- Participant-disjoint split must run before window generation.",
            "- Windows are causal and use only frames with timestamp <= the terminal frame timestamp.",
            "- Standardizers and categorical encoders must be fitted on training participants only.",
            "- True historical FMS is prohibited from model input features.",
            "- Formal training remains blocked until the ambiguities above are resolved.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

