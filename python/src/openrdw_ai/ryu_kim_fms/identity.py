import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .io import discover_csv_files, parse_filename_metadata, read_rows
from .schema import CANONICAL_COLUMNS, DatasetConfig


STATIC_COLUMNS = ("gender", "mssq", "age")
DYNAMIC_SEQUENCE_COLUMNS = (
    "timestamp",
    "fms",
    "acceleration_x",
    "acceleration_y",
    "acceleration_z",
    "angular_velocity_x",
    "angular_velocity_y",
    "angular_velocity_z",
)
TIME_FMS_COLUMNS = ("timestamp", "fms")
USABLE_PREFIX_ROWS = 420

DUPLICATE_REPORT_FIELDS = (
    "duplicate_type",
    "evidence",
    "evidence_hash",
    "session_count",
    "session_uids",
    "source_files",
    "raw_pa_ids",
    "confirmed_duplicate",
    "split_leakage_risk",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_session_uid(source_file_sha256: str, filename: str) -> str:
    digest = hashlib.sha256(f"{source_file_sha256}|{filename}".encode("utf-8")).hexdigest()
    return f"session_{digest[:16]}"


def normalize_condition(condition_raw: str) -> str:
    text = condition_raw.lower()
    text = text.replace("rof", "reverse_optical_flow")
    text = text.replace("foward", "forward")
    text = text.replace("whiteline", "white_line")
    text = text.replace("__", "_")
    tokens = set(text.split("_"))
    if text.startswith("base"):
        return "base"
    if "noise" in text:
        return "noise"
    if "reverse_optical_flow" in text or "reverse_optical_flow" in text.replace("_", ""):
        if "backward" in text:
            return "reverse_optical_flow_backward"
        if "forward" in text:
            return "reverse_optical_flow_forward"
        if "high" in tokens:
            return "reverse_optical_flow_high_density"
        if "low" in tokens:
            return "reverse_optical_flow_low_density"
        if "texture" in text:
            return "reverse_optical_flow_texture"
        if "white_line" in text:
            return "reverse_optical_flow_white_line"
        if "original" in text:
            return "reverse_optical_flow_original"
        return "reverse_optical_flow"
    return text or "unknown"


def infer_cohort_id(raw_pa_id: str, condition_raw: str) -> str:
    number = int(raw_pa_id[2:]) if raw_pa_id.startswith("PA") and raw_pa_id[2:].isdigit() else -1
    condition = condition_raw.lower()
    if 1 <= number < 100:
        return "cohort_pa001_099_mixed_conditions"
    if 100 <= number < 200:
        return "cohort_pa100_199_reverse_optical_flow"
    if 200 <= number < 300:
        return "cohort_pa200_299_noise"
    return "cohort_unknown"


def _value_key(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def sequence_hash(rows: Sequence[Mapping[str, object]], columns: Sequence[str], limit: int = 0) -> str:
    digest = hashlib.sha256()
    selected = rows[:limit] if limit else rows
    for row in selected:
        digest.update("|".join(_value_key(row.get(col)) for col in columns).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _missing_blocks(rows: Sequence[Mapping[str, object]], column: str) -> List[Tuple[int, int]]:
    blocks: List[Tuple[int, int]] = []
    start = None
    for index, row in enumerate(rows):
        missing = row.get(column) is None or row.get(column) == ""
        if missing and start is None:
            start = index
        elif not missing and start is not None:
            blocks.append((start, index - 1))
            start = None
    if start is not None:
        blocks.append((start, len(rows) - 1))
    return blocks


def classify_missingness(rows: Sequence[Mapping[str, object]], column: str) -> Dict[str, object]:
    blocks = _missing_blocks(rows, column)
    missing_count = sum(end - start + 1 for start, end in blocks)
    row_count = len(rows)
    if missing_count == 0:
        pattern = "none"
    elif missing_count == row_count:
        pattern = "entire-column missing"
    elif len(blocks) == missing_count:
        pattern = "sporadic missing"
    else:
        pattern = "contiguous missing block"
    return {
        "missing_count": missing_count,
        "missing_fraction": missing_count / row_count if row_count else 0.0,
        "missing_pattern": pattern,
        "block_count": len(blocks),
        "largest_block_length": max((end - start + 1 for start, end in blocks), default=0),
        "blocks": blocks[:10],
    }


def _list_values(rows: Sequence[Mapping[str, object]], column: str) -> str:
    values = sorted({_value_key(row.get(column)) for row in rows if _value_key(row.get(column)) != ""})
    return "|".join(values)


def build_session_manifest(config: DatasetConfig) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    files = discover_csv_files(config.raw_dir_abs)
    manifest: List[Dict[str, object]] = []
    missing_rows: List[Dict[str, object]] = []

    for path in files:
        meta = parse_filename_metadata(path)
        raw_pa_id = meta["participant_id"]
        condition_raw = meta["condition_id"]
        inferred_cohort_id = infer_cohort_id(raw_pa_id, condition_raw)
        source_hash = sha256_file(path)
        rows = list(read_rows(path))
        row_count = len(rows)
        session_uid = stable_session_uid(source_hash, path.name)
        condition_normalized = normalize_condition(condition_raw)
        fms_values = [float(row["fms"]) for row in rows if isinstance(row.get("fms"), float)]
        missing_by_column = {col: classify_missingness(rows, col) for col in CANONICAL_COLUMNS}
        unresolved_reasons = [
            "PAxx prefix is not treated as a globally unique participant ID.",
            "No authoritative subject table links sessions across cohorts.",
        ]
        if any(missing_by_column[col]["missing_count"] for col in STATIC_COLUMNS):
            unresolved_reasons.append("One or more static fields are missing in this session.")
        if any(missing_by_column[col]["missing_count"] == row_count and row_count for col in DYNAMIC_SEQUENCE_COLUMNS):
            unresolved_reasons.append("One or more dynamic/target columns are entirely missing.")
        identity_confidence = "candidate_from_filename_cohort_only"
        subject_uid_candidate = f"{inferred_cohort_id}:{raw_pa_id}"

        manifest.append(
            {
                "source_file": str(path),
                "source_file_sha256": source_hash,
                "raw_pa_id": raw_pa_id,
                "inferred_cohort_id": inferred_cohort_id,
                "subject_uid_candidate": subject_uid_candidate,
                "session_uid": session_uid,
                "condition_raw": condition_raw,
                "condition_normalized": condition_normalized,
                "row_count": row_count,
                "usable_rows_before_420": min(row_count, USABLE_PREFIX_ROWS),
                "age_values": _list_values(rows, "age"),
                "gender_values": _list_values(rows, "gender"),
                "mssq_values": _list_values(rows, "mssq"),
                "fms_min": min(fms_values) if fms_values else "",
                "fms_max": max(fms_values) if fms_values else "",
                "missing_count_by_column": json.dumps(
                    {col: missing_by_column[col]["missing_count"] for col in CANONICAL_COLUMNS},
                    sort_keys=True,
                ),
                "identity_confidence": identity_confidence,
                "unresolved_reasons": " | ".join(unresolved_reasons),
                "content_without_filename_sha256": sequence_hash(rows, CANONICAL_COLUMNS),
                "dynamic_sequence_sha256": sequence_hash(rows, DYNAMIC_SEQUENCE_COLUMNS),
                "dynamic_sequence_first420_sha256": sequence_hash(rows, DYNAMIC_SEQUENCE_COLUMNS, USABLE_PREFIX_ROWS),
                "time_fms_sha256": sequence_hash(rows, TIME_FMS_COLUMNS),
                "time_fms_first420_sha256": sequence_hash(rows, TIME_FMS_COLUMNS, USABLE_PREFIX_ROWS),
                "_first420_dynamic_rows": [
                    tuple(_value_key(row.get(col)) for col in DYNAMIC_SEQUENCE_COLUMNS)
                    for row in rows[:USABLE_PREFIX_ROWS]
                ],
            }
        )
        for col, stats in missing_by_column.items():
            missing_rows.append(
                {
                    "session_uid": session_uid,
                    "source_file": str(path),
                    "raw_pa_id": raw_pa_id,
                    "inferred_cohort_id": inferred_cohort_id,
                    "condition_normalized": condition_normalized,
                    "column": col,
                    "row_count": row_count,
                    "missing_count": stats["missing_count"],
                    "missing_fraction": stats["missing_fraction"],
                    "missing_pattern": stats["missing_pattern"],
                    "block_count": stats["block_count"],
                    "largest_block_length": stats["largest_block_length"],
                    "example_blocks": json.dumps(stats["blocks"]),
                    "interpolation_allowed": "false" if stats["missing_pattern"] == "entire-column missing" else "not_in_this_task",
                }
            )

    return manifest, missing_rows


def build_identity_candidates(manifest: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in manifest:
        grouped[str(row["subject_uid_candidate"])].append(row)
    candidates: List[Dict[str, object]] = []
    for candidate, rows in sorted(grouped.items()):
        age_values = sorted({str(row["age_values"]) for row in rows if row["age_values"]})
        gender_values = sorted({str(row["gender_values"]) for row in rows if row["gender_values"]})
        mssq_values = sorted({str(row["mssq_values"]) for row in rows if row["mssq_values"]})
        reasons = ["Candidate groups sessions only by inferred cohort plus raw PA prefix."]
        if len(age_values) > 1 or len(gender_values) > 1 or len(mssq_values) > 1:
            reasons.append("Static values conflict across sessions; identity remains unresolved.")
        candidates.append(
            {
                "subject_uid_candidate": candidate,
                "raw_pa_id": rows[0]["raw_pa_id"],
                "inferred_cohort_id": rows[0]["inferred_cohort_id"],
                "session_count": len(rows),
                "session_uids": "|".join(str(row["session_uid"]) for row in rows),
                "condition_normalized_values": "|".join(sorted({str(row["condition_normalized"]) for row in rows})),
                "age_values_across_sessions": "|".join(age_values),
                "gender_values_across_sessions": "|".join(gender_values),
                "mssq_values_across_sessions": "|".join(mssq_values),
                "identity_status": "unresolved",
                "identity_confidence": "not_confirmed",
                "unresolved_reasons": " | ".join(reasons),
            }
        )
    return candidates


def _hash_duplicates(manifest: Sequence[Mapping[str, object]], field: str, duplicate_type: str) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in manifest:
        grouped[str(row[field])].append(row)
    duplicates: List[Dict[str, object]] = []
    for digest, rows in grouped.items():
        if len(rows) < 2:
            continue
        duplicates.append(
            {
                "duplicate_type": duplicate_type,
                "evidence": field,
                "evidence_hash": digest,
                "session_count": len(rows),
                "session_uids": "|".join(str(row["session_uid"]) for row in rows),
                "source_files": "|".join(str(row["source_file"]) for row in rows),
                "raw_pa_ids": "|".join(sorted({str(row["raw_pa_id"]) for row in rows})),
                "confirmed_duplicate": "true",
                "split_leakage_risk": "must_keep_together_or_drop_duplicates",
            }
        )
    return duplicates


def _first420_similarity_candidates(manifest: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    reports = _hash_duplicates(manifest, "dynamic_sequence_first420_sha256", "first420_dynamic_exact")

    groups: Dict[Tuple[str, int], List[Mapping[str, object]]] = defaultdict(list)
    for row in manifest:
        groups[(str(row["condition_normalized"]), int(row["usable_rows_before_420"]))].append(row)
    for rows in groups.values():
        for left_index in range(len(rows)):
            left = rows[left_index]
            left_seq = left.get("_first420_dynamic_rows", [])
            if not left_seq:
                continue
            for right in rows[left_index + 1 :]:
                right_seq = right.get("_first420_dynamic_rows", [])
                if not right_seq or len(left_seq) != len(right_seq):
                    continue
                equal_rows = sum(1 for a, b in zip(left_seq, right_seq) if a == b)
                similarity = equal_rows / len(left_seq)
                if similarity >= 0.99 and left["dynamic_sequence_first420_sha256"] != right["dynamic_sequence_first420_sha256"]:
                    reports.append(
                        {
                            "duplicate_type": "first420_dynamic_high_similarity",
                            "evidence": "row_equality_ratio_ge_0.99",
                            "evidence_hash": f"{similarity:.6f}",
                            "session_count": 2,
                            "session_uids": f"{left['session_uid']}|{right['session_uid']}",
                            "source_files": f"{left['source_file']}|{right['source_file']}",
                            "raw_pa_ids": "|".join(sorted({str(left["raw_pa_id"]), str(right["raw_pa_id"])})),
                            "confirmed_duplicate": "false",
                            "split_leakage_risk": "candidate_review_required",
                        }
                    )
    return reports


def build_duplicate_report(manifest: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    reports: List[Dict[str, object]] = []
    reports.extend(_hash_duplicates(manifest, "source_file_sha256", "sha256_identical_file"))
    reports.extend(_hash_duplicates(manifest, "content_without_filename_sha256", "content_identical_excluding_filename"))
    reports.extend(_hash_duplicates(manifest, "dynamic_sequence_sha256", "dynamic_sequence_identical_excluding_static"))
    reports.extend(_first420_similarity_candidates(manifest))
    reports.extend(_hash_duplicates(manifest, "time_fms_sha256", "time_and_fms_identical"))
    return reports


def add_condition_cohort_missingness(missing_rows: List[Dict[str, object]]) -> None:
    totals: Dict[Tuple[str, str, str], Counter] = defaultdict(Counter)
    for row in missing_rows:
        key = (str(row["inferred_cohort_id"]), str(row["condition_normalized"]), str(row["column"]))
        totals[key]["sessions"] += 1
        if int(row["missing_count"]) > 0:
            totals[key]["sessions_with_missing"] += 1
        if row["missing_pattern"] == "entire-column missing":
            totals[key]["entire_column_missing_sessions"] += 1
    for row in missing_rows:
        key = (str(row["inferred_cohort_id"]), str(row["condition_normalized"]), str(row["column"]))
        stats = totals[key]
        row["condition_cohort_sessions"] = stats["sessions"]
        row["condition_cohort_sessions_with_missing"] = stats["sessions_with_missing"]
        row["condition_cohort_entire_column_missing_sessions"] = stats["entire_column_missing_sessions"]
        if stats["sessions_with_missing"] == stats["sessions"] and stats["sessions"] > 0:
            row["condition_cohort_missing_pattern"] = "condition/cohort-specific missing"
        else:
            row["condition_cohort_missing_pattern"] = "not_condition_cohort_specific"


def build_gate_status(
    manifest: Sequence[Mapping[str, object]],
    identity_candidates: Sequence[Mapping[str, object]],
    duplicate_report: Sequence[Mapping[str, object]],
    missing_rows: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    confirmed_duplicates = [row for row in duplicate_report if row["confirmed_duplicate"] == "true"]
    unresolved_identity = [row for row in identity_candidates if row["identity_status"] != "confirmed"]
    entire_column_missing = [row for row in missing_rows if row["missing_pattern"] == "entire-column missing"]
    dynamic_blockers = []
    dynamic_blockers.append(
        "Trusted split unit is unresolved because PAxx is not a confirmed globally unique participant ID."
    )
    if confirmed_duplicates:
        dynamic_blockers.append("Confirmed duplicate sessions exist and must be grouped or removed before split.")
    if entire_column_missing:
        dynamic_blockers.append("Some sessions have entire missing columns; strategy must be explicit and non-interpolating.")
    if unresolved_identity:
        static_blockers = ["Participant identity is unresolved; static personalization cannot treat candidates as confirmed people."]
    else:
        static_blockers = []
    unit_blockers = [
        "Acceleration unit unresolved.",
        "Angular velocity unit unresolved.",
        "Coordinate frame unresolved.",
        "Feature computation provenance unresolved.",
    ]
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "GATE_A_DYNAMIC_BASELINE": {
            "status": "blocked" if dynamic_blockers else "pass",
            "requires": [
                "trusted split unit",
                "no duplicate-session leakage",
                "explicit missing-data handling",
            ],
            "blockers": dynamic_blockers,
        },
        "GATE_B_STATIC_PERSONALIZATION": {
            "status": "blocked" if static_blockers else "pass",
            "requires": ["trusted participant identity", "trusted static feature linkage"],
            "blockers": static_blockers,
        },
        "GATE_C_CROSS_DATASET_TRANSFER": {
            "status": "blocked",
            "requires": ["units", "coordinate frame", "feature computation method"],
            "blockers": unit_blockers,
        },
        "GATE_D_REALTIME_DEPLOYMENT": {
            "status": "blocked",
            "requires": ["units", "coordinate frame", "online feature computation", "runtime missing-data policy"],
            "blockers": unit_blockers + ["Runtime missing-data behavior is not defined."],
        },
    }


def write_csv(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = [name for name in rows[0].keys() if not str(name).startswith("_")]
    elif path.name == "duplicate_session_report.csv":
        fieldnames = list(DUPLICATE_REPORT_FIELDS)
    else:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: value for key, value in row.items() if key in fieldnames})


def assert_unique_session_uids(manifest: Sequence[Mapping[str, object]]) -> None:
    session_uids = [str(row["session_uid"]) for row in manifest]
    if len(session_uids) != len(set(session_uids)):
        raise AssertionError("session_uid values must be unique")


def assert_unresolved_identities_not_confirmed(identity_candidates: Sequence[Mapping[str, object]]) -> None:
    for row in identity_candidates:
        if row.get("identity_status") == "confirmed":
            continue
        if row.get("identity_confidence") in ("confirmed", "high"):
            raise AssertionError("Unresolved identity candidate is marked with confirmed/high confidence")


def assert_duplicate_groups_not_cross_split(
    duplicate_report: Sequence[Mapping[str, object]],
    session_to_split: Mapping[str, str],
) -> None:
    for row in duplicate_report:
        if row.get("confirmed_duplicate") != "true":
            continue
        session_uids = [uid for uid in str(row["session_uids"]).split("|") if uid]
        splits = {session_to_split[uid] for uid in session_uids if uid in session_to_split}
        if len(splits) > 1:
            raise AssertionError(f"Confirmed duplicate sessions cross splits: {session_uids} -> {sorted(splits)}")


def assert_entire_column_missing_not_linear_interpolated(missing_rows: Sequence[Mapping[str, object]]) -> None:
    for row in missing_rows:
        if row.get("missing_pattern") == "entire-column missing" and row.get("interpolation_allowed") != "false":
            raise AssertionError("Entire-column missing data must not be marked for ordinary linear interpolation")


def write_identity_report(
    manifest: Sequence[Mapping[str, object]],
    identity_candidates: Sequence[Mapping[str, object]],
    duplicate_report: Sequence[Mapping[str, object]],
    missing_rows: Sequence[Mapping[str, object]],
    gate_status: Mapping[str, object],
    path: Path,
) -> None:
    cohort_counts = Counter(str(row["inferred_cohort_id"]) for row in manifest)
    raw_pa_counts = Counter(str(row["raw_pa_id"]) for row in manifest)
    missing_av_yz = [row for row in missing_rows if row["column"] in ("angular_velocity_y", "angular_velocity_z") and int(row["missing_count"]) > 0]
    missing_av_yz_patterns = Counter(str(row["missing_pattern"]) for row in missing_av_yz)
    duplicate_counts = Counter(str(row["duplicate_type"]) for row in duplicate_report)
    lines = [
        "# Ryu-Kim Identity Resolution",
        "",
        "This second-round audit does not modify raw data and does not train models.",
        "",
        "## Paper Counts Versus Local Files",
        "",
        "- User-provided paper statistics: four participant batches of 48, 37, 31, and 40, with 427 experiments.",
        f"- Local dataset copy: {len(manifest)} CSV files.",
        f"- Local raw PA prefixes: {len(raw_pa_counts)} unique `PAxx` prefixes.",
        "- The local `PAxx` namespace is not globally unique participant identity evidence. It appears to encode file-batch/session naming, not a single global subject table.",
        "- The extra local CSV count versus 427 is unresolved from the local readme and git history; it remains an audit issue rather than an assumed duplicate.",
        "",
        "Inferred filename cohorts, used only as provenance buckets:",
    ]
    lines.extend(f"- {cohort}: {count} files" for cohort, count in sorted(cohort_counts.items()))
    lines.extend(
        [
            "",
            "## Identity Policy",
            "",
            "- `raw_pa_id` is the parsed filename prefix only.",
            "- `subject_uid_candidate` is `inferred_cohort_id:raw_pa_id` and remains unresolved.",
            "- Age, gender, and MSSQ are consistency checks only; identical static values never confirm identity.",
            "- Static conflicts block static personalization and are never resolved by automatic merging.",
            "",
            "## Duplicate Checks",
            "",
        ]
    )
    if duplicate_counts:
        lines.extend(f"- {kind}: {count} duplicate groups" for kind, count in sorted(duplicate_counts.items()))
    else:
        lines.append("- No confirmed duplicate groups were found by the implemented exact hash checks.")
    lines.extend(
        [
            "",
            "Checks performed:",
            "- SHA256-identical files.",
            "- Content-identical sessions after ignoring filenames.",
            "- Dynamic sequence identical after excluding static fields.",
            "- First-420-row dynamic sequence exact equality.",
            "- Time-series plus FMS exact equality.",
            "",
            "High-similarity first-420 matching uses row-level dynamic equality ratio >= 0.99 within normalized-condition buckets; matching candidates are review-only, not confirmed duplicates.",
            "",
            "## Missingness",
            "",
            f"- Rows in missingness table: {len(missing_rows)}.",
            f"- Angular velocity Y/Z sessions with missing values: {len(missing_av_yz)} column-session records.",
            f"- Angular velocity Y/Z missing patterns: `{dict(missing_av_yz_patterns)}`.",
            "- Missingness classes: none, sporadic missing, contiguous missing block, entire-column missing, and condition/cohort-specific missing.",
            "- No interpolation or imputation is performed in this task.",
            "",
            "## Gate Status",
            "",
        ]
    )
    for gate_name, gate in gate_status.items():
        if not gate_name.startswith("GATE_"):
            continue
        lines.append(f"- {gate_name}: {gate['status']}; blockers: {gate['blockers']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_identity_resolution(config: DatasetConfig) -> Dict[str, object]:
    manifest, missing_rows = build_session_manifest(config)
    add_condition_cohort_missingness(missing_rows)
    identity_candidates = build_identity_candidates(manifest)
    duplicate_report = build_duplicate_report(manifest)
    gate_status = build_gate_status(manifest, identity_candidates, duplicate_report, missing_rows)

    output_dir = config.output_dir_abs
    write_csv(manifest, output_dir / "session_manifest.csv")
    write_csv(identity_candidates, output_dir / "participant_identity_candidates.csv")
    write_csv(duplicate_report, output_dir / "duplicate_session_report.csv")
    write_csv(missing_rows, output_dir / "missingness_by_session.csv")
    with (output_dir / "gate_status.json").open("w", encoding="utf-8") as handle:
        json.dump(gate_status, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    write_identity_report(
        manifest,
        identity_candidates,
        duplicate_report,
        missing_rows,
        gate_status,
        config.resolve(Path("docs/research/ryu_kim_identity_resolution.md")),
    )
    return {
        "manifest": manifest,
        "identity_candidates": identity_candidates,
        "duplicate_report": duplicate_report,
        "missing_rows": missing_rows,
        "gate_status": gate_status,
    }
