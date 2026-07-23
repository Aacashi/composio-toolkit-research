"""Stage 2 — derive verdict fields from a Stage 1 run or ground truth.

  python scripts/derive.py --run run_v1.json
  → data/run_v1_derived.json

  python scripts/derive.py --gt
  → updates data/ground_truth.json inplace
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.verdict import derive_verdict  # noqa: E402

DATA = ROOT / "data"


def derive_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        atoms_present = any(
            row.get(f) not in (None, "")
            for f in ("access_tier", "auth_primary", "api_type", "docs_access")
        )
        if not atoms_present:
            out.append(row)
            continue
        out.append(derive_verdict(dict(row)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 2 derivation")
    parser.add_argument("--run", default=None, help="run_vN.json under data/")
    parser.add_argument(
        "--gt",
        action="store_true",
        help="Apply derive_verdict to data/ground_truth.json inplace",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output path (default: run_vN_derived.json)",
    )
    args = parser.parse_args(argv)

    if args.gt:
        path = DATA / "ground_truth.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        updated = derive_rows(rows)
        path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"derived GT inplace: {path} ({len(updated)} rows)")
        return 0

    if not args.run:
        parser.error("provide --run run_vN.json or --gt")

    run_path = Path(args.run)
    if not run_path.is_absolute():
        run_path = DATA / run_path
    rows = json.loads(run_path.read_text(encoding="utf-8"))
    updated = derive_rows(rows)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = DATA / out_path
    else:
        stem = run_path.stem
        if stem.endswith("_derived"):
            out_path = run_path
        else:
            out_path = run_path.with_name(f"{stem}_derived.json")

    out_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path} ({len(updated)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
