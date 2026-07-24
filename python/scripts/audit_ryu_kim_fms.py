import argparse
import sys
from pathlib import Path


def _bootstrap_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "python" / "src"))


_bootstrap_path()

from openrdw_ai.ryu_kim_fms.audit import audit_dataset, write_json, write_markdown_report
from openrdw_ai.ryu_kim_fms.schema import DatasetConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the Ryu-Kim FMS dataset without modifying raw data.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    config = DatasetConfig(repo_root=Path(args.repo_root))
    audit = audit_dataset(config)
    write_json(audit, config.resolve(config.audit_json_path))
    write_markdown_report(audit, config.resolve(config.report_path))
    print(f"wrote {config.resolve(config.audit_json_path)}")
    print(f"wrote {config.resolve(config.report_path)}")
    if audit["blocked_for_formal_preprocessing"]:
        print("formal preprocessing/training gate: BLOCKED due to unresolved dataset ambiguities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

