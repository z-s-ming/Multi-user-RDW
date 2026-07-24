import csv
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .io import discover_csv_files, parse_filename_metadata, read_rows
from .schema import DYNAMIC_FEATURES, DatasetConfig


FMS_BINS = ((0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0000001))
FORBIDDEN_INPUT_NAMES = {
    "fms",
    "fms_history",
    "age",
    "gender",
    "mssq",
    "participant_id",
    "raw_pa_id",
    "session_id",
    "condition",
    "condition_id",
    "condition_raw",
    "condition_normalized",
    "source_file",
    "source_filename",
}


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def rmse(errors: Sequence[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else float("nan")


def stdev(values: Sequence[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


class DynamicStandardizer:
    def __init__(self, feature_names: Sequence[str] = DYNAMIC_FEATURES) -> None:
        self.feature_names = list(feature_names)
        self.mean_: List[float] = []
        self.scale_: List[float] = []
        self.fit_group_ids_: List[str] = []

    def fit(self, windows: Sequence[Mapping[str, object]], train_raw_pa_ids: Sequence[str]) -> "DynamicStandardizer":
        train_groups = set(train_raw_pa_ids)
        columns: List[List[float]] = [[] for _ in self.feature_names]
        fast_counts = [0 for _ in self.feature_names]
        fast_sums = [0.0 for _ in self.feature_names]
        fast_sumsq = [0.0 for _ in self.feature_names]
        fast_available = False
        fit_groups = set()
        for window in windows:
            if window["raw_pa_id"] not in train_groups:
                continue
            fit_groups.add(str(window["raw_pa_id"]))
            if "raw_feature_stats" in window:
                fast_available = True
                for index, stats in enumerate(window["raw_feature_stats"]):
                    fast_counts[index] += int(stats["count"])
                    fast_sums[index] += float(stats["sum"])
                    fast_sumsq[index] += float(stats["sumsq"])
                continue
            for values, mask in zip(window["x_dynamic"], window["missing_mask"]):
                for index, value in enumerate(values):
                    if not mask[index] and value is not None:
                        columns[index].append(float(value))
        if fast_available:
            if any(count == 0 for count in fast_counts):
                raise ValueError("Cannot fit standardizer because at least one feature has no observed training values")
            self.mean_ = [total / count for total, count in zip(fast_sums, fast_counts)]
            self.scale_ = []
            for count, total, total_sq, m in zip(fast_counts, fast_sums, fast_sumsq, self.mean_):
                variance = max(0.0, total_sq / count - m * m)
                self.scale_.append(math.sqrt(variance) or 1.0)
        else:
            if any(not col for col in columns):
                raise ValueError("Cannot fit standardizer because at least one feature has no observed training values")
            self.mean_ = [mean(col) for col in columns]
            self.scale_ = []
            for col, m in zip(columns, self.mean_):
                variance = sum((x - m) ** 2 for x in col) / len(col)
                self.scale_.append(math.sqrt(variance) or 1.0)
        self.fit_group_ids_ = sorted(fit_groups)
        return self

    def transform_window(self, window: Mapping[str, object]) -> List[List[float]]:
        transformed: List[List[float]] = []
        for values, mask in zip(window["x_dynamic"], window["missing_mask"]):
            row: List[float] = []
            for index, value in enumerate(values):
                if mask[index] or value is None:
                    row.append(0.0)
                else:
                    row.append((float(value) - self.mean_[index]) / self.scale_[index])
            transformed.append(row)
        return transformed


def assert_allowed_model_inputs(feature_names: Sequence[str]) -> None:
    forbidden = FORBIDDEN_INPUT_NAMES.intersection(set(feature_names))
    if forbidden:
        raise AssertionError(f"Forbidden model input features present: {sorted(forbidden)}")


def assert_no_future_frames_in_window(window: Mapping[str, object]) -> None:
    timestamps = window.get("timestamps", [])
    if not timestamps:
        raise AssertionError("Window has no timestamps")
    terminal = float(window["end_time"])
    if any(float(t) > terminal for t in timestamps):
        raise AssertionError("Window contains future frames")


def assert_window_does_not_cross_session(window: Mapping[str, object]) -> None:
    session_uid = window.get("session_uid")
    if not session_uid:
        raise AssertionError("Window is missing session_uid")
    session_uids = window.get("session_uids", [session_uid])
    if len(set(session_uids)) != 1:
        raise AssertionError("Window crosses session boundaries")


def load_raw_sessions(config: DatasetConfig) -> List[Dict[str, object]]:
    sessions: List[Dict[str, object]] = []
    for path in discover_csv_files(config.raw_dir_abs):
        meta = parse_filename_metadata(path)
        rows = list(read_rows(path))
        raw_pa_id = meta["participant_id"]
        sessions.append(
            {
                "source_file": str(path),
                "raw_pa_id": raw_pa_id,
                "session_uid": meta["session_id"],
                "session_id": meta["session_id"],
                "condition_id": meta["condition_id"],
                "rows": rows,
            }
        )
    return sessions


def make_dynamic_windows(
    sessions: Sequence[Mapping[str, object]],
    duration_seconds: float,
    sample_interval_seconds: float,
    max_missing_fraction: float,
    stride_steps: int = 1,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    length = round(duration_seconds / sample_interval_seconds)
    windows: List[Dict[str, object]] = []
    excluded = 0
    excluded_sessions = set()
    excluded_groups = set()
    candidate_windows = 0
    for session in sessions:
        rows = [r for r in session["rows"] if r.get("timestamp") is not None]
        rows = sorted(rows, key=lambda r: (float(r["timestamp"]), int(r.get("row_index", 0))))
        for end_index in range(length - 1, len(rows), stride_steps):
            chunk = rows[end_index - length + 1 : end_index + 1]
            if len(chunk) != length:
                continue
            terminal = chunk[-1]
            if terminal.get("fms") is None:
                continue
            candidate_windows += 1
            x_dynamic: List[List[Optional[float]]] = []
            missing_mask: List[List[int]] = []
            missing_count = 0
            for row in chunk:
                values: List[Optional[float]] = []
                mask_row: List[int] = []
                for feature in DYNAMIC_FEATURES:
                    value = row.get(feature)
                    is_missing = value is None
                    values.append(float(value) if value is not None else None)
                    mask_row.append(1 if is_missing else 0)
                    missing_count += 1 if is_missing else 0
                x_dynamic.append(values)
                missing_mask.append(mask_row)
            raw_feature_stats = []
            for feature_index in range(len(DYNAMIC_FEATURES)):
                observed = [
                    row[feature_index]
                    for row, mask_row in zip(x_dynamic, missing_mask)
                    if not mask_row[feature_index] and row[feature_index] is not None
                ]
                raw_feature_stats.append(
                    {
                        "count": len(observed),
                        "missing_count": length - len(observed),
                        "sum": sum(observed),
                        "sumsq": sum(value * value for value in observed),
                        "min": min(observed) if observed else None,
                        "max": max(observed) if observed else None,
                        "first": x_dynamic[0][feature_index],
                        "first_missing": missing_mask[0][feature_index],
                        "last": x_dynamic[-1][feature_index],
                        "last_missing": missing_mask[-1][feature_index],
                    }
                )
            raw_lag_values = []
            last_index = length - 1
            for feature_index in range(len(DYNAMIC_FEATURES)):
                feature_lags = []
                for dilation in (1, 2, 4, 8, 16):
                    for tap in range(2):
                        source_index = last_index - tap * dilation
                        if source_index < 0 or missing_mask[source_index][feature_index]:
                            feature_lags.append(None)
                        else:
                            feature_lags.append(x_dynamic[source_index][feature_index])
                raw_lag_values.append(feature_lags)
            missing_fraction = missing_count / (length * len(DYNAMIC_FEATURES))
            if missing_fraction > max_missing_fraction:
                excluded += 1
                excluded_sessions.add(str(session["session_uid"]))
                excluded_groups.add(str(session["raw_pa_id"]))
                continue
            window = {
                "raw_pa_id": session["raw_pa_id"],
                "session_uid": session["session_uid"],
                "timestamps": [float(row["timestamp"]) for row in chunk],
                "start_time": float(chunk[0]["timestamp"]),
                "end_time": float(terminal["timestamp"]),
                "source_row_start": int(chunk[0].get("row_index", 0)),
                "source_row_end": int(terminal.get("row_index", end_index)),
                "x_dynamic_feature_names": list(DYNAMIC_FEATURES),
                "missing_mask_generated": True,
                "missing_count_by_dynamic_feature": {
                    name: raw_feature_stats[index]["missing_count"]
                    for index, name in enumerate(DYNAMIC_FEATURES)
                },
                "raw_feature_stats": raw_feature_stats,
                "raw_lag_values": raw_lag_values,
                "window_length_steps": length,
                "dynamic_missing_fraction": missing_fraction,
                "has_missing_dynamic": missing_count > 0,
                "y_fms": float(terminal["fms"]),
            }
            assert_allowed_model_inputs(window["x_dynamic_feature_names"])
            assert_no_future_frames_in_window(window)
            assert_window_does_not_cross_session(window)
            windows.append(window)
    exclusion = {
        "candidate_windows": candidate_windows,
        "effective_windows": len(windows),
        "excluded_windows_missing_fraction_gt_threshold": excluded,
        "excluded_sessions": len(excluded_sessions),
        "excluded_raw_pa_id_groups": len(excluded_groups),
        "window_length_steps": length,
    }
    return windows, exclusion


def make_group_kfold_assignments(
    group_to_weight: Mapping[str, int],
    n_folds: int,
    seed: int,
) -> Dict[str, int]:
    rng = random.Random(seed)
    groups = list(group_to_weight.items())
    rng.shuffle(groups)
    groups.sort(key=lambda item: item[1], reverse=True)
    fold_weights = [0 for _ in range(n_folds)]
    assignments: Dict[str, int] = {}
    for group, weight in groups:
        fold_index = min(range(n_folds), key=lambda i: (fold_weights[i], i))
        assignments[group] = fold_index
        fold_weights[fold_index] += weight
    return assignments


def split_windows_by_fold(
    windows: Sequence[Mapping[str, object]],
    fold_assignments: Mapping[str, int],
    test_fold: int,
) -> Tuple[List[Mapping[str, object]], List[Mapping[str, object]]]:
    train, test = [], []
    for window in windows:
        if fold_assignments[str(window["raw_pa_id"])] == test_fold:
            test.append(window)
        else:
            train.append(window)
    return train, test


def assert_raw_pa_and_session_disjoint(
    train_windows: Sequence[Mapping[str, object]],
    test_windows: Sequence[Mapping[str, object]],
) -> None:
    train_groups = {str(w["raw_pa_id"]) for w in train_windows}
    test_groups = {str(w["raw_pa_id"]) for w in test_windows}
    if train_groups.intersection(test_groups):
        raise AssertionError("raw_pa_id groups overlap between train and test")
    train_sessions = {str(w["session_uid"]) for w in train_windows}
    test_sessions = {str(w["session_uid"]) for w in test_windows}
    if train_sessions.intersection(test_sessions):
        raise AssertionError("sessions overlap between train and test")


def fms_bin(value: float) -> str:
    for low, high in FMS_BINS:
        if low <= value < high:
            return f"{int(low)}-{int(high if high < 20.1 else 20)}"
    return "outside"


def check_fold_balance_or_raise(windows: Sequence[Mapping[str, object]], fold_assignments: Mapping[str, int], n_folds: int) -> None:
    session_counts = []
    global_bins = Counter(fms_bin(float(w["y_fms"])) for w in windows)
    major_bins = {k for k, v in global_bins.items() if v / len(windows) >= 0.05}
    for fold in range(n_folds):
        fold_windows = [w for w in windows if fold_assignments[str(w["raw_pa_id"])] == fold]
        if not fold_windows:
            raise RuntimeError(f"Fold {fold} has no windows")
        session_counts.append(len({str(w["session_uid"]) for w in fold_windows}))
        fold_bins = Counter(fms_bin(float(w["y_fms"])) for w in fold_windows)
        missing_major = sorted(bin_name for bin_name in major_bins if fold_bins[bin_name] == 0)
        if missing_major:
            raise RuntimeError(f"Fold {fold} is severely imbalanced; missing major FMS bins {missing_major}")
    mean_sessions = mean(session_counts)
    for fold, count in enumerate(session_counts):
        ratio = count / mean_sessions if mean_sessions else 0
        if ratio < 0.25 or ratio > 4.0:
            raise RuntimeError(f"Fold {fold} session count is severely imbalanced: {count} vs mean {mean_sessions:.2f}")


def matrix_features_window_stats(x: Sequence[Sequence[float]]) -> List[float]:
    features: List[float] = []
    width = len(x[0])
    for index in range(width):
        col = [row[index] for row in x]
        m = mean(col)
        variance = mean([(value - m) ** 2 for value in col])
        features.extend([m, math.sqrt(variance), min(col), max(col), col[0], col[-1]])
    return features


def _standardize_value(value: Optional[float], missing: int, mean_value: float, scale_value: float) -> float:
    if missing or value is None:
        return 0.0
    return (float(value) - mean_value) / scale_value


def fast_matrix_features_window_stats(window: Mapping[str, object], standardizer: DynamicStandardizer) -> List[float]:
    features: List[float] = []
    length = int(window["window_length_steps"])
    for index, stats in enumerate(window["raw_feature_stats"]):
        m = standardizer.mean_[index]
        s = standardizer.scale_[index]
        count = int(stats["count"])
        raw_sum = float(stats["sum"])
        raw_sumsq = float(stats["sumsq"])
        z_sum = (raw_sum - count * m) / s
        z_mean = z_sum / length
        z_sumsq = (raw_sumsq - 2 * m * raw_sum + count * m * m) / (s * s)
        variance = max(0.0, z_sumsq / length - z_mean * z_mean)
        values_for_minmax = []
        if stats["min"] is not None:
            values_for_minmax.append((float(stats["min"]) - m) / s)
        if stats["max"] is not None:
            values_for_minmax.append((float(stats["max"]) - m) / s)
        if int(stats["missing_count"]) > 0:
            values_for_minmax.append(0.0)
        if not values_for_minmax:
            values_for_minmax.append(0.0)
        first = _standardize_value(stats["first"], int(stats["first_missing"]), m, s)
        last = _standardize_value(stats["last"], int(stats["last_missing"]), m, s)
        features.extend([z_mean, math.sqrt(variance), min(values_for_minmax), max(values_for_minmax), first, last])
    return features


def matrix_features_causal_tcn_linear(x: Sequence[Sequence[float]], dilations: Sequence[int] = (1, 2, 4, 8, 16), taps: int = 2) -> List[float]:
    features: List[float] = []
    last_index = len(x) - 1
    width = len(x[0])
    for channel in range(width):
        for dilation in dilations:
            for tap in range(taps):
                source_index = last_index - tap * dilation
                features.append(x[source_index][channel] if source_index >= 0 else 0.0)
    features.extend(matrix_features_window_stats(x))
    return features


def fast_matrix_features_causal_tcn_linear(window: Mapping[str, object], standardizer: DynamicStandardizer) -> List[float]:
    features: List[float] = []
    for channel, lags in enumerate(window["raw_lag_values"]):
        for value in lags:
            features.append(_standardize_value(value, 1 if value is None else 0, standardizer.mean_[channel], standardizer.scale_[channel]))
    features.extend(fast_matrix_features_window_stats(window, standardizer))
    return features


def prepare_design(
    windows: Sequence[Mapping[str, object]],
    standardizer: DynamicStandardizer,
    model_name: str,
) -> Tuple[List[List[float]], List[float]]:
    x_rows: List[List[float]] = []
    y: List[float] = []
    for window in windows:
        if "raw_feature_stats" in window:
            if model_name == "ridge_window_stats":
                features = fast_matrix_features_window_stats(window, standardizer)
            elif model_name == "causal_tcn_linear":
                features = fast_matrix_features_causal_tcn_linear(window, standardizer)
            else:
                raise ValueError(model_name)
        else:
            x = standardizer.transform_window(window)
            if model_name == "ridge_window_stats":
                features = matrix_features_window_stats(x)
            elif model_name == "causal_tcn_linear":
                features = matrix_features_causal_tcn_linear(x)
            else:
                raise ValueError(model_name)
        x_rows.append(features)
        y.append(float(window["y_fms"]))
    return x_rows, y


def solve_linear_system(a: List[List[float]], b: List[float]) -> List[float]:
    n = len(b)
    aug = [row[:] + [b_i] for row, b_i in zip(a, b)]
    for pivot in range(n):
        best = max(range(pivot, n), key=lambda r: abs(aug[r][pivot]))
        aug[pivot], aug[best] = aug[best], aug[pivot]
        if abs(aug[pivot][pivot]) < 1e-12:
            aug[pivot][pivot] = 1e-12
        pivot_value = aug[pivot][pivot]
        for col in range(pivot, n + 1):
            aug[pivot][col] /= pivot_value
        for row in range(n):
            if row == pivot:
                continue
            factor = aug[row][pivot]
            if factor == 0:
                continue
            for col in range(pivot, n + 1):
                aug[row][col] -= factor * aug[pivot][col]
    return [aug[i][n] for i in range(n)]


class RidgeRegressor:
    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.coef_: List[float] = []

    def fit(self, x_rows: Sequence[Sequence[float]], y: Sequence[float]) -> "RidgeRegressor":
        if not x_rows:
            raise ValueError("No rows for Ridge fit")
        p = len(x_rows[0]) + 1
        xtx = [[0.0 for _ in range(p)] for _ in range(p)]
        xty = [0.0 for _ in range(p)]
        for x, target in zip(x_rows, y):
            row = [1.0] + list(x)
            for i in range(p):
                xty[i] += row[i] * target
                for j in range(p):
                    xtx[i][j] += row[i] * row[j]
        for i in range(1, p):
            xtx[i][i] += self.alpha
        self.coef_ = solve_linear_system(xtx, xty)
        return self

    def predict(self, x_rows: Sequence[Sequence[float]]) -> List[float]:
        return [self.coef_[0] + sum(c * v for c, v in zip(self.coef_[1:], x)) for x in x_rows]

    @property
    def parameter_count(self) -> int:
        return len(self.coef_)


class MeanFmsRegressor:
    def __init__(self) -> None:
        self.value = 0.0

    def fit(self, y: Sequence[float]) -> "MeanFmsRegressor":
        self.value = mean(y)
        return self

    def predict(self, count: int) -> List[float]:
        return [self.value for _ in range(count)]

    @property
    def parameter_count(self) -> int:
        return 1


def regression_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> Dict[str, float]:
    errors = [pred - true for true, pred in zip(y_true, y_pred)]
    mae = mean([abs(e) for e in errors])
    root = rmse(errors)
    y_mean = mean(y_true)
    ss_res = sum(e * e for e in errors)
    ss_tot = sum((y - y_mean) ** 2 for y in y_true)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"mae": mae, "rmse": root, "r2": r2}


def grouped_macro_metrics(predictions: Sequence[Mapping[str, object]], group_key: str) -> Dict[str, float]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in predictions:
        grouped[str(row[group_key])].append(row)
    maes, rmses = [], []
    for rows in grouped.values():
        errors = [float(row["y_pred"]) - float(row["y_true"]) for row in rows]
        maes.append(mean([abs(e) for e in errors]))
        rmses.append(rmse(errors))
    return {"mae": mean(maes), "rmse": mean(rmses)}


def metrics_by_slice(predictions: Sequence[Mapping[str, object]], slice_key: str) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in predictions:
        grouped[str(row[slice_key])].append(row)
    result: Dict[str, Dict[str, float]] = {}
    for key, rows in sorted(grouped.items()):
        y_true = [float(row["y_true"]) for row in rows]
        y_pred = [float(row["y_pred"]) for row in rows]
        result[key] = regression_metrics(y_true, y_pred)
    return result


def summarize_predictions(
    predictions: Sequence[Mapping[str, object]],
    duration: float,
    fold: int,
    model_name: str,
    train_time: float,
    inference_time: float,
    parameter_count: int,
) -> Dict[str, object]:
    y_true = [float(row["y_true"]) for row in predictions]
    y_pred = [float(row["y_pred"]) for row in predictions]
    window_metrics = regression_metrics(y_true, y_pred)
    session_metrics = grouped_macro_metrics(predictions, "session_uid")
    group_metrics = grouped_macro_metrics(predictions, "raw_pa_id")
    return {
        "duration_seconds": duration,
        "fold": fold,
        "model": model_name,
        "window_count": len(predictions),
        "window_mae": window_metrics["mae"],
        "window_rmse": window_metrics["rmse"],
        "window_r2": window_metrics["r2"],
        "session_macro_mae": session_metrics["mae"],
        "session_macro_rmse": session_metrics["rmse"],
        "raw_pa_id_group_macro_mae": group_metrics["mae"],
        "raw_pa_id_group_macro_rmse": group_metrics["rmse"],
        "train_time_seconds": train_time,
        "inference_latency_ms_per_window": (inference_time / len(predictions) * 1000.0) if predictions else 0.0,
        "parameter_count": parameter_count,
    }


def write_csv(rows: Sequence[Mapping[str, object]], path: Path, fieldnames: Optional[Sequence[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fieldnames:
        path.write_text("", encoding="utf-8")
        return
    names = list(fieldnames or rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})


def write_json(data: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def default_progress(message: str) -> None:
    print(message, flush=True)


def select_curve_sessions(predictions: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    by_session: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in predictions:
        by_session[str(row["session_uid"])].append(row)
    session_errors = []
    for session_uid, rows in by_session.items():
        mae = mean([abs(float(r["y_pred"]) - float(r["y_true"])) for r in rows])
        session_errors.append((mae, session_uid, rows))
    if not session_errors:
        return []
    session_errors.sort(key=lambda item: item[0])
    indices = sorted(set([0, len(session_errors) // 2, len(session_errors) - 1]))
    labels = {0: "low_error", len(session_errors) // 2: "median_error", len(session_errors) - 1: "high_error"}
    selected = []
    for index in indices:
        mae, session_uid, rows = session_errors[index]
        label = labels.get(index, "selected")
        for row in sorted(rows, key=lambda r: float(r["end_time"])):
            selected.append({**row, "curve_rank": label, "session_mae": mae})
    return selected


def run_dynamic_baseline(
    repo_root: Path,
    output_dir: Path,
    n_folds: int = 5,
    seed: int = 42,
    durations_seconds: Sequence[float] = (10.0, 30.0, 60.0),
    max_missing_fraction: float = 0.20,
    progress=default_progress,
) -> Dict[str, object]:
    config = DatasetConfig(repo_root=repo_root)
    progress("[setup] loading raw sessions")
    sessions = load_raw_sessions(config)
    raw_session_count = len(sessions)
    progress(f"[setup] loaded {raw_session_count} sessions")
    output_dir.mkdir(parents=True, exist_ok=True)
    all_metric_rows: List[Dict[str, object]] = []
    all_window_counts: List[Dict[str, object]] = []

    for duration in durations_seconds:
        duration_start = time.perf_counter()
        progress(f"[{duration:.0f}s] generating causal windows")
        windows, exclusion = make_dynamic_windows(
            sessions,
            duration,
            config.expected_interval_seconds,
            max_missing_fraction,
        )
        progress(
            f"[{duration:.0f}s] windows ready: "
            f"effective={exclusion['effective_windows']}, "
            f"excluded_missing>{max_missing_fraction:.0%}="
            f"{exclusion['excluded_windows_missing_fraction_gt_threshold']}"
        )
        group_weights = Counter(str(w["raw_pa_id"]) for w in windows)
        progress(f"[{duration:.0f}s] assigning {len(group_weights)} raw_pa_id groups to {n_folds} folds")
        fold_assignments = make_group_kfold_assignments(group_weights, n_folds, seed)
        progress(f"[{duration:.0f}s] checking fold balance")
        check_fold_balance_or_raise(windows, fold_assignments, n_folds)
        write_json(
            {
                "duration_seconds": duration,
                "split_name": "raw_pa_id-group-disjoint split",
                "fold_assignments": fold_assignments,
            },
            output_dir / f"splits_{int(duration)}s.json",
        )
        all_window_counts.append({"duration_seconds": duration, **exclusion})

        duration_predictions: List[Dict[str, object]] = []
        for fold in range(n_folds):
            train_windows, test_windows = split_windows_by_fold(windows, fold_assignments, fold)
            progress(
                f"[{duration:.0f}s][fold {fold + 1}/{n_folds}] "
                f"train_windows={len(train_windows)}, test_windows={len(test_windows)}"
            )
            assert_raw_pa_and_session_disjoint(train_windows, test_windows)
            train_groups = sorted({str(w["raw_pa_id"]) for w in train_windows})
            progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}] fitting training-fold standardizer")
            standardizer = DynamicStandardizer().fit(windows, train_groups)
            if standardizer.fit_group_ids_ != train_groups:
                raise AssertionError("Standardizer fitted on groups outside the training fold")

            y_train = [float(w["y_fms"]) for w in train_windows]
            y_test = [float(w["y_fms"]) for w in test_windows]
            model_specs = ["mean_fms", "ridge_window_stats", "causal_tcn_linear"]
            fold_predictions_by_model: Dict[str, List[Dict[str, object]]] = {}
            for model_name in model_specs:
                progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}][{model_name}] training")
                start_train = time.perf_counter()
                if model_name == "mean_fms":
                    model = MeanFmsRegressor().fit(y_train)
                    train_time = time.perf_counter() - start_train
                    progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}][{model_name}] predicting")
                    start_infer = time.perf_counter()
                    y_pred = model.predict(len(test_windows))
                    inference_time = time.perf_counter() - start_infer
                else:
                    x_train, _ = prepare_design(train_windows, standardizer, model_name)
                    model = RidgeRegressor(alpha=1.0).fit(x_train, y_train)
                    train_time = time.perf_counter() - start_train
                    progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}][{model_name}] building test features")
                    x_test, _ = prepare_design(test_windows, standardizer, model_name)
                    progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}][{model_name}] predicting")
                    start_infer = time.perf_counter()
                    y_pred = model.predict(x_test)
                    inference_time = time.perf_counter() - start_infer
                prediction_rows = []
                for window, true, pred in zip(test_windows, y_test, y_pred):
                    prediction_rows.append(
                        {
                            "duration_seconds": duration,
                            "fold": fold,
                            "model": model_name,
                            "raw_pa_id": window["raw_pa_id"],
                            "session_uid": window["session_uid"],
                            "end_time": window["end_time"],
                            "source_row_end": window["source_row_end"],
                            "missing_slice": "missing_dynamic" if window["has_missing_dynamic"] else "complete_dynamic",
                            "fms_bin": fms_bin(float(true)),
                            "y_true": true,
                            "y_pred": pred,
                        }
                    )
                fold_predictions_by_model[model_name] = prediction_rows
                primary_metrics = summarize_predictions(
                    prediction_rows,
                    duration,
                    fold,
                    model_name,
                    train_time,
                    inference_time,
                    model.parameter_count,
                )
                all_metric_rows.append(primary_metrics)
                progress(
                    f"[{duration:.0f}s][fold {fold + 1}/{n_folds}][{model_name}] "
                    f"done: MAE={primary_metrics['window_mae']:.4f}, "
                    f"RMSE={primary_metrics['window_rmse']:.4f}, "
                    f"train={train_time:.2f}s, "
                    f"latency={primary_metrics['inference_latency_ms_per_window']:.4f}ms/window"
                )
                for bin_name, values in metrics_by_slice(prediction_rows, "fms_bin").items():
                    all_metric_rows.append(
                        {
                            "duration_seconds": duration,
                            "fold": fold,
                            "model": model_name,
                            "metric_slice": f"fms_bin_{bin_name}",
                            "window_count": len([r for r in prediction_rows if r["fms_bin"] == bin_name]),
                            "window_mae": values["mae"],
                            "window_rmse": values["rmse"],
                            "window_r2": values["r2"],
                        }
                    )
                for slice_name, values in metrics_by_slice(prediction_rows, "missing_slice").items():
                    all_metric_rows.append(
                        {
                            "duration_seconds": duration,
                            "fold": fold,
                            "model": model_name,
                            "metric_slice": slice_name,
                            "window_count": len([r for r in prediction_rows if r["missing_slice"] == slice_name]),
                            "window_mae": values["mae"],
                            "window_rmse": values["rmse"],
                            "window_r2": values["r2"],
                        }
                    )
                duration_predictions.extend(prediction_rows)

                if model_name == "causal_tcn_linear":
                    progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}][{model_name}] writing curve samples")
                    curves = select_curve_sessions(prediction_rows)
                    write_csv(
                        curves,
                        output_dir / f"prediction_curves_{int(duration)}s_fold{fold}_{model_name}.csv",
                    )
            progress(f"[{duration:.0f}s][fold {fold + 1}/{n_folds}] fold complete")
        progress(f"[{duration:.0f}s] writing predictions")
        write_csv(duration_predictions, output_dir / f"predictions_{int(duration)}s.csv")
        progress(f"[{duration:.0f}s] complete in {time.perf_counter() - duration_start:.1f}s")

    progress("[final] writing metric tables and summary")
    metric_fieldnames = [
        "duration_seconds",
        "fold",
        "model",
        "metric_slice",
        "window_count",
        "window_mae",
        "window_rmse",
        "window_r2",
        "session_macro_mae",
        "session_macro_rmse",
        "raw_pa_id_group_macro_mae",
        "raw_pa_id_group_macro_rmse",
        "train_time_seconds",
        "inference_latency_ms_per_window",
        "parameter_count",
    ]
    write_csv(all_metric_rows, output_dir / "metrics_by_fold.csv", metric_fieldnames)
    write_csv(all_window_counts, output_dir / "window_counts.csv")
    summary = summarize_metric_rows(all_metric_rows, raw_session_count)
    write_json(summary, output_dir / "summary.json")
    write_markdown_summary(summary, output_dir / "README.md")
    progress("[final] done")
    return summary


