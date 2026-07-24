import json
import random
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Set


def participant_disjoint_split(
    participant_ids: Sequence[str],
    train_ratio: float,
    validation_ratio: float,
    test_ratio: float,
    seed: int,
) -> Dict[str, List[str]]:
    if round(train_ratio + validation_ratio + test_ratio, 6) != 1.0:
        raise ValueError("Split ratios must sum to 1.0")
    unique_ids = sorted(set(participant_ids))
    if len(unique_ids) < 3:
        raise ValueError("Need at least 3 participants for train/validation/test splits")
    rng = random.Random(seed)
    rng.shuffle(unique_ids)
    n = len(unique_ids)
    n_train = max(1, int(n * train_ratio))
    n_validation = max(1, int(n * validation_ratio))
    if n_train + n_validation >= n:
        n_train = max(1, n - 2)
        n_validation = 1
    return {
        "train": sorted(unique_ids[:n_train]),
        "validation": sorted(unique_ids[n_train : n_train + n_validation]),
        "test": sorted(unique_ids[n_train + n_validation :]),
    }


def validate_participant_disjoint(splits: Mapping[str, Sequence[str]]) -> None:
    seen: Dict[str, str] = {}
    for split_name, ids in splits.items():
        for participant_id in ids:
            if participant_id in seen:
                raise AssertionError(
                    f"Participant {participant_id} appears in both {seen[participant_id]} and {split_name}"
                )
            seen[participant_id] = split_name


def split_for_participant(participant_id: str, splits: Mapping[str, Sequence[str]]) -> str:
    for split_name, ids in splits.items():
        if participant_id in ids:
            return split_name
    raise KeyError(f"Participant {participant_id} is not present in split definition")


def write_splits(splits: Mapping[str, Sequence[str]], output_dir: Path) -> None:
    validate_participant_disjoint(splits)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "participant_splits.json").open("w", encoding="utf-8") as handle:
        json.dump({k: list(v) for k, v in splits.items()}, handle, indent=2)
        handle.write("\n")

