import argparse
import sys
from pathlib import Path


def _bootstrap_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "python" / "src"))


_bootstrap_path()

from openrdw_ai.ryu_kim_fms.identity import run_identity_resolution
from openrdw_ai.ryu_kim_fms.schema import DatasetConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Second-round Ryu-Kim identity/session/missingness audit.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    config = DatasetConfig(repo_root=Path(args.repo_root))
    outputs = run_identity_resolution(config)
    print(f"sessions: {len(outputs['manifest'])}")
    print(f"identity candidates: {len(outputs['identity_candidates'])}")
    print(f"duplicate groups: {len(outputs['duplicate_report'])}")
    print(f"missingness rows: {len(outputs['missing_rows'])}")
    print(f"gate status written to {config.output_dir_abs / 'gate_status.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