def summarize_metric_rows(metric_rows: Sequence[Mapping[str, object]], raw_session_count: int) -> Dict[str, object]:
    primary = [r for r in metric_rows if not r.get("metric_slice")]
    grouped: Dict[Tuple[str, str], List[Mapping[str, object]]] = defaultdict(list)
    for row in primary:
        grouped[(str(row["duration_seconds"]), str(row["model"]))].append(row)
    summary_rows = []
    for (duration, model), rows in sorted(grouped.items()):
        item = {"duration_seconds": float(duration), "model": model, "folds": len(rows)}
        for metric in (
            "window_mae",
            "window_rmse",
            "window_r2",
            "session_macro_mae",
            "session_macro_rmse",
            "raw_pa_id_group_macro_mae",
            "raw_pa_id_group_macro_rmse",
            "train_time_seconds",
            "inference_latency_ms_per_window",
            "parameter_count",
        ):
            values = [float(row[metric]) for row in rows if row.get(metric) not in ("", None)]
            item[f"{metric}_mean"] = mean(values)
            item[f"{metric}_std"] = stdev(values)
        summary_rows.append(item)
    return {
        "declarations": {
            "public_snapshot_session_count": raw_session_count,
            "true_participant_identity_confirmed": False,
            "split_name": "raw_pa_id-group-disjoint split",
            "result_scope": "identifier-group-disjoint dynamic baseline",
            "static_personalization": False,
            "cross_dataset_or_unity_realtime_claim": False,
        },
        "summary_rows": summary_rows,
    }


