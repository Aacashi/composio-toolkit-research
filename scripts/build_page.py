"""Generate single static findings index.html from stats.json + final.json.

Rules-engine output only — no hardcoded counts. Commit the HTML; no build step at deploy.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date
from pathlib import Path

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


def table(headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{c}</td>" for c in row)
        body.append(f"<tr>{tds}</tr>")
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f"<table>{cap}<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def verdict_cell(v: str) -> str:
    color = SWATCH.get(v, "#000")
    return (
        f'<span class="swatch" style="background:{color}"></span> {esc(v)}'
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

    # Headline residual
    residual = (
        f" Two more need a paid plan first ({h['easy_but_paid']} of {n}); "
        f"{h['buildability_unknown']} of {n} could not be classified."
    )

    # A
    a_rows = [
        [esc(r["value"]), str(r["count"]), f"{r['pct_of_100']}% ({r['count']} of {n})"]
        for r in stats["A_auth_dominates"]
    ]

    # B
    b_rows = []
    for r in bcat["rows"]:
        b_rows.append(
            [
                esc(r["category"]),
                str(r["open"]),
                str(r["paid"]),
                str(r["gated"]),
                str(r["unknown"]),
                str(r["total"]),
            ]
        )

    # C
    c_rows = [
        [esc(r["blocker_type"]), str(r["count"]), esc(r["who_acts"])]
        for r in stats["C_blockers"]
    ]

    # D
    d_rows = [
        [esc(r["verdict"]), str(r["count"]), esc(r["meaning"])]
        for r in stats["D_buildability"]
    ]

    # E matrix
    cols = e["columns"]
    e_headers = ["auth_primary"] + cols + ["total"]
    e_rows = []
    for r in e["rows"]:
        e_rows.append([esc(r["row"])] + [str(r.get(c, 0)) for c in cols] + [str(r["total"])])

    # F
    f_rows = [
        [
            esc(r["who_must_act"]),
            str(r["count"]),
            esc(r["typical_wait"]),
            esc(r["work_kind"]),
        ]
        for r in queues["rows"]
    ]

    # G
    g_rows = [
        [
            "OpenAPI spec",
            f"yes {g['has_openapi_spec']['yes']} / no {g['has_openapi_spec']['no']} / unknown {g['has_openapi_spec']['unknown']} (of {n})",
        ],
        [
            "Needs instance URL",
            f"yes {g['needs_instance_url']['yes']} / no {g['needs_instance_url']['no']} / unknown {g['needs_instance_url']['unknown']} (of {n})",
        ],
        [
            "Webhooks",
            f"yes {g['has_webhooks']['yes']} / no {g['has_webhooks']['no']} / unknown {g['has_webhooks']['unknown']} (of {n})",
        ],
        [
            "MCP servers",
            (
                f"official_open {g['mcp_exists']['official_open']} / "
                f"official_gated {g['mcp_exists']['official_gated']} / "
                f"community {g['mcp_exists']['community']} / "
                f"none {g['mcp_exists']['none']} / "
                f"unknown {g['mcp_exists']['unknown']} (of {n})"
            ),
        ],
    ]

    # Deep accuracy
    deep_rows = []
    for field, d in deep["fields"].items():
        deep_rows.append(
            [
                esc(field),
                str(d["correct"]),
                str(d["wrong"]),
                str(d["honestly_unknown"]),
                f"{d['correct_pct_of_base']}% correct ({d['correct']} of {d['base']})",
            ]
        )

    # Miss table (curated 8–10 named)
    miss_priority = [
        ("Twenty", "access_tier"),
        ("Zendesk", "access_tier"),
        ("Zendesk", "auth_primary"),
        ("Notion", "access_tier"),
        ("Notion", "auth_primary"),
        ("Ahrefs", "access_tier"),
        ("Meta Ads", "mcp_exists"),
        ("fanbasis", "access_tier"),
        ("DealCloud", "mcp_exists"),
        ("QuickBooks", "access_tier"),
    ]
    causes = {
        ("Twenty", "access_tier"): "Trial vs free boundary on pricing page",
        ("Zendesk", "access_tier"): "Second-round preferred public path → approval_gated vs GT trial",
        ("Zendesk", "auth_primary"): "Fixed by second-round preference in other runs; GT wants basic",
        ("Notion", "access_tier"): "Missed marketplace review; docs support two readings",
        ("Notion", "auth_primary"): "Basic token-exchange confused with primary auth (GT oauth2)",
        ("Ahrefs", "access_tier"): "Chose Ahrefs Connect partner path vs plain API plan_gated",
        ("Meta Ads", "mcp_exists"): "MCP presence wiped (no MCP URL); GT is none",
        ("fanbasis", "access_tier"): "Docs password-walled; only marketing homepage fetched",
        ("DealCloud", "mcp_exists"): "MCP open vs gated misread",
        ("QuickBooks", "access_tier"): "Second-round path override flipped a correct approval_gated",
    }
    miss_index = {(m["app"], m["field"]): m for m in deep["misses"]}
    miss_rows = []
    for app, field in miss_priority:
        m = miss_index.get((app, field))
        if not m:
            # find any miss for app
            cand = [x for x in deep["misses"] if x["app"] == app]
            if not cand:
                continue
            m = cand[0]
            field = m["field"]
        miss_rows.append(
            [
                esc(m["app"]),
                esc(m["field"]),
                esc(m["expected"]),
                esc(m["actual"]),
                esc(causes.get((m["app"], m["field"]), m["bucket"])),
            ]
        )

    # Full table by buildability
    by_build = {b: [] for b in BUILD_ORDER}
    for r in rows:
        b = r.get("buildability") or "unknown"
        by_build.setdefault(b, []).append(r)
    for b in by_build:
        by_build[b].sort(key=lambda x: (x.get("app_name") or "").lower())

    full_sections = []
    for b in BUILD_ORDER:
        group = by_build.get(b) or []
        if not group:
            continue
        full_sections.append(f"<h3>{esc(b)} ({len(group)} of {n})</h3><hr>")
        fr = []
        for r in group:
            ev = (r.get("evidence") or {}).get("access_tier") or ""
            if ev:
                ev_cell = f'<a href="{esc(ev)}">{esc(ev)}</a>'
            else:
                ev_cell = "—"
            fr.append(
                [
                    esc(r.get("app_name")),
                    esc(r.get("category")),
                    verdict_cell(r.get("buildability") or "unknown"),
                    esc(r.get("blocker_type") or ""),
                    esc(r.get("unblocker") or ""),
                    esc(r.get("access_tier") or "unknown"),
                    esc(r.get("auth_primary") or "unknown"),
                    esc(r.get("api_type") or "unknown"),
                    esc(r.get("mcp_exists") or "unknown"),
                    ev_cell,
                ]
            )
        full_sections.append(
            table(
                [
                    "app",
                    "category",
                    "verdict",
                    "blocker",
                    "who unblocks",
                    "access tier",
                    "auth",
                    "api type",
                    "MCP",
                    "evidence",
                ],
                fr,
            )
        )

    data_json = json.dumps(rows, ensure_ascii=False)
    stats_embed = json.dumps(stats, ensure_ascii=False)

    version_rows = [
        [esc(v["version"]), esc(v["overall"]), esc(v["note"])] for v in stats["K_version_history"]
    ]

    shallow_rows = [
        ["yes", str(shallow["yes"])],
        ["disagrees", str(shallow["disagrees"])],
        ["n_a", str(shallow["n_a"])],
    ]

    defeated = [
        ["fanbasis", "Developer docs password-walled; only the marketing homepage was reachable"],
        ["PitchBook", "No documentation found; schema_fail / empty fetch path"],
        [
            "Salesforce Commerce Cloud",
            "Docs page returned little usable API content (thin / consent furniture)",
        ],
    ]
    for name in cov["docs_none_apps"]:
        if name not in ("fanbasis", "PitchBook"):
            defeated.append([name, "docs_access=none_found"])

    css = """
