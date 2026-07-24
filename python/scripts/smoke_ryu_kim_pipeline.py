import argparse
import sys
from pathlib import Path


def _bootstrap_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "python" / "src"))


_bootstrap_path()

from openrdw_ai.ryu_kim_fms.io import discover_csv_files, read_all_rows
from openrdw_ai.ryu_kim_fms.preprocess import Preprocessor, assert_scaler_fit_only_on_train
from openrdw_ai.ryu_kim_fms.schema import DatasetConfig, WINDOW_DURATIONS_SECONDS
from openrdw_ai.ryu_kim_fms.split import participant_disjoint_split, validate_participant_disjoint
from openrdw_ai.ryu_kim_fms.window import assert_no_future_frames, generate_causal_windows


def main() -> int:
    parser = argparse.ArgumentParser(description="Small pipeline smoke test; no training is run.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--max-windows-per-duration", type=int, default=16)
    args = parser.parse_args()

    config = DatasetConfig(repo_root=Path(args.repo_root))
    files = discover_csv_files(config.raw_dir_abs)[: args.max_files]
    rows = read_all_rows(files)
    participants = sorted({str(r["participant_id"]) for r in rows if r["participant_id"]})
    splits = participant_disjoint_split(
        participants,
        config.train_ratio,
        config.validation_ratio,
        config.test_ratio,
        config.split_seed,
    )
    validate_participant_disjoint(splits)

    for duration in WINDOW_DURATIONS_SECONDS:
        all_windows = list(generate_causal_windows(rows, duration, config.expected_interval_seconds))
        train_participant_set = set(splits["train"])
        train_windows = [w for w in all_windows if w["participant_id"] in train_participant_set]
        other_windows = [w for w in all_windows if w["participant_id"] not in train_participant_set]
        windows = (train_windows[: args.max_windows_per_duration // 2] + other_windows[: args.max_windows_per_duration // 2])
        if not windows:
            print(f"{duration:.0f}s: skipped, no windows in smoke subset")
            continue
        for window in windows:
            assert_no_future_frames(window)
        preprocessor = Preprocessor().fit(all_windows, splits["train"])
        assert_scaler_fit_only_on_train(preprocessor, splits["train"])
        batch = [preprocessor.transform_window(w) for w in windows[:4]]
        dynamic_shape = (len(batch), len(batch[0]["x_dynamic"]), len(batch[0]["x_dynamic"][0]))
        static_shape = (len(batch), len(batch[0]["x_static"]))
        target_shape = (len(batch),)
        print(
            f"{duration:.0f}s window smoke: x_dynamic={dynamic_shape}, "
            f"x_static={static_shape}, y={target_shape}"
        )
    print("smoke test completed; no model training was run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