def write_markdown_summary(summary: Mapping[str, object], path: Path) -> None:
    lines = [
        "# Ryu-Kim Dynamic Baseline",
        "",
        "This is a limited controlled dynamic-feature baseline. It does not train with static personal information and does not claim cross-dataset or Unity real-time deployment performance.",
        "",
        "## Required Declarations",
        "",
        "- Current public repository snapshot contains 428 sessions.",
        "- True participant identity is still unconfirmed.",
        "- Current results are an identifier-group-disjoint dynamic baseline using a raw_pa_id-group-disjoint split.",
        "- Static personalization is not included.",
        "- Results do not represent cross-dataset transfer or Unity real-time deployment performance.",
        "",
        "## Mean ± Std Across Folds",
        "",
        "| window | model | window MAE | window RMSE | window R2 | session MAE | group MAE | train s | latency ms/window | params |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["summary_rows"]:
        lines.append(
            f"| {row['duration_seconds']:.0f}s | {row['model']} | "
            f"{row['window_mae_mean']:.4f} ± {row['window_mae_std']:.4f} | "
            f"{row['window_rmse_mean']:.4f} ± {row['window_rmse_std']:.4f} | "
            f"{row['window_r2_mean']:.4f} ± {row['window_r2_std']:.4f} | "
            f"{row['session_macro_mae_mean']:.4f} ± {row['session_macro_mae_std']:.4f} | "
            f"{row['raw_pa_id_group_macro_mae_mean']:.4f} ± {row['raw_pa_id_group_macro_mae_std']:.4f} | "
            f"{row['train_time_seconds_mean']:.4f} | "
            f"{row['inference_latency_ms_per_window_mean']:.4f} | "
            f"{row['parameter_count_mean']:.0f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
