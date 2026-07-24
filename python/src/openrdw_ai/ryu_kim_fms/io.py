import csv
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from .schema import CANONICAL_COLUMNS


PARTICIPANT_RE = re.compile(r"^(PA\d+)")
TIME_SUFFIX_RE = re.compile(r"_(\d{1,2})_(\d{2})_(\d{2})_(AM|PM)$", re.IGNORECASE)


def discover_csv_files(raw_data_dir: Path) -> List[Path]:
    return sorted(p for p in raw_data_dir.glob("*.csv") if p.is_file())


def parse_filename_metadata(path: Path) -> Dict[str, str]:
    stem = path.stem
    match = PARTICIPANT_RE.match(stem)
    participant_id = match.group(1) if match else ""
    remainder = stem[len(participant_id) + 1 :] if participant_id and stem.startswith(participant_id + "_") else ""
    condition_id = TIME_SUFFIX_RE.sub("", remainder)
    return {
        "source_file": str(path),
        "source_filename": path.name,
        "participant_id": participant_id,
        "session_id": stem,
        "condition_id": condition_id,
    }


def parse_float(value: str) -> Optional[float]:
    value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_rows(path: Path) -> Iterator[Dict[str, object]]:
    meta = parse_filename_metadata(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader):
            record: Dict[str, object] = dict(meta)
            record["row_index"] = row_index
            record["raw_column_count"] = len(row)
            for col_index, name in enumerate(CANONICAL_COLUMNS):
                value = row[col_index].strip() if col_index < len(row) else ""
                if name == "gender":
                    record[name] = value.lower()
                else:
                    record[name] = parse_float(value)
            yield record


def read_all_rows(files: Iterable[Path]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for path in files:
        rows.extend(read_rows(path))
    return rows