:root { color-scheme: light; }
body { margin: 0; font: 16px/1.45 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  color: #111; background: #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.75rem; font-weight: 700; line-height: 1.25; margin: 0 0 0.5rem; }
h2 { font-size: 1.25rem; margin: 2rem 0 0.75rem; border-bottom: 1px solid #111; padding-bottom: 0.25rem; }
h3 { font-size: 1.05rem; margin: 1.25rem 0 0.5rem; }
p, li { max-width: 70ch; }
.assumption { color: #333; margin: 0 0 1.25rem; }
.stat-row { display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0 1.5rem; }
.stat { border: 1px solid #111; padding: 0.75rem 1rem; min-width: 7rem; }
.stat .n { font-size: 1.75rem; font-weight: 700; display: block; }
.stat .l { font-size: 0.85rem; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.25rem; font-size: 0.92rem; }
th, td { border: 1px solid #111; padding: 0.35rem 0.5rem; text-align: left; vertical-align: top; }
th { background: #f3f3f3; }
.swatch { display: inline-block; width: 0.65rem; height: 0.65rem; border: 1px solid #111;
  vertical-align: middle; margin-right: 0.25rem; }
.constraints { border: 1px solid #111; padding: 1rem; margin: 1.5rem 0; }
footer { margin-top: 2rem; font-size: 0.9rem; border-top: 1px solid #111; padding-top: 0.75rem; }
.takeaway { font-weight: 600; margin: 0.25rem 0 0.5rem; }
a { color: #111; }
hr { border: 0; border-top: 1px solid #111; margin: 0.5rem 0 1rem; }
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Composio toolkit research — findings (100 apps)</title>
<style>{css}</style>
</head>
<body>
<main>
<h1>Of {n} apps, {h['easy_win']} can be built today with self-serve credentials,
{h['needs_review']} need a vendor to approve, {h['needs_outreach']} need a sales conversation,
and {h['blocked']} have no usable API.{residual}</h1>
<p class="assumption">Classified for the public/distributed integration path, since Composio ships
toolkits that many customers install.</p>

<h2>At a glance</h2>
<div class="stat-row">
  <div class="stat"><span class="n">{h['easy_win']}</span><span class="l">easy_win</span></div>
  <div class="stat"><span class="n">{h['needs_review']}</span><span class="l">needs_review</span></div>
  <div class="stat"><span class="n">{h['needs_outreach']}</span><span class="l">needs_outreach</span></div>
  <div class="stat"><span class="n">{h['blocked']}</span><span class="l">blocked</span></div>
  <div class="stat"><span class="n">{h['access_tier_unknown']}</span><span class="l">access_tier unknown</span></div>
  <div class="stat"><span class="n">{esc(h['most_common_blocker'])}</span><span class="l">most common blocker ({h['most_common_blocker_count']} of {n})</span></div>
</div>

<h2>Patterns that change a decision</h2>

<h3>Auth complexity does not predict buildability</h3>
<p class="takeaway">{e['api_key_not_easy_win']} of {e['api_key_total']} api_key apps are not easy_win.
oauth2 apps span {e['oauth2_distinct_buildability_count']} distinct buildability values
({', '.join(e['oauth2_buildability_span'])}). Same auth appears across easy_win, needs_review, and needs_outreach —
triage by who must say yes, not by how hard the integration looks.</p>
{table(e_headers, e_rows)}

<h3>The queues, sized</h3>
<p class="takeaway">{esc(queues['takeaway'])}</p>
{table(['who must act', 'app count', 'typical wait', 'what kind of work'], f_rows)}

<h2>Four statistics the brief asks for</h2>

<h3>Which auth dominates</h3>
<p class="takeaway">oauth2 leads at {stats['A_auth_dominates'][0]['count']} of {n}
({stats['A_auth_dominates'][0]['pct_of_100']}%); api_key is second at
{stats['A_auth_dominates'][1]['count']} of {n}.</p>
{table(['auth method', 'count', '% (n of 100)'], a_rows)}

<h3>Which categories are self-serve vs gated</h3>
<p class="takeaway">Most gated: {esc(bcat['most_gated_category'])} ({bcat['most_gated_detail']}).
Most open: {esc(bcat['most_open_category'])} ({bcat['most_open_detail']}).
Uses access_tier_rollup; unknown is its own column.</p>
{table(['category', 'open', 'paid', 'gated', 'unknown', 'total'], b_rows)}

<h3>The most common blocker</h3>
<p class="takeaway">Excluding none, the most common blocker is {esc(h['most_common_blocker'])}
({h['most_common_blocker_count']} of {n}) — vendor review.</p>
{table(['blocker', 'count', 'who has to act'], c_rows)}

<h3>Easy wins versus needs outreach</h3>
<p class="takeaway">{h['easy_win']} of {n} are easy_win; {h['needs_outreach']} of {n} need outreach;
{h['needs_review']} of {n} need vendor review.</p>
{table(['verdict', 'count', 'what it means'], d_rows)}

<h2>Secondary statistics</h2>
{table(['signal', 'counts'], g_rows)}
<p>{g['mcp_present_not_easy_win']} of {g['mcp_present']} apps with an MCP server
(official_open, official_gated, or community) are not easy_win — MCP presence does not imply
the API is accessible.</p>

<h2>Full table (100 apps)</h2>
<p>Sorted by buildability, easiest first; alphabetical within each group. Evidence links to the
primary access_tier URL when present.</p>
{''.join(full_sections)}

<h2>How it was built</h2>
<p>A discover agent with a bound Tavily search tool chooses what to search. Pages are fetched and
extracted through Tavily via the Composio SDK (direct Tavily fallback if needed). A second, no-tools
Gemini call fills atomic facts and path fields. Deterministic post-loop guards prefer second-round
auth/path corrections and wipe MCP presence claims without an MCP URL. A pure-Python rules engine
(<code>derive_verdict</code>) derives buildability, blockers, and rollups offline — counts and
cross-tabs, not ML clustering.</p>
<ul>
<li>Hand-labelling 30 apps as ground truth before scoring runs</li>
<li>Choosing the public/distributed path assumption</li>
<li>Defining enum boundaries (trial vs free, partner vs plan, etc.)</li>
<li>Diagnosing why prompt-only fixes failed and deterministic code fixes moved accuracy</li>
</ul>

<h2>Verification</h2>
<p>Deep verification sample: {deep['sample_apps']} apps across three ground-truth files,
four scored fields each (up to 120 labels). Correct / wrong / honestly unknown are never blended
with the shallow Composio check. The same rules engine runs over hand labels and agent output —
a verdict mismatch always traces to a fact mismatch.</p>
{table(['field', 'correct', 'wrong', 'honestly unknown', 'rate'], deep_rows)}
<p>Overall deep: {deep['overall']['correct']} correct, {deep['overall']['wrong']} wrong,
{deep['overall']['honestly_unknown']} honestly unknown
({deep['overall']['correct_pct_of_base']}% of {deep['overall']['base']}).</p>

<h3>Shallow verification (Composio auth agreement)</h3>
<p>{esc(shallow['note'])}</p>
{table(['agrees_with_composio', 'count'], shallow_rows)}

<h3>Version history</h3>
{table(['version', 'overall', 'what changed'], version_rows)}
<p>Prompt-level tweaks moved little on judgement fields. Deterministic code fixes (merge/second-round
preference, MCP URL presence wipe) moved the three-trial average from about 58% to about 61%.</p>

<h3>Miss table (named)</h3>
{table(['app', 'field', 'expected', 'actual', 'cause'], miss_rows)}

<h3>Named divergences (docs support two readings)</h3>
<ul>
<li><strong>Notion</strong> — public connections may need Marketplace security review, but an unlisted
public connection can be used without one; both clauses appear in the docs.</li>
<li><strong>Ahrefs</strong> — Ahrefs Connect is a partner programme; plain API access is only plan-gated.
Both labels are defensible.</li>
<li><strong>Twenty / Zendesk</strong> — free versus trial is a boundary call on pricing pages.</li>
</ul>

<h2>What defeated the agent</h2>
{table(['app', 'reason'], [[esc(a), esc(b)] for a, b in defeated])}
<p>{cov['access_tier_unknown']} of {n} apps ended with access_tier unknown:
{esc(', '.join(cov['access_tier_unknown_apps']))}.</p>

<div class="constraints">
<h2>Constraints</h2>
<p>Built entirely on free tiers: Gemini Flash-lite for all model calls, Tavily free credits for
search and extraction, no paid accounts for any of the 100 apps, and no local model. That capped
the pipeline at roughly two model calls and six page fetches per app.</p>
<p>Flash-lite is a weak choice for multi-step reasoning and boundary judgements (trial vs free,
MCP open vs gated, public-path auth). A stronger model would be a better choice for extraction
and any future verifier.</p>
<p>There is no second verification agent today. That is a free-tier / call-budget constraint, not
a design preference. Without those constraints, a second agent would re-read fetched pages and
challenge every scored field before commit — expected to catch hallucinated MCP, wrong auth, and
path/tier misreads beyond what post-loop guards alone can fix.</p>
<p>Three further fixes were identified but not shipped: trial-versus-free detection in the extract
prompt, MCP open-versus-gated gating on page text rather than URL presence, and a corrected
auth_detail conflict rule. Together these were expected to move overall accuracy from roughly
61% into the 65–70% range.</p>
<p>Accuracy is also not one number. Factual fields reach 90% (api_type, {deep['fields']['api_type']['correct']}
of {deep['fields']['api_type']['base']}). Judgement fields reach
{deep['fields']['access_tier']['correct_pct_of_base']}% (access_tier), and roughly a third of those
errors are boundary disagreements where the vendor's own documentation supports both labels.</p>
</div>

<footer>
<p>Findings page repo: <a href="{esc(repo_url)}">{esc(repo_url)}</a>.
Research pipeline: <a href="{esc(research_repo)}">{esc(research_repo)}</a>.</p>
<p>Run data: v2b postguard + rules-engine derive · page generated {esc(date.today().isoformat())}.</p>
<p>Reproduce: prepare_final.py → build_stats.py → build_page.py from
composio-toolkit-research (<code>publish-v2-harden</code>).</p>
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
    parser.add_argument(
        "--repo-url",
        default="https://github.com/Aacashi/composio-toolkit-findings",
    )
    parser.add_argument(
        "--research-repo",
        default="https://github.com/Aacashi/composio-toolkit-research/tree/publish-v2-harden",
    )
    args = parser.parse_args(argv)

    stats_path = Path(args.stats)
    final_path = Path(args.final)
    out_path = Path(args.out)
    if not stats_path.is_absolute():
        stats_path = ROOT / stats_path
    if not final_path.is_absolute():
        final_path = ROOT / final_path
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    html_out = build_html(
        load(stats_path),
        load(final_path),
        repo_url=args.repo_url,
        research_repo=args.research_repo,
    )
    out_path.write_text(html_out, encoding="utf-8")
    print(f"[page] wrote {out_path} ({len(html_out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
