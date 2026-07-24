import argparse
import sys
from pathlib import Path


def _bootstrap_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "python" / "src"))
    return repo_root


REPO_ROOT = _bootstrap_path()

from openrdw_ai.ryu_kim_fms.dynamic_baseline import run_dynamic_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Train controlled Ryu-Kim dynamic baselines.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default="reports/ryu_kim_dynamic_baseline")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--durations", default="10,30,60")
    parser.add_argument("--max-missing-fraction", type=float, default=0.20)
    args = parser.parse_args()
    repo_root = Path(args.repo_root)
    durations = [float(item.strip()) for item in args.durations.split(",") if item.strip()]
    output_dir = repo_root / args.output_dir
    summary = run_dynamic_baseline(
        repo_root=repo_root,
        output_dir=output_dir,
        n_folds=args.folds,
        seed=args.seed,
        durations_seconds=durations,
        max_missing_fraction=args.max_missing_fraction,
    )
    print(f"wrote reports to {output_dir}")
    for row in summary["summary_rows"]:
        print(
            f"{row['duration_seconds']:.0f}s {row['model']}: "
            f"MAE={row['window_mae_mean']:.4f}±{row['window_mae_std']:.4f}, "
            f"RMSE={row['window_rmse_mean']:.4f}±{row['window_rmse_std']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

