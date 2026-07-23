"""Apply post-loop guardrails to a saved run JSON (no Gemini/Tavily/cache).

1) Prefer second-round values from contradiction notes (auth + path fields).
2) Wipe MCP presence claims when no MCP-related URL was fetched.
Then re-derive access_tier from path fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.guard import apply_post_loop_guards  # noqa: E402
from pipeline.nodes import derive_access_tier_from_paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline post-loop guards on a run JSON")
    parser.add_argument("--in", dest="infile", default="data/run_v2b.json")
    parser.add_argument("--out", dest="outfile", default="data/run_v2b_postguard.json")
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
    n_sr = n_mcp = 0
    for row in rows:
        r = dict(row)
        before_auth = r.get("auth_primary")
        before_mcp = r.get("mcp_exists")
        r = apply_post_loop_guards(r, dbg=None)
        r = derive_access_tier_from_paths(r)
        r["post_loop_guards"] = True
        flags = r.get("flags") or []
        if "second_round_preferred" in flags and before_auth != r.get("auth_primary"):
            n_sr += 1
        if "mcp_presence_no_url" in flags and before_mcp != r.get("mcp_exists"):
            n_mcp += 1
        out_rows.append(r)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[post-loop] wrote {len(out_rows)} rows -> {out_path}")
    print(f"[post-loop] auth/path second-round fixes: {n_sr}")
    print(f"[post-loop] mcp presence wiped (no URL): {n_mcp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
