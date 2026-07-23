"""Prepare data/final.json from run_v2b_postguard.json (rules-engine input).

- Verify Magento (repair only if truly duplicated)
- Split notes vs debug_contradictions
- Coerce out-of-enum / odd path pairs; fill missing meta
- Run derive_verdict so every row has buildability / blocker / unblocker / rollup
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.verdict import derive_verdict  # noqa: E402
from schema import ALLOWED_VALUES, PATH_ACCESS_VALUES  # noqa: E402

SPLIT_MARK = " | contradiction "


def split_notes(notes: str) -> tuple[str, list[str]]:
    text = notes or ""
    if SPLIT_MARK not in text:
        # Also catch leading "contradiction " without prior prose
        if text.strip().lower().startswith("contradiction "):
            parts = [p.strip() for p in text.split(" | ") if p.strip()]
            return "", parts
        return text.strip(), []
    head, rest = text.split(SPLIT_MARK, 1)
    chunks = [SPLIT_MARK.strip()[2:] + " " + rest]  # "contradiction ..."
    # Further | contradiction segments already inside rest
    more = []
    for piece in rest.split(" | "):
        piece = piece.strip()
        if not piece:
            continue
        if piece.lower().startswith("contradiction "):
            more.append(piece)
        elif more:
            more[-1] = more[-1] + " | " + piece
        else:
            more.append("contradiction " + piece if not piece.lower().startswith("contradiction") else piece)
    # Prefer structured split of rest on " | "
    parts = []
    buf = "contradiction " + rest if not rest.lower().startswith("contradiction") else rest
    for piece in buf.split(" | "):
        piece = piece.strip()
        if piece:
            parts.append(piece)
    return head.strip(), parts


def coerce_path_fields(row: dict) -> list[str]:
    """Return list of coerce flags applied."""
    flags = []
    priv = row.get("private_path_access")
    pub = row.get("public_path_access")
    paths = row.get("integration_paths") or "unknown"

    for field in ("private_path_access", "public_path_access"):
        val = row.get(field)
        if val in (None, ""):
            row[field] = "unknown" if field.startswith("private") else "n_a"
            flags.append(f"coerced_empty_{field}")
            continue
        if val not in PATH_ACCESS_VALUES:
            row[field] = "unknown"
            flags.append(f"coerced_invalid_{field}")

    priv = row.get("private_path_access")
    pub = row.get("public_path_access")
    paths = row.get("integration_paths") or "unknown"

    # one_path with private n_a but public concrete: move public → private
    if paths == "one_path" and priv in ("n_a", "unknown", None) and pub not in (
        None,
        "",
        "n_a",
        "unknown",
    ):
        row["private_path_access"] = pub
        row["public_path_access"] = "n_a"
        flags.append("coerced_one_path_public_to_private")

    # unknown paths with only public set: leave but mark
    if paths == "unknown" and pub not in (None, "", "n_a", "unknown") and priv in (
        "n_a",
        "unknown",
        None,
    ):
        # Cannot invent integration_paths; coerce dangling public to unknown
        row["public_path_access"] = "unknown"
        flags.append("coerced_dangling_public_path")

    if row.get("integration_paths") not in ALLOWED_VALUES["integration_paths"]:
        row["integration_paths"] = "unknown"
        flags.append("coerced_integration_paths")

    return flags


def prepare_row(row: dict) -> dict:
    r = dict(row)
    # Magento: if notes somehow duplicated, dedupe later via key integrity only

    notes, contradictions = split_notes(r.get("notes") or "")
    r["notes"] = notes
    r["debug_contradictions"] = contradictions

    coerce_flags = coerce_path_fields(r)
    flags = list(r.get("flags") or [])
    for f in coerce_flags:
        if f not in flags:
            flags.append(f)
    r["flags"] = flags

    if r.get("guard_applied") is None:
        r["guard_applied"] = False
    if r.get("pages_meta") is None:
        r["pages_meta"] = []
    if r.get("post_loop_guards") is None:
        r["post_loop_guards"] = False

    # Re-derive access_tier from paths after coerce (simple mirror of nodes logic)
    paths = r.get("integration_paths") or "unknown"
    private = r.get("private_path_access") or "unknown"
    public = r.get("public_path_access") or "n_a"
    if paths == "two_paths":
        r["access_tier"] = public if public not in (None, "", "n_a") else "unknown"
    elif paths == "one_path":
        r["access_tier"] = private if private not in (None, "", "n_a") else "unknown"
    else:
        # keep existing access_tier if already set and paths unknown
        if r.get("access_tier") in (None, ""):
            r["access_tier"] = "unknown"

    r = derive_verdict(r)
    required = ("buildability", "blocker_type", "unblocker", "access_tier_rollup")
    for k in required:
        if r.get(k) in (None, ""):
            raise RuntimeError(f"{r.get('app_name')}: missing derived {k}")
    return r


def magento_needs_repair(raw_text: str) -> bool:
    idx = raw_text.find("Magento (Adobe Commerce)")
    if idx < 0:
        return False
    snippet = raw_text[idx : idx + 4000]
    return snippet.count('"flags"') > 1 or snippet.count('"sources_fetched"') > 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare final.json for findings rules engine")
    parser.add_argument("--in", dest="infile", default="data/run_v2b_postguard.json")
    parser.add_argument("--out", dest="outfile", default="data/final.json")
    parser.add_argument("--site-copy", default="site/data.json")
    args = parser.parse_args(argv)

    in_path = Path(args.infile)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.outfile)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    site_path = Path(args.site_copy)
    if not site_path.is_absolute():
        site_path = ROOT / site_path

    raw_text = in_path.read_text(encoding="utf-8")
    rows = json.loads(raw_text)
    if not isinstance(rows, list) or len(rows) != 100:
        raise SystemExit(f"expected 100-row list, got {type(rows)} len={getattr(rows, '__len__', lambda: '?')()}")

    names = [r["app_name"] for r in rows]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate app_name in input")

    if magento_needs_repair(raw_text):
        print("[prep] Magento duplication detected — json.load already collapsed keys; no structural rewrite needed")
    else:
        print("[prep] Magento: clean (no duplicate blocks)")

    out_rows = [prepare_row(r) for r in rows]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(out_rows, indent=2, ensure_ascii=False)
    out_path.write_text(payload, encoding="utf-8")
    site_path.write_text(payload, encoding="utf-8")

    # sanity
    rollups = {}
    for r in out_rows:
        rollups[r["access_tier_rollup"]] = rollups.get(r["access_tier_rollup"], 0) + 1
    print(f"[prep] wrote {len(out_rows)} rows -> {out_path}")
    print(f"[prep] copied -> {site_path}")
    print(f"[prep] access_tier_rollup: {rollups}")
    n_contra = sum(1 for r in out_rows if r.get("debug_contradictions"))
    print(f"[prep] rows with debug_contradictions: {n_contra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
