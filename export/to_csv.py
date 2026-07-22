"""Flatten run_vN.json to wide CSV for human review."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Column order: identity, atoms, derived, evidence/confidence pairs, audit
BASE_COLS = [
    "app_name",
    "category",
    "one_liner",
    "business_type",
    "business_type_confirmed",
    "docs_access",
    "docs_location",
    "auth_primary",
    "auth_secondary",
    "auth_detail",
    "access_tier",
    "access_cost_note",
    "api_type",
    "api_breadth",
    "has_openapi_spec",
    "needs_instance_url",
    "has_webhooks",
    "rate_limit_note",
    "mcp_exists",
    "mcp_access",
    "buildability",
    "blocker",
    "blocker_type",
    "unblocker",
    "wait_class",
    "composio_supports",
    "composio_auth_scheme",
    "agrees_with_composio",
    "human_verdict",
    "human_notes",
    "flags",
    "sources_fetched",
    "first_party_domains",
    "backup_links",
    "notes",
    "run_id",
]

EVIDENCE_FIELDS = [
    "docs_access",
    "docs_location",
    "auth_primary",
    "access_tier",
    "api_type",
    "api_breadth",
    "has_openapi_spec",
    "needs_instance_url",
    "has_webhooks",
    "mcp_exists",
    "mcp_access",
]


def flatten_row(row: dict) -> dict:
    out: dict = {}
    evidence = row.get("evidence") or {}
    confidence = row.get("confidence") or {}

    for col in BASE_COLS:
        val = row.get(col, "")
        if col in ("auth_secondary", "flags", "sources_fetched", "first_party_domains"):
            if isinstance(val, list):
                val = "; ".join(str(x) for x in val)
        elif col == "backup_links":
            if isinstance(val, list):
                val = "; ".join(
                    f"{b.get('url','')}|{b.get('why','')}" if isinstance(b, dict) else str(b)
                    for b in val
                )
        elif isinstance(val, bool):
            val = str(val).lower()
        elif val is None:
            val = ""
        out[col] = val

    # adjacent triples: field, field_evidence, field_confidence
    flat: dict = {}
    for col in BASE_COLS:
        flat[col] = out.get(col, "")
        if col in EVIDENCE_FIELDS:
            flat[f"{col}_evidence"] = evidence.get(col, "")
            flat[f"{col}_confidence"] = confidence.get(col, "")
    return flat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", default=None, help="Output CSV path")
    args = parser.parse_args(argv)

    run_path = Path(args.run)
    if not run_path.is_absolute():
        run_path = ROOT / "data" / run_path
    out_path = Path(args.out) if args.out else run_path.with_suffix(".csv")
    if not out_path.is_absolute() and args.out:
        out_path = ROOT / "data" / out_path

    rows = json.loads(run_path.read_text(encoding="utf-8"))
    flat_rows = [flatten_row(r) for r in rows]
    if not flat_rows:
        print("empty run")
        return 1

    fieldnames: list[str] = []
    seen = set()
    for r in flat_rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(flat_rows)
    print(f"wrote {out_path} ({len(flat_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
