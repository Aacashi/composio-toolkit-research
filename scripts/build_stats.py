"""Rules-engine analysis: counts and cross-tabs from data/final.json → data/stats.json.

Not ML clustering. Every figure on the findings page must come from this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BUILD_ORDER = [
    "easy_win",
    "easy_but_paid",
    "needs_review",
    "needs_outreach",
    "blocked",
    "unknown",
]

BUILD_MEANING = {
    "easy_win": "self-serve credentials; engineer can start today",
    "easy_but_paid": "credentials need a card or paid plan first",
    "needs_review": "vendor must approve before production use",
    "needs_outreach": "sales or partner conversation required",
    "blocked": "no usable API or docs path for a toolkit",
    "unknown": "insufficient first-party evidence to decide",
}

UNBLOCKER_META = {
    "nobody": {
        "typical_wait": "none",
        "work_kind": "engineering — start today",
    },
    "composio_finance": {
        "typical_wait": "hours/days",
        "work_kind": "internal spend approval",
    },
    "vendor_human": {
        "typical_wait": "days/weeks",
        "work_kind": "vendor review, outside our control",
    },
    "composio_bd": {
        "typical_wait": "weeks/months",
        "work_kind": "business development",
    },
    "n_a": {
        "typical_wait": "n/a",
        "work_kind": "blocked or unclassified — no unlock path",
    },
}

BLOCKER_WHO = {
    "none": "nobody",
    "payment": "composio_finance",
    "vendor_review": "vendor_human",
    "partnership": "composio_bd",
    "no_api": "n_a",
    "no_docs": "n_a",
    "unknown": "n_a",
}

SCORED = ("access_tier", "auth_primary", "api_type", "mcp_exists")

FLAG_KEYS = (
    "no_docs_found",
    "no_auth_page_fetched",
    "no_pricing_page_fetched",
    "thin_content",
    "mcp_presence_no_url",
    "second_round_used",
    "second_round_preferred",
    "path_selection_applied",
    "retry_used",
)

# Hand-recorded version history (overall / field notes from research runs).
VERSION_HISTORY = [
    {
        "version": "v1",
        "overall": "26/40 (65.0%) on original 10-app key",
        "note": "Call1 search agent + Call2 extract; direct access_tier emit; live guards on.",
    },
    {
        "version": "v2",
        "overall": "27/40 (67.5%) on original 10-app key",
        "note": "Best single-key score; Call2 emits access_tier; optional second round.",
    },
    {
        "version": "v2b unguarded",
        "overall": "avg 58.3% across 3×10-app trials (26+23+21)/120",
        "note": "Path fields + derive access_tier; live guards off; 100-app run.",
    },
    {
        "version": "v2b postguard",
        "overall": "avg 60.8% across 3×10-app trials (29+22+22)/120",
        "note": "Post-loop: prefer second-round auth/path; wipe MCP presence without MCP URL.",
    },
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_gt_rows(path: Path) -> tuple[list[dict], list[str]]:
    doc = load_json(path)
    if isinstance(doc, list):
        # empty template — skip if no filled atoms
        filled = [r for r in doc if r.get("access_tier") not in (None, "")]
        return filled, list(SCORED)
    return doc["rows"], list(doc.get("scored_fields") or SCORED)


def count_field(rows: list[dict], field: str) -> list[dict]:
    c = Counter((r.get(field) or "unknown") for r in rows)
    n = len(rows)
    out = [{"value": k, "count": v, "pct_of_100": round(100.0 * v / n, 1)} for k, v in c.most_common()]
    return out


def crosstab(rows: list[dict], row_field: str, col_field: str, col_order: list[str] | None = None) -> dict:
    cols = col_order or sorted({(r.get(col_field) or "unknown") for r in rows})
    row_vals = sorted(
        {(r.get(row_field) or "unknown") for r in rows},
        key=lambda x: -sum(1 for r in rows if (r.get(row_field) or "unknown") == x),
    )
    matrix = []
    for rv in row_vals:
        entry = {"row": rv}
        for cv in cols:
            entry[cv] = sum(
                1
                for r in rows
                if (r.get(row_field) or "unknown") == rv and (r.get(col_field) or "unknown") == cv
            )
        entry["total"] = sum(entry[cv] for cv in cols)
        matrix.append(entry)
    return {"row_field": row_field, "col_field": col_field, "columns": cols, "rows": matrix}


def deep_accuracy(rows_by_name: dict[str, dict], gt_paths: list[Path]) -> dict:
    per_field = {f: {"correct": 0, "wrong": 0, "honestly_unknown": 0} for f in SCORED}
    misses = []
    labelled_apps = 0
    for path in gt_paths:
        if not path.exists():
            continue
        gt_rows, fields = load_gt_rows(path)
        if not gt_rows:
            continue
        for g in gt_rows:
            name = g["app_name"]
            pred = rows_by_name.get(name)
            if not pred:
                continue
            labelled_apps += 1
            for f in fields:
                exp = g.get(f)
                if exp in (None, ""):
                    continue
                act = pred.get(f) or "unknown"
                if act == "unknown" and exp != "unknown":
                    per_field[f]["honestly_unknown"] += 1
                    misses.append({"app": name, "field": f, "expected": exp, "actual": act, "bucket": "honestly_unknown"})
                elif act == exp:
                    per_field[f]["correct"] += 1
                else:
                    per_field[f]["wrong"] += 1
                    misses.append({"app": name, "field": f, "expected": exp, "actual": act, "bucket": "wrong"})

    # Per-field rates with bases
    fields_out = {}
    for f, d in per_field.items():
        base = d["correct"] + d["wrong"] + d["honestly_unknown"]
        fields_out[f] = {
            **d,
            "base": base,
            "correct_pct_of_base": round(100.0 * d["correct"] / base, 1) if base else 0.0,
        }
    total_c = sum(per_field[f]["correct"] for f in SCORED)
    total_w = sum(per_field[f]["wrong"] for f in SCORED)
    total_u = sum(per_field[f]["honestly_unknown"] for f in SCORED)
    total = total_c + total_w + total_u
    return {
        "sample_apps": labelled_apps,
        "sample_note": "Up to 30 apps across ground_truth.json + batch2 + batch3 (4 scored fields).",
        "fields": fields_out,
        "overall": {
            "correct": total_c,
            "wrong": total_w,
            "honestly_unknown": total_u,
            "base": total,
            "correct_pct_of_base": round(100.0 * total_c / total, 1) if total else 0.0,
        },
        "misses": misses,
    }


def build_stats(rows: list[dict], gt_paths: list[Path]) -> dict:
    n = len(rows)
    assert n == 100

    build = Counter((r.get("buildability") or "unknown") for r in rows)
    tier = Counter((r.get("access_tier") or "unknown") for r in rows)
    unblock = Counter((r.get("unblocker") or "n_a") for r in rows)
    btype = Counter((r.get("blocker_type") or "unknown") for r in rows)

    # A auth
    auth_table = count_field(rows, "auth_primary")

    # B category x rollup
    cats = []
    seen = set()
    for r in rows:
        c = r.get("category") or "unknown"
        if c not in seen:
            seen.add(c)
            cats.append(c)
    rollup_cols = ["open", "paid", "gated", "unknown"]
    cat_rows = []
    for cat in cats:
        sub = [r for r in rows if (r.get("category") or "unknown") == cat]
        entry = {"category": cat}
        for col in rollup_cols:
            entry[col] = sum(1 for r in sub if (r.get("access_tier_rollup") or "unknown") == col)
        entry["total"] = len(sub)
        entry["gated_share"] = round(entry["gated"] / entry["total"], 3) if entry["total"] else 0
        entry["open_share"] = round(entry["open"] / entry["total"], 3) if entry["total"] else 0
        cat_rows.append(entry)
    most_gated = max(cat_rows, key=lambda x: (x["gated_share"], x["gated"]))
    most_open = max(cat_rows, key=lambda x: (x["open_share"], x["open"]))

    # B2 category × buildability (10 apps each → percentages)
    cat_build_rows = []
    for cat in cats:
        sub = [r for r in rows if (r.get("category") or "unknown") == cat]
        total = len(sub)
        entry: dict = {"category": cat, "total": total}
        for b in BUILD_ORDER:
            cnt = sum(1 for r in sub if (r.get("buildability") or "unknown") == b)
            entry[b] = cnt
            entry[f"{b}_pct"] = round(100.0 * cnt / total, 1) if total else 0.0
        cat_build_rows.append(entry)

    # B3 business_type × buildability (Call-1 prior clusters)
    btypes: list[str] = []
    bt_seen: set[str] = set()
    for r in rows:
        bt = r.get("business_type") or "unknown"
        if bt not in bt_seen:
            bt_seen.add(bt)
            btypes.append(bt)
    bt_build_rows = []
    for bt in btypes:
        sub = [r for r in rows if (r.get("business_type") or "unknown") == bt]
        total = len(sub)
        entry = {"business_type": bt, "total": total}
        for b in BUILD_ORDER:
            cnt = sum(1 for r in sub if (r.get("buildability") or "unknown") == b)
            entry[b] = cnt
            entry[f"{b}_pct"] = round(100.0 * cnt / total, 1) if total else 0.0
        bt_build_rows.append(entry)
    bt_build_rows.sort(key=lambda x: -x["total"])

    # C blockers
    blocker_table = []
    for bt, cnt in btype.most_common():
        blocker_table.append(
            {
                "blocker_type": bt,
                "count": cnt,
                "who_acts": BLOCKER_WHO.get(bt, "n_a"),
                "pct_of_100": round(100.0 * cnt / n, 1),
            }
        )
    most_blocker = next((b for b in blocker_table if b["blocker_type"] != "none"), blocker_table[0])

    # D buildability
    build_table = []
    for b in BUILD_ORDER:
        build_table.append(
            {
                "verdict": b,
                "count": build.get(b, 0),
                "pct_of_100": round(100.0 * build.get(b, 0) / n, 1),
                "meaning": BUILD_MEANING[b],
            }
        )

    # E auth x buildability
    auth_x_build = crosstab(rows, "auth_primary", "buildability", BUILD_ORDER)
    api_key_total = sum(1 for r in rows if r.get("auth_primary") == "api_key")
    api_key_not_easy = sum(
        1 for r in rows if r.get("auth_primary") == "api_key" and r.get("buildability") != "easy_win"
    )
    oauth_builds = {
        (r.get("buildability") or "unknown")
        for r in rows
        if r.get("auth_primary") == "oauth2"
    }

    # F queues
    queue_table = []
    for u in ("nobody", "composio_finance", "vendor_human", "composio_bd", "n_a"):
        meta = UNBLOCKER_META[u]
        queue_table.append(
            {
                "who_must_act": u,
                "count": unblock.get(u, 0),
                "pct_of_100": round(100.0 * unblock.get(u, 0) / n, 1),
                "typical_wait": meta["typical_wait"],
                "work_kind": meta["work_kind"],
            }
        )
    eng = unblock.get("nobody", 0)
    bd_ish = unblock.get("composio_bd", 0) + unblock.get("vendor_human", 0) + unblock.get("composio_finance", 0)

    # G secondary
    def yn_counts(field: str) -> dict:
        c = Counter((r.get(field) or "unknown") for r in rows)
        return {k: c.get(k, 0) for k in ("yes", "no", "unknown")}

    mcp_c = Counter((r.get("mcp_exists") or "unknown") for r in rows)
    mcp_present = sum(
        1
        for r in rows
        if r.get("mcp_exists") in ("official_open", "official_gated", "community")
    )
    mcp_present_not_easy = sum(
        1
        for r in rows
        if r.get("mcp_exists") in ("official_open", "official_gated", "community")
        and r.get("buildability") != "easy_win"
    )

    # H coverage
    flag_counts = {k: sum(1 for r in rows if k in (r.get("flags") or [])) for k in FLAG_KEYS}
    two_paths = sum(1 for r in rows if r.get("integration_paths") == "two_paths")

    # I deep (pooled + per-trial)
    by_name = {r["app_name"]: r for r in rows}
    deep = deep_accuracy(by_name, gt_paths)
    trials = []
    trial_specs = [
        ("trial1", "Original 10-app key", gt_paths[0]),
        ("trial2", "Random batch 2", gt_paths[1]),
        ("trial3", "Random batch 3", gt_paths[2]),
    ]
    for tid, label, path in trial_specs:
        if not path.exists():
            continue
        t = deep_accuracy(by_name, [path])
        trials.append(
            {
                "id": tid,
                "label": label,
                "path": str(path.name),
                "overall": t["overall"],
                "fields": {
                    f: {
                        "correct": t["fields"][f]["correct"],
                        "base": t["fields"][f]["base"],
                        "correct_pct_of_base": t["fields"][f]["correct_pct_of_base"],
                    }
                    for f in SCORED
                },
            }
        )
    deep["trials"] = trials
    # Average of three trial overall %
    if trials:
        deep["trial_avg_pct"] = round(
            sum(t["overall"]["correct_pct_of_base"] for t in trials) / len(trials), 1
        )

    # Pick one concrete sample miss for the page narrative (prefer access_tier wrong)
    sample = None
    for m in deep["misses"]:
        if m["field"] == "access_tier" and m["bucket"] == "wrong":
            sample = m
            break
    if sample is None and deep["misses"]:
        sample = deep["misses"][0]
    deep["sample_miss"] = sample

    # J shallow
    agree = Counter((r.get("agrees_with_composio") or "n_a") for r in rows)

    # apps for defeated / full table helpers
    unknown_tier_apps = sorted(
        r["app_name"] for r in rows if (r.get("access_tier") or "unknown") == "unknown"
    )
    docs_none = sorted(
        r["app_name"]
        for r in rows
        if r.get("docs_access") == "none_found" or "no_docs_found" in (r.get("flags") or [])
    )

    headline = {
        "easy_win": build.get("easy_win", 0),
        "needs_review": build.get("needs_review", 0),
        "needs_outreach": build.get("needs_outreach", 0),
        "blocked": build.get("blocked", 0),
        "easy_but_paid": build.get("easy_but_paid", 0),
        "buildability_unknown": build.get("unknown", 0),
        "access_tier_unknown": tier.get("unknown", 0),
        "most_common_blocker": most_blocker["blocker_type"],
        "most_common_blocker_count": most_blocker["count"],
    }

    return {
        "n": n,
        "description": "Rules-engine counts from final.json — not ML clustering.",
        "headline": headline,
        "A_auth_dominates": auth_table,
        "B_category_rollup": {
            "rows": cat_rows,
            "columns": rollup_cols,
            "most_gated_category": most_gated["category"],
            "most_gated_detail": f"{most_gated['gated']}/{most_gated['total']}",
            "most_open_category": most_open["category"],
            "most_open_detail": f"{most_open['open']}/{most_open['total']}",
        },
        "B2_category_buildability": {
            "rows": cat_build_rows,
            "verdicts": BUILD_ORDER,
            "note": "10 apps per product category; percentages within each category.",
        },
        "B3_business_type_buildability": {
            "rows": bt_build_rows,
            "verdicts": BUILD_ORDER,
            "note": "Call-1 business_type prior vs rules-engine buildability.",
        },
        "C_blockers": blocker_table,
        "D_buildability": build_table,
        "E_auth_x_buildability": {
            **auth_x_build,
            "api_key_total": api_key_total,
            "api_key_not_easy_win": api_key_not_easy,
            "oauth2_buildability_span": sorted(oauth_builds),
            "oauth2_distinct_buildability_count": len(oauth_builds),
        },
        "F_queues": {
            "rows": queue_table,
            "engineering_ready_nobody": eng,
            "non_engineering_queues": bd_ish,
            "takeaway": (
                f"{eng} of 100 are engineering-ready (nobody). "
                f"{bd_ish} of 100 wait on vendor review, finance, or BD. "
                f"{unblock.get('n_a', 0)} of 100 are n_a (blocked/unknown)."
            ),
        },
        "G_secondary": {
            "has_openapi_spec": yn_counts("has_openapi_spec"),
            "needs_instance_url": yn_counts("needs_instance_url"),
            "has_webhooks": yn_counts("has_webhooks"),
            "mcp_exists": {k: mcp_c.get(k, 0) for k in ("official_open", "official_gated", "community", "none", "unknown")},
            "mcp_present": mcp_present,
            "mcp_present_not_easy_win": mcp_present_not_easy,
        },
        "H_coverage": {
            "access_tier_unknown": tier.get("unknown", 0),
            "access_tier_unknown_apps": unknown_tier_apps,
            "auth_primary_unknown": sum(1 for r in rows if (r.get("auth_primary") or "unknown") == "unknown"),
            "docs_access_none_found": len(docs_none),
            "docs_none_apps": docs_none,
            "flag_counts": flag_counts,
            "integration_paths_two_paths": two_paths,
        },
        "I_deep_verification": deep,
        "J_shallow_composio": {
            "yes": agree.get("yes", 0),
            "disagrees": agree.get("disagrees", 0),
            "n_a": agree.get("n_a", 0),
            "note": "Independent auth_primary check vs Composio catalog — never averaged with deep verification.",
        },
        "K_version_history": VERSION_HISTORY,
        "full_table_sort": BUILD_ORDER,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build stats.json from final.json")
    parser.add_argument("--in", dest="infile", default="data/final.json")
    parser.add_argument("--out", dest="outfile", default="data/stats.json")
    args = parser.parse_args(argv)

    in_path = Path(args.infile)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.outfile)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    rows = load_json(in_path)
    gt_paths = [
        ROOT / "ground_truth.json",
        ROOT / "data" / "ground_truth_batch2.json",
        ROOT / "data" / "ground_truth_batch3.json",
    ]
    stats = build_stats(rows, gt_paths)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[stats] wrote {out_path}")
    h = stats["headline"]
    print(
        f"[stats] headline easy_win={h['easy_win']} needs_review={h['needs_review']} "
        f"needs_outreach={h['needs_outreach']} blocked={h['blocked']} "
        f"tier_unknown={h['access_tier_unknown']} blocker={h['most_common_blocker']}"
    )
    d = stats["I_deep_verification"]["overall"]
    print(
        f"[stats] deep overall correct={d['correct']} wrong={d['wrong']} "
        f"honestly_unknown={d['honestly_unknown']} base={d['base']} ({d['correct_pct_of_base']}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
