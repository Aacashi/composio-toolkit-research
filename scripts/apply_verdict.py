"""Apply derive_verdict() to ground_truth.json (atoms → verdict bundle).

Human fills atoms only. This script is the only writer of buildability /
unblocker / wait_class / blocker_type / blocker on the GT file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.verdict import derive_verdict  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gt",
        default=str(ROOT / "data" / "ground_truth.json"),
        help="Path to ground_truth.json",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        default=True,
        help="Overwrite GT file (default)",
    )
    args = parser.parse_args(argv)
    path = Path(args.gt)
    rows = json.loads(path.read_text(encoding="utf-8"))

    updated = []
    skipped = 0
    for row in rows:
        # Skip rows with no atomic access_tier/api_type filled yet
        atoms_present = any(
            row.get(f) not in (None, "")
            for f in ("access_tier", "auth_primary", "api_type", "docs_access")
        )
        if not atoms_present:
            skipped += 1
            updated.append(row)
            continue
        updated.append(derive_verdict(dict(row)))

    path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"applied derive_verdict to {path}")
    print(f"rows={len(updated)} skipped_empty_atoms={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
