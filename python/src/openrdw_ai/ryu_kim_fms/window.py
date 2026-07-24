from collections import defaultdict
from typing import Dict, Iterable, Iterator, List, Sequence

from .schema import DYNAMIC_FEATURES


def window_length_steps(duration_seconds: float, sample_interval_seconds: float) -> int:
    steps = round(duration_seconds / sample_interval_seconds)
    if steps <= 0:
        raise ValueError("Window length must be positive")
    if abs(steps * sample_interval_seconds - duration_seconds) > 1e-6:
        raise ValueError("Window duration must be divisible by sample interval")
    return steps


def generate_causal_windows(
    rows: Sequence[Dict[str, object]],
    duration_seconds: float,
    sample_interval_seconds: float,
    stride_steps: int = 1,
    dynamic_features: Sequence[str] = DYNAMIC_FEATURES,
) -> Iterator[Dict[str, object]]:
    length = window_length_steps(duration_seconds, sample_interval_seconds)
    grouped: Dict[tuple, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(row["participant_id"], row["session_id"])].append(row)

    for (participant_id, session_id), session_rows in sorted(grouped.items()):
        sortable_rows = [r for r in session_rows if r.get("timestamp") is not None]
        ordered = sorted(sortable_rows, key=lambda r: (float(r["timestamp"]), int(r.get("row_index", 0))))
        for end_index in range(length - 1, len(ordered), stride_steps):
            start_index = end_index - length + 1
            chunk = ordered[start_index : end_index + 1]
            if len(chunk) != length:
                continue
            required_fields = tuple(dynamic_features) + ("timestamp", "fms", "age", "mssq", "gender")
            if any(r.get(name) is None or r.get(name) == "" for r in chunk for name in required_fields):
                continue
            timestamps = [float(r["timestamp"]) for r in chunk]
            terminal_time = timestamps[-1]
            if any(t > terminal_time for t in timestamps):
                raise AssertionError("Causal window contains a future frame")
            features = [[float(r[name]) for name in dynamic_features] for r in chunk]
            yield {
                "participant_id": participant_id,
                "session_id": session_id,
                "start_time": timestamps[0],
                "end_time": terminal_time,
                "source_row_start": int(chunk[0].get("row_index", start_index)),
                "source_row_end": int(chunk[-1].get("row_index", end_index)),
                "x_dynamic": features,
                "x_dynamic_feature_names": list(dynamic_features),
                "static_raw": {
                    "age": chunk[-1]["age"],
                    "mssq": chunk[-1]["mssq"],
                    "gender": chunk[-1]["gender"],
                },
                "y_fms": float(chunk[-1]["fms"]),
            }


def assert_no_future_frames(window: Dict[str, object]) -> None:
    if window["start_time"] > window["end_time"]:
        raise AssertionError("Window start is after terminal time")
    if window["source_row_start"] > window["source_row_end"]:
        raise AssertionError("Window source rows are inverted")
    if "fms" in window.get("x_dynamic_feature_names", []):
        raise AssertionError("FMS must not be present in input feature names")
