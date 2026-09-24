"""Generate only the two additive analytics feeds; never loads or resets cloud tables."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.cymbal_store_ops.reporting_fixtures import generate_report_tables  # noqa: E402
from data.generate import generate_all  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "report_out")
    output = parser.parse_args().out
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in generate_report_tables(generate_all()).items():
        (output / f"{name}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
