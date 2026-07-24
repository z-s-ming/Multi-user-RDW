from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


CANONICAL_COLUMNS: Tuple[str, ...] = (
    "timestamp",
    "fms",
    "acceleration_x",
    "acceleration_y",
    "acceleration_z",
    "angular_velocity_x",
    "angular_velocity_y",
    "angular_velocity_z",
    "gender",
    "mssq",
    "age",
)

DYNAMIC_FEATURES: Tuple[str, ...] = (
    "acceleration_x",
    "acceleration_y",
    "acceleration_z",
    "angular_velocity_x",
    "angular_velocity_y",
    "angular_velocity_z",
)

STATIC_CONTINUOUS_FEATURES: Tuple[str, ...] = ("age", "mssq")
STATIC_CATEGORICAL_FEATURES: Tuple[str, ...] = ("gender",)
WINDOW_DURATIONS_SECONDS: Tuple[float, ...] = (10.0, 30.0, 60.0)


@dataclass(frozen=True)
class FieldMapping:
    """Mapping inferred from dataset readme column order.

    The raw CSV files have no header. Units for acceleration, angular velocity,
    and FMS bounds are intentionally left unresolved until source documentation
    confirms them.
    """

    canonical_columns: Tuple[str, ...] = CANONICAL_COLUMNS
    units: Dict[str, str] = field(
        default_factory=lambda: {
            "timestamp": "seconds",
            "fms": "UNKNOWN",
            "acceleration_x": "UNKNOWN",
            "acceleration_y": "UNKNOWN",
            "acceleration_z": "UNKNOWN",
            "angular_velocity_x": "UNKNOWN",
            "angular_velocity_y": "UNKNOWN",
            "angular_velocity_z": "UNKNOWN",
            "gender": "category",
            "mssq": "score",
            "age": "years",
        }
    )
    source_note: str = (
        "shared/data/raw/pretraining/2025_Cybersickness_dataset/readme.md lists "
        "the eleven headerless CSV columns in this order."
    )


@dataclass(frozen=True)
class DatasetConfig:
    repo_root: Path = Path(__file__).resolve().parents[4]
    raw_data_dir: Path = Path(
        "shared/data/raw/pretraining/2025_Cybersickness_dataset/Dataset"
    )
    readme_path: Path = Path(
        "shared/data/raw/pretraining/2025_Cybersickness_dataset/readme.md"
    )
    output_dir: Path = Path("shared/data/processed/ryu_kim")
    report_path: Path = Path("docs/research/ryu_kim_fms_data_audit.md")
    audit_json_path: Path = Path("shared/data/processed/ryu_kim/dataset_audit.json")
    split_dir: Path = Path("shared/data/processed/ryu_kim/splits")
    expected_interval_seconds: float = 0.5
    maximum_allowed_gap_seconds: float = 1.0
    split_seed: int = 42
    train_ratio: float = 0.70
    validation_ratio: float = 0.15
    test_ratio: float = 0.15
    field_mapping: FieldMapping = field(default_factory=FieldMapping)

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path

    @property
    def raw_dir_abs(self) -> Path:
        return self.resolve(self.raw_data_dir)

    @property
    def output_dir_abs(self) -> Path:
        return self.resolve(self.output_dir)

