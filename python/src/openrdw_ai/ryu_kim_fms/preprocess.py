import math
from collections import Counter
from typing import Dict, Iterable, List, Mapping, Sequence


class Standardizer:
    def __init__(self) -> None:
        self.mean_: List[float] = []
        self.scale_: List[float] = []
        self.fitted_on_participants_: List[str] = []

    def fit(self, matrix: Sequence[Sequence[float]], participant_ids: Sequence[str]) -> "Standardizer":
        if not matrix:
            raise ValueError("Cannot fit scaler on an empty matrix")
        width = len(matrix[0])
        columns = [[float(row[i]) for row in matrix] for i in range(width)]
        self.mean_ = [sum(col) / len(col) for col in columns]
        self.scale_ = []
        for col, mean in zip(columns, self.mean_):
            variance = sum((x - mean) ** 2 for x in col) / len(col)
            scale = math.sqrt(variance)
            self.scale_.append(scale if scale > 0 else 1.0)
        self.fitted_on_participants_ = sorted(set(participant_ids))
        return self

    def transform(self, matrix: Sequence[Sequence[float]]) -> List[List[float]]:
        if not self.mean_:
            raise RuntimeError("Scaler is not fitted")
        return [
            [(float(value) - self.mean_[i]) / self.scale_[i] for i, value in enumerate(row)]
            for row in matrix
        ]


class GenderEncoder:
    def __init__(self) -> None:
        self.categories_: List[str] = []
        self.fitted_on_participants_: List[str] = []

    def fit(self, values: Sequence[str], participant_ids: Sequence[str]) -> "GenderEncoder":
        self.categories_ = sorted(set(v if v else "unknown" for v in values) | {"unknown"})
        self.fitted_on_participants_ = sorted(set(participant_ids))
        return self

    def transform_one(self, value: str) -> List[float]:
        if not self.categories_:
            raise RuntimeError("Encoder is not fitted")
        value = value if value in self.categories_ else "unknown"
        return [1.0 if category == value else 0.0 for category in self.categories_]


class Preprocessor:
    def __init__(self) -> None:
        self.dynamic_scaler = Standardizer()
        self.static_scaler = Standardizer()
        self.gender_encoder = GenderEncoder()

    def fit(self, windows: Sequence[Dict[str, object]], train_participants: Sequence[str]) -> "Preprocessor":
        train_set = set(train_participants)
        train_windows = [w for w in windows if w["participant_id"] in train_set]
        if not train_windows:
            raise ValueError("No training windows available for fitting preprocessors")
        dynamic_rows: List[List[float]] = []
        dynamic_participants: List[str] = []
        static_rows: List[List[float]] = []
        genders: List[str] = []
        static_participants: List[str] = []
        for window in train_windows:
            for row in window["x_dynamic"]:
                dynamic_rows.append(row)
                dynamic_participants.append(str(window["participant_id"]))
            static = window["static_raw"]
            static_rows.append([float(static["age"]), float(static["mssq"])])
            genders.append(str(static["gender"]))
            static_participants.append(str(window["participant_id"]))
        self.dynamic_scaler.fit(dynamic_rows, dynamic_participants)
        self.static_scaler.fit(static_rows, static_participants)
        self.gender_encoder.fit(genders, static_participants)
        return self

    def transform_window(self, window: Dict[str, object]) -> Dict[str, object]:
        static = window["static_raw"]
        x_static_cont = self.static_scaler.transform([[float(static["age"]), float(static["mssq"])]])[0]
        x_static = x_static_cont + self.gender_encoder.transform_one(str(static["gender"]))
        return {
            "participant_id": window["participant_id"],
            "session_id": window["session_id"],
            "start_time": window["start_time"],
            "end_time": window["end_time"],
            "x_dynamic": self.dynamic_scaler.transform(window["x_dynamic"]),
            "x_static": x_static,
            "y_fms": window["y_fms"],
        }


def assert_scaler_fit_only_on_train(preprocessor: Preprocessor, train_participants: Sequence[str]) -> None:
    expected = sorted(set(train_participants))
    for name, fitted in (
        ("dynamic scaler", preprocessor.dynamic_scaler.fitted_on_participants_),
        ("static scaler", preprocessor.static_scaler.fitted_on_participants_),
        ("gender encoder", preprocessor.gender_encoder.fitted_on_participants_),
    ):
        if fitted != expected:
            raise AssertionError(f"{name} fitted on {fitted}, expected only {expected}")

