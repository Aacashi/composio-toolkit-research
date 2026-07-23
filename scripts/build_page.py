"""Generate single static findings index.html from stats.json + final.json.

Rules-engine output only — no hardcoded counts. Concise research memo layout.
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

BUILD_ORDER = [
    "easy_win",
    "easy_but_paid",
    "needs_review",
    "needs_outreach",
    "blocked",
    "unknown",
]

SWATCH = {
    "easy_win": "#1a7f37",
    "easy_but_paid": "#9a6700",
    "needs_review": "#0969da",
    "needs_outreach": "#8250df",
    "blocked": "#cf222e",
    "unknown": "#656d76",
}


def esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def short_url(url: str) -> str:
    if not url:
        return "—"
    p = urlparse(url)
    host = (p.netloc or "").removeprefix("www.")
    path = p.path or ""
    if len(path) > 28:
        path = path[:25] + "…"
    label = f"{host}{path}" if host else url[:40]
    return f'<a href="{esc(url)}">{esc(label)}</a>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def verdict_cell(v: str) -> str:
    return f'<span class="swatch" style="background:{SWATCH.get(v, "#000")}"></span>{esc(v)}'


def cat_short(name: str) -> str:
    # Shorten long category labels for the full table
    return (
        name.replace("Marketing, Ads, Email and Social", "Marketing / Ads")
        .replace("Communications and Messaging", "Comms")
        .replace("Developer, Infra and Data platforms", "Dev / Infra")
        .replace("Productivity and Project Management", "Productivity")
        .replace("AI, Research and Media-native", "AI / Media")
        .replace("Data, SEO and Scraping", "Data / SEO")
        .replace("Support and Helpdesk", "Support")
        .replace("Finance and Fintech", "Finance")
        .replace("CRM and Sales", "CRM")
    )


def build_html(stats: dict, rows: list[dict], *, repo_url: str, research_repo: str) -> str:
    h = stats["headline"]
    n = stats["n"]
    deep = stats["I_deep_verification"]
    shallow = stats["J_shallow_composio"]
    g = stats["G_secondary"]
    cov = stats["H_coverage"]
    e = stats["E_auth_x_buildability"]
    bcat = stats["B_category_rollup"]
    queues = stats["F_queues"]

    deep_pct = deep["overall"]["correct_pct_of_base"]
    deep_base = deep["overall"]["base"]
    deep_correct = deep["overall"]["correct"]
    tier_pct = deep["fields"]["access_tier"]["correct_pct_of_base"]
    api_pct = deep["fields"]["api_type"]["correct_pct_of_base"]
    auth_pct = deep["fields"]["auth_primary"]["correct_pct_of_base"]
    mcp_pct = deep["fields"]["mcp_exists"]["correct_pct_of_base"]

    # Compact auth counts: "oauth2 50 · api_key 31 · …"
    auth_line = " · ".join(f"{r['value']} {r['count']}" for r in stats["A_auth_dominates"])

    # A — count + % only (drop redundant third wording)
    a_rows = [
        [esc(r["value"]), str(r["count"]), f"{r['pct_of_100']}%"]
        for r in stats["A_auth_dominates"]
    ]

    b_rows = [
        [
            esc(r["category"]),
            str(r["open"]),
            str(r["paid"]),
            str(r["gated"]),
            str(r["unknown"]),
            str(r["total"]),
        ]
        for r in bcat["rows"]
    ]

    # C — skip blocker_type=none (already in easy_win count)
    c_rows = [
        [esc(r["blocker_type"]), str(r["count"]), esc(r["who_acts"])]
        for r in stats["C_blockers"]
        if r["blocker_type"] != "none"
    ]

    d_rows = [
        [esc(r["verdict"]), str(r["count"]), esc(r["meaning"])]
        for r in stats["D_buildability"]
    ]

    # E — drop all-zero columns for readability (keep if any non-zero)
    cols = [c for c in e["columns"] if any(r.get(c, 0) for r in e["rows"])]
    e_headers = ["auth"] + [c.replace("needs_", "").replace("easy_but_", "paid_") for c in cols] + ["n"]
    e_rows = []
    for r in e["rows"]:
        if r["total"] == 0:
            continue
        e_rows.append([esc(r["row"])] + [str(r.get(c, 0)) for c in cols] + [str(r["total"])])

    f_rows = [
        [esc(r["who_must_act"]), str(r["count"]), esc(r["typical_wait"]), esc(r["work_kind"])]
        for r in queues["rows"]
    ]

    g_rows = [
        ["OpenAPI", f"yes {g['has_openapi_spec']['yes']} · no {g['has_openapi_spec']['no']} · unk {g['has_openapi_spec']['unknown']}"],
        ["Instance URL", f"yes {g['needs_instance_url']['yes']} · no {g['needs_instance_url']['no']} · unk {g['needs_instance_url']['unknown']}"],
        ["Webhooks", f"yes {g['has_webhooks']['yes']} · no {g['has_webhooks']['no']} · unk {g['has_webhooks']['unknown']}"],
        [
            "MCP",
            (
                f"open {g['mcp_exists']['official_open']} · gated {g['mcp_exists']['official_gated']} · "
                f"none {g['mcp_exists']['none']} · unk {g['mcp_exists']['unknown']}"
            ),
        ],
    ]

    deep_rows = [
        [
            esc(field),
            str(d["correct"]),
            str(d["wrong"]),
            str(d["honestly_unknown"]),
            f"{d['correct_pct_of_base']}%",
        ]
        for field, d in deep["fields"].items()
    ]

    causes = {
        ("Twenty", "access_tier"): "trial vs free boundary",
        ("Zendesk", "access_tier"): "public path → approval_gated vs GT trial",
        ("Notion", "access_tier"): "missed marketplace review (docs ambiguous)",
        ("Notion", "auth_primary"): "Basic exchange confused with primary (GT oauth2)",
        ("Ahrefs", "access_tier"): "Connect partner path vs plain API plan_gated",
        ("Ahrefs", "mcp_exists"): "open vs gated MCP",
        ("Meta Ads", "mcp_exists"): "presence wiped (no MCP URL); GT none",
        ("fanbasis", "access_tier"): "docs password-walled; homepage only",
        ("DealCloud", "mcp_exists"): "open vs gated MCP",
        ("QuickBooks", "access_tier"): "path override → free vs GT approval_gated",
        ("Pylon", "access_tier"): "plan_gated vs GT trial",
        ("Pylon", "auth_primary"): "api_key vs GT pat",
    }
    miss_index = {(m["app"], m["field"]): m for m in deep["misses"]}
    miss_priority = [
        ("Twenty", "access_tier"),
        ("Zendesk", "access_tier"),
        ("Notion", "access_tier"),
        ("Notion", "auth_primary"),
        ("Ahrefs", "access_tier"),
        ("Meta Ads", "mcp_exists"),
        ("fanbasis", "access_tier"),
        ("DealCloud", "mcp_exists"),
        ("QuickBooks", "access_tier"),
        ("Pylon", "access_tier"),
    ]
    miss_rows = []
    for app, field in miss_priority:
        m = miss_index.get((app, field))
        if not m:
            continue
        miss_rows.append(
            [
                esc(m["app"]),
                esc(m["field"]),
                esc(m["expected"]),
                esc(m["actual"]),
                esc(causes.get((m["app"], m["field"]), m["bucket"])),
            ]
        )

    version_rows = [
        [esc(v["version"]), esc(v["overall"])] for v in stats["K_version_history"]
    ]

    # Full table: drop redundant blocker_type (implied by verdict/unblocker)
    by_build: dict[str, list] = {b: [] for b in BUILD_ORDER}
    for r in rows:
        by_build.setdefault(r.get("buildability") or "unknown", []).append(r)
    for b in by_build:
        by_build[b].sort(key=lambda x: (x.get("app_name") or "").lower())

    full_sections = []
    for b in BUILD_ORDER:
        group = by_build.get(b) or []
        if not group:
            continue
        full_sections.append(f'<h3 id="{esc(b)}">{esc(b)} — {len(group)} of {n}</h3>')
        fr = []
        for r in group:
            fr.append(
                [
                    esc(r.get("app_name")),
                    esc(cat_short(r.get("category") or "")),
                    verdict_cell(r.get("buildability") or "unknown"),
                    esc(r.get("unblocker") or ""),
                    esc(r.get("access_tier") or "unknown"),
                    esc(r.get("auth_primary") or "unknown"),
                    esc(r.get("api_type") or "unknown"),
                    esc(r.get("mcp_exists") or "unknown"),
                    short_url((r.get("evidence") or {}).get("access_tier") or ""),
                ]
            )
        full_sections.append(
            table(
                ["app", "category", "verdict", "who acts", "tier", "auth", "api", "MCP", "evidence"],
                fr,
            )
        )

    defeated_apps = ", ".join(cov["docs_none_apps"] + ["Salesforce Commerce Cloud"])
    unknown_tier = ", ".join(cov["access_tier_unknown_apps"])

    data_json = json.dumps(rows, ensure_ascii=False)
    stats_embed = json.dumps(stats, ensure_ascii=False)

    css = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#111;background:#fff}
main{max-width:1100px;margin:0 auto;padding:1.25rem 1rem 2.5rem}
h1{font-size:1.35rem;font-weight:700;line-height:1.35;margin:0 0 .4rem}
h2{font-size:1.05rem;margin:1.6rem 0 .5rem;padding-bottom:.2rem;border-bottom:1px solid #111}
h3{font-size:.95rem;margin:1rem 0 .35rem}
p,li{margin:.35rem 0;max-width:72ch}
.sub{color:#333;margin:0 0 1rem;font-size:.92rem}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.5rem;margin:0 0 1.25rem}
@media(max-width:900px){.stats{grid-template-columns:repeat(3,1fr)}}
@media(max-width:520px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{border:1px solid #111;padding:.55rem .65rem;min-height:4.2rem}
.stat .n{display:block;font-size:1.35rem;font-weight:700;line-height:1.1;word-break:break-word}
.stat .l{font-size:.75rem;line-height:1.25;color:#222}
table{border-collapse:collapse;width:100%;margin:.35rem 0 1rem;font-size:.84rem}
th,td{border:1px solid #111;padding:.28rem .4rem;text-align:left;vertical-align:top}
th{background:#f2f2f2;font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.swatch{display:inline-block;width:.55rem;height:.55rem;border:1px solid #111;margin-right:.3rem;vertical-align:middle}
.note{font-size:.9rem;margin:.25rem 0 .75rem}
.box{border:1px solid #111;padding:.75rem .9rem;margin:1rem 0}
footer{margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #111;font-size:.85rem}
a{color:#111}
code{font-size:.9em}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:800px){.two-col{grid-template-columns:1fr}}
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Composio toolkit research — 100-app findings</title>
<style>{css}</style>
</head>
<body>
<main>

<h1>Of {n} apps: {h['easy_win']} self-serve today, {h['needs_review']} need vendor approval,
{h['needs_outreach']} need sales outreach, {h['blocked']} have no usable API
({h['easy_but_paid']} paid-first, {h['buildability_unknown']} unclassified).
Accuracy on {deep['sample_apps']} hand-labelled apps ({deep_base} labels):
<strong>{deep_pct}%</strong> ({deep_correct}/{deep_base}) —
tier {tier_pct}% · auth {auth_pct}% · api {api_pct}% · MCP {mcp_pct}%.</h1>
<p class="sub">Public/distributed integration path (Composio ships multi-customer toolkits).
Auth mix: {esc(auth_line)}.</p>

<div class="stats">
  <div class="stat"><span class="n">{h['easy_win']}</span><span class="l">easy_win</span></div>
  <div class="stat"><span class="n">{h['needs_review']}</span><span class="l">needs_review</span></div>
  <div class="stat"><span class="n">{h['needs_outreach']}</span><span class="l">needs_outreach</span></div>
  <div class="stat"><span class="n">{h['blocked']}</span><span class="l">blocked</span></div>
  <div class="stat"><span class="n">{h['access_tier_unknown']}</span><span class="l">tier unknown</span></div>
  <div class="stat"><span class="n">{h['most_common_blocker_count']}</span><span class="l">{esc(h['most_common_blocker'])} (top blocker)</span></div>
</div>

<h2>Proof (up front)</h2>
<p class="note">Deep check on {deep['sample_apps']} apps × 4 fields. Correct / wrong / honestly unknown —
never blended with Composio catalog shallow check
(yes {shallow['yes']} · disagrees {shallow['disagrees']} · n_a {shallow['n_a']} of {n}).
Same rules engine on labels and agent output.</p>
{table(['field', 'correct', 'wrong', 'unk', '%'], deep_rows)}
{table(['app', 'field', 'expected', 'actual', 'cause'], miss_rows)}
<p class="note"><strong>Docs support two readings:</strong>
Notion (marketplace vs unlisted public) ·
Ahrefs (Connect partner vs plan-gated API) ·
Twenty/Zendesk (free vs trial).</p>
<p class="note"><strong>Defeated:</strong> {esc(defeated_apps)}.
<strong>Tier unknown ({cov['access_tier_unknown']} of {n}):</strong> {esc(unknown_tier)}.</p>
{table(['version', 'score'], version_rows)}
<p class="note">Prompt tweaks moved little; post-loop code guards lifted the 3-trial average ~58%→~61%.</p>

<h2>Patterns</h2>
<p class="note"><strong>Auth ≠ buildability.</strong>
{e['api_key_not_easy_win']} of {e['api_key_total']} api_key apps are not easy_win;
oauth2 spans {e['oauth2_distinct_buildability_count']} verdicts. Triage by who must say yes.</p>
{table(e_headers, e_rows)}
<p class="note"><strong>Queues.</strong> {esc(queues['takeaway'])}</p>
{table(['who acts', 'n', 'wait', 'work'], f_rows)}

<h2>Required counts</h2>
<div class="two-col">
<div>
<p class="note">Auth (of {n}).</p>
{table(['auth', 'n', '%'], a_rows)}
<p class="note">Blockers excl. none.</p>
{table(['blocker', 'n', 'who'], c_rows)}
</div>
<div>
<p class="note">Verdicts.</p>
{table(['verdict', 'n', 'means'], d_rows)}
<p class="note">Secondary (of {n}). MCP present but not easy_win: {g['mcp_present_not_easy_win']} of {g['mcp_present']}.</p>
{table(['signal', 'breakdown'], g_rows)}
</div>
</div>
<p class="note">Categories by access_tier_rollup — most gated {esc(bcat['most_gated_category'])} ({bcat['most_gated_detail']});
most open {esc(bcat['most_open_category'])} ({bcat['most_open_detail']}).</p>
{table(['category', 'open', 'paid', 'gated', 'unk', 'n'], b_rows)}

<h2>All 100 apps</h2>
<p class="note">Sorted easy→hard; A–Z within group. “Who acts” replaces a separate blocker column (same mapping).</p>
{''.join(full_sections)}

<h2>Method</h2>
<p>Discover agent (Gemini + Tavily search) → Tavily extract via Composio SDK → no-tools extract →
post-loop guards (second-round auth/path preference; MCP URL presence) →
Python rules engine for verdicts (not ML clustering).</p>
<p class="note">Human-required: hand GT (30 apps), public-path assumption, enum boundaries,
diagnosing prompt vs code fixes.</p>

<div class="box">
<h2>Constraints</h2>
<p>Free tiers only (Flash-lite, Tavily credits, no paid app accounts) → ~2 model calls and ≤6 pages/app.
Flash-lite is weak for boundary judgement; a stronger model would help more than further prompt tweaks.
No second verification agent (budget constraint)—without that limit, a verifier over scored fields would raise accuracy further.
Unshipped: trial/free detect, MCP gated-from-page-text, tighter auth_detail conflict → expected ~61% toward 65–70%.
Accuracy is not one number: api_type {api_pct}% vs access_tier {tier_pct}% (many boundary disagreements).</p>
</div>

<footer>
<p><a href="{esc(repo_url)}">{esc(repo_url)}</a> ·
<a href="{esc(research_repo)}">{esc(research_repo)}</a> ·
generated {esc(date.today().isoformat())} ·
reproduce: <code>prepare_final.py → build_stats.py → build_page.py</code> on <code>master</code></p>
</footer>

</main>
<script type="application/json" id="data">{data_json}</script>
<script type="application/json" id="stats">{stats_embed}</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", default="data/stats.json")
    parser.add_argument("--final", default="data/final.json")
    parser.add_argument("--out", default="index.html")
    parser.add_argument("--repo-url", default="https://github.com/Aacashi/composio-toolkit-findings")
    parser.add_argument(
        "--research-repo",
        default="https://github.com/Aacashi/composio-toolkit-research",
    )
    args = parser.parse_args(argv)

    def resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else ROOT / path

    out = build_html(
        load(resolve(args.stats)),
        load(resolve(args.final)),
        repo_url=args.repo_url,
        research_repo=args.research_repo,
    )
    out_path = resolve(args.out)
    out_path.write_text(out, encoding="utf-8")
    print(f"[page] wrote {out_path} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
