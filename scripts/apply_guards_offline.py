"""Apply Stage-1 guards offline to a saved run JSON (no Gemini/Tavily)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.guard import apply_guard  # noqa: E402
from pipeline.nodes import derive_access_tier_from_paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline apply_guard on a run JSON")
    parser.add_argument(
        "--in",
        dest="infile",
        default="data/run_v2b.json",
        help="Input run JSON (unguarded)",
    )
    parser.add_argument(
        "--out",
        dest="outfile",
        default="data/run_v2b_guarded.json",
        help="Output run JSON (guarded)",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.infile)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.outfile)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    rows = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("input must be a JSON list of rows")

    out_rows: list[dict] = []
    for row in rows:
        r = dict(row)
        cli = r.get("api_type") == "cli_only"
        # pages_meta is metadata only; full page text not required for URL-hint guards
        r = apply_guard(r, cli_shortcircuit=cli, dbg=None, pages=[])
        r = derive_access_tier_from_paths(r)
        r["guard_applied"] = True
        out_rows.append(r)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[offline-guards] wrote {len(out_rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
