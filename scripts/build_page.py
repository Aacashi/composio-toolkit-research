"""Generate human-skimmable findings case study (index.html) from stats + final JSON."""

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
    path = (p.path or "")[:28] + ("…" if len(p.path or "") > 28 else "")
    return f'<a href="{esc(url)}">{esc(host + path)}</a>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def verdict_cell(v: str) -> str:
    return f'<span class="swatch" style="background:{SWATCH.get(v, "#000")}"></span>{esc(v)}'


def cat_short(name: str) -> str:
    return (
        (name or "")
        .replace("Marketing, Ads, Email and Social", "Marketing")
        .replace("Communications and Messaging", "Comms")
        .replace("Developer, Infra and Data platforms", "Dev/Infra")
        .replace("Productivity and Project Management", "Productivity")
        .replace("AI, Research and Media-native", "AI/Media")
        .replace("Data, SEO and Scraping", "Data/SEO")
        .replace("Support and Helpdesk", "Support")
        .replace("Finance and Fintech", "Finance")
        .replace("CRM and Sales", "CRM")
    )


def pct_cell(pct: float) -> str:
    if pct == 0:
        return "—"
    return f"{pct:g}%"


def build_html(stats: dict, rows: list[dict], *, research_repo: str, findings_repo: str) -> str:
    h = stats["headline"]
    n = stats["n"]
    deep = stats["I_deep_verification"]
    g = stats["G_secondary"]
    cov = stats["H_coverage"]
    e = stats["E_auth_x_buildability"]
    bcat = stats["B_category_rollup"]
    queues = stats["F_queues"]
    cat_build = stats["B2_category_buildability"]
    bt_build = stats["B3_business_type_buildability"]
    trials = deep.get("trials") or []
    trial_avg = deep.get("trial_avg_pct", deep["overall"]["correct_pct_of_base"])

    tier = deep["fields"]["access_tier"]
    auth = deep["fields"]["auth_primary"]
    api = deep["fields"]["api_type"]
    mcp = deep["fields"]["mcp_exists"]

    sample = deep.get("sample_miss") or {}
    sample_app = sample.get("app", "—")
    sample_field = sample.get("field", "—")
    sample_exp = sample.get("expected", "—")
    sample_act = sample.get("actual", "—")

    trial_rows = []
    for t in trials:
        trial_rows.append(
            [
                esc(t["label"]),
                f"{t['overall']['correct']}/{t['overall']['base']}",
                f"{t['overall']['correct_pct_of_base']}%",
                f"{t['fields']['access_tier']['correct_pct_of_base']}%",
                f"{t['fields']['auth_primary']['correct_pct_of_base']}%",
                f"{t['fields']['api_type']['correct_pct_of_base']}%",
                f"{t['fields']['mcp_exists']['correct_pct_of_base']}%",
            ]
        )
    if trials:
        trial_rows.append(
            [
                "Average of 3 trials",
                "—",
                f"{trial_avg}%",
                f"{round(sum(t['fields']['access_tier']['correct_pct_of_base'] for t in trials)/len(trials),1)}%",
                f"{round(sum(t['fields']['auth_primary']['correct_pct_of_base'] for t in trials)/len(trials),1)}%",
                f"{round(sum(t['fields']['api_type']['correct_pct_of_base'] for t in trials)/len(trials),1)}%",
                f"{round(sum(t['fields']['mcp_exists']['correct_pct_of_base'] for t in trials)/len(trials),1)}%",
            ]
        )

    field_rows = [
        ["access_tier (highest judgement)", f"{tier['correct']}/{tier['base']}", f"{tier['correct_pct_of_base']}%"],
        ["auth_primary", f"{auth['correct']}/{auth['base']}", f"{auth['correct_pct_of_base']}%"],
        ["api_type (most factual)", f"{api['correct']}/{api['base']}", f"{api['correct_pct_of_base']}%"],
        ["mcp_exists", f"{mcp['correct']}/{mcp['base']}", f"{mcp['correct_pct_of_base']}%"],
    ]

    # Category × buildability % (10 apps each)
    cat_pct_rows = []
    for r in cat_build["rows"]:
        cat_pct_rows.append(
            [
                esc(cat_short(r["category"])),
                pct_cell(r["easy_win_pct"]),
                pct_cell(r["easy_but_paid_pct"]),
                pct_cell(r["needs_review_pct"]),
                pct_cell(r["needs_outreach_pct"]),
                pct_cell(r["blocked_pct"]),
                pct_cell(r["unknown_pct"]),
            ]
        )

    # Business type × buildability %
    bt_pct_rows = []
    for r in bt_build["rows"]:
        bt_pct_rows.append(
            [
                esc(r["business_type"]),
                str(r["total"]),
                pct_cell(r["easy_win_pct"]),
                pct_cell(r["easy_but_paid_pct"]),
                pct_cell(r["needs_review_pct"]),
                pct_cell(r["needs_outreach_pct"]),
                pct_cell(r["blocked_pct"]),
                pct_cell(r["unknown_pct"]),
            ]
        )

    # Full 100 table last
    by_build: dict[str, list] = {b: [] for b in BUILD_ORDER}
    for r in rows:
        by_build.setdefault(r.get("buildability") or "unknown", []).append(r)
    for b in by_build:
        by_build[b].sort(key=lambda x: (x.get("app_name") or "").lower())

    full_bits = []
    for b in BUILD_ORDER:
        group = by_build.get(b) or []
        if not group:
            continue
        full_bits.append(f"<h3>{esc(b)} — {len(group)} of {n}</h3>")
        fr = []
        for r in group:
            fr.append(
                [
                    esc(r.get("app_name")),
                    esc(cat_short(r.get("category") or "")),
                    esc(r.get("business_type") or "—"),
                    verdict_cell(r.get("buildability") or "unknown"),
                    esc(r.get("unblocker") or ""),
                    esc(r.get("access_tier") or "unknown"),
                    esc(r.get("auth_primary") or "unknown"),
                    esc(r.get("api_type") or "unknown"),
                    esc(r.get("mcp_exists") or "unknown"),
                    short_url((r.get("evidence") or {}).get("access_tier") or ""),
                ]
            )
        full_bits.append(
            table(
                [
                    "app",
                    "category",
                    "business_type",
                    "verdict",
                    "who acts",
                    "tier",
                    "auth",
                    "api",
                    "MCP",
                    "evidence",
                ],
                fr,
            )
        )

    data_json = json.dumps(rows, ensure_ascii=False)
    stats_json = json.dumps(stats, ensure_ascii=False)

    css = """
*{box-sizing:border-box}
body{margin:0;font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#111;background:#fff}
main{max-width:820px;margin:0 auto;padding:1.5rem 1.1rem 3rem}
h1{font-size:1.45rem;line-height:1.3;margin:0 0 .5rem;font-weight:700}
h2{font-size:1.1rem;margin:1.75rem 0 .55rem;padding-bottom:.25rem;border-bottom:1px solid #111}
h3{font-size:.95rem;margin:1.1rem 0 .4rem}
p,li{margin:.4rem 0;max-width:70ch}
ul{padding-left:1.15rem;margin:.35rem 0 .8rem}
.lead{font-size:1.02rem;margin:0 0 1rem}
.meta{color:#333;font-size:.92rem;margin:0 0 1.25rem}
.proof{border:1px solid #111;padding:.7rem .85rem;margin:0 0 1.25rem;font-size:.92rem}
.proof a{font-weight:600}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;margin:1rem 0 1.25rem}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{border:1px solid #111;padding:.55rem .65rem}
.stat b{display:block;font-size:1.4rem;line-height:1.1}
.stat span{font-size:.78rem}
table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem;font-size:.82rem}
th,td{border:1px solid #111;padding:.28rem .4rem;text-align:left;vertical-align:top}
th{background:#f3f3f3}
.swatch{display:inline-block;width:.55rem;height:.55rem;border:1px solid #111;margin-right:.3rem;vertical-align:middle}
.box{border:1px solid #111;padding:.75rem .9rem;margin:1rem 0}
.flow{font-family:ui-monospace,Consolas,monospace;font-size:.84rem;line-height:1.55;border:1px solid #111;padding:.7rem .85rem;margin:.6rem 0 1rem;white-space:pre-wrap;background:#fafafa}
footer{margin-top:2rem;padding-top:.7rem;border-top:1px solid #111;font-size:.85rem}
a{color:#111}
.full{max-width:1100px}
.full-wrap{margin-left:calc(50% - 50vw);margin-right:calc(50% - 50vw);padding:0 max(1rem, calc(50vw - 550px))}
code{font-size:.88em}
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Composio toolkit research — case study</title>
<style>{css}</style>
</head>
<body>
<main>

<h1>Of {n} apps, {h['easy_win']} can ship with self-serve credentials today,
{h['needs_review']} need a vendor to approve, {h['needs_outreach']} need a sales conversation,
and {h['blocked']} have no usable API.</h1>
<p class="lead">Plus {h['easy_but_paid']} that need payment first and {h['buildability_unknown']} still unclassified.
Classified on the <strong>public / distributed</strong> path — Composio ships toolkits many customers install.
The product question is not “how hard is the API?” but “who has to say yes before an engineer can start?”</p>

<div class="proof">
<strong>Proof / code:</strong>
<a href="{esc(research_repo)}">{esc(research_repo)}</a>
(full research pipeline on <code>master</code>).
Regenerate with <code>prepare_final.py → build_stats.py → build_page.py</code>.
</div>

<div class="stats">
  <div class="stat"><b>{h['easy_win']}</b><span>easy_win</span></div>
  <div class="stat"><b>{h['needs_review']}</b><span>needs_review</span></div>
  <div class="stat"><b>{h['needs_outreach']}</b><span>needs_outreach</span></div>
  <div class="stat"><b>{h['blocked']}</b><span>blocked</span></div>
</div>

<h2>Pipeline</h2>
<p>Core idea: reverse-engineer vendor incentives into a <code>business_type</code> prior, use that prior to
decide <em>where</em> documentation usually lives, search there under a tight budget, extract only cited facts,
then let Python — not the LLM — decide the ops verdict.</p>
<div class="flow">app + category + hint
  → Call 1 discover (Gemini Flash-Lite + Tavily search, ≤6 tool calls)
      · classify business_type (incentive prior)
      · prior reshapes queries (infra→quickstart/keys; ads→Marketing API + app review;
        enterprise→partner / contact sales; data vendor→pricing tiers; …)
      · fill six URL slots: auth, pricing/access, API index, OpenAPI, webhooks, MCP
  → URL liveness check (dead auth/pricing URLs nulled; flags dead_url_skipped)
  → fetch first-party pages (Tavily extract via Composio SDK; budget-capped)
  → Call 2 extract (no tools): path fields, auth, api_type, MCP, OpenAPI, webhooks
      · must cite evidence URLs; access_tier is NOT guessed by Gemini
  → if scored fields still unknown → one targeted second round (≤2 more searches, more pages)
  → merge_extract (prefer second-round on auth/path contradictions)
  → post-loop guards (no LLM):
      · prefer second-round values logged in contradiction notes
      · wipe MCP presence if no MCP-related URL was fetched
  → derive access_tier from path fields → rules-engine derive_verdict
      → buildability / blocker / unblocker / rollup
  → append row (offline full apply_guard available separately)</div>
<p><strong>Where a human was required:</strong> writing ground truth before any score,
locking the public-path assumption, defining enum boundaries (trial vs free, partner vs plan),
and deciding that cheap code guards beat further prompt-only tweaks on Flash-Lite.</p>

<h2>Data types engineered beyond the Notion brief</h2>
<p>The assignment already asked for category + one-liner, auth method(s), self-serve vs gated,
API surface (REST/GraphQL + MCP), buildability + blocker, and evidence URLs.
Those stay as the product spine. On top of that brief I added a few closed-enum signals
I expected to matter for <em>search strategy</em> and for a clean ops queue — then derived
a short tag set so clustering / cross-tabs stay decision-shaped, not exploratory ML.</p>

<p><strong>Extra atoms I added (not restating the Notion list):</strong></p>
<ul>
<li><strong><code>business_type</code></strong> — incentive prior for Call 1 only
(infra usage-based, SaaS seat-based, ad platform, data vendor, commerce, enterprise sales, AI-native).
Hypothesis: vendors who benefit from third parties hitting their API publish keys/docs where strangers find them;
partner / enterprise / ads-review businesses bury credentials differently — so the prior changes <em>where to search</em>,
not the final verdict.</li>
<li><strong><code>docs_access</code></strong> — can a stranger read docs without a sales call
(<code>public</code> / <code>login_required</code> / <code>on_request</code> / <code>none_found</code>).
Separates “API exists” from “docs are reachable enough to research.”</li>
<li><strong><code>integration_paths</code> + <code>private_path_access</code> / <code>public_path_access</code> + <code>path_evidence</code></strong> —
many vendors offer a private self-serve token <em>and</em> a public distributed app that needs review.
Composio ships multi-customer toolkits, so these fields force the public path into the record
instead of accidentally scoring the easy internal token.</li>
<li><strong><code>has_openapi_spec</code>, <code>has_webhooks</code>, <code>needs_instance_url</code>, <code>is_open_source</code></strong> —
build-convenience and setup signals beyond “is there an API.” OpenAPI speeds scaffolding;
webhooks matter for event toolkits; instance URL flags self-hosted / tenant base URLs;
open-source is its own boolean (not a business_type).</li>
<li><strong><code>flags[]</code> + confidence + short free-text notes</strong> —
machine-readable failure modes (<code>dead_url_skipped</code>, <code>second_round_used</code>,
<code>business_type_unconfirmed</code>, …) so honest unknowns stay auditable. Free text is for humans only — never clustered.</li>
</ul>

<p><strong>Derived columns (rules engine, not the LLM):</strong></p>
<ul>
<li><strong><code>access_tier</code></strong> — from path fields (Gemini does not emit the tier).
Answers the stranger-with-credentials test on the public path
(<code>self_serve_free</code> / trial / card / plan / approval / partner / no public access / unknown).</li>
<li><strong><code>access_tier_rollup</code></strong> — collapses fine tiers into a few tags:
<code>open</code> · <code>paid</code> · <code>gated</code> · <code>unknown</code>.
Kept deliberately small so category / business_type cross-tabs stay readable.</li>
<li><strong><code>buildability</code></strong> — ops verdict from rollup + API existence:
<code>easy_win</code> · <code>easy_but_paid</code> · <code>needs_review</code> · <code>needs_outreach</code> · <code>blocked</code> · <code>unknown</code>.</li>
<li><strong><code>blocker_type</code> + <code>unblocker</code></strong> (+ one-line <code>blocker</code>) —
what the wait is, and <em>who must act</em> (<code>nobody</code>, finance, vendor human, BD).
That is the queue Composio actually runs.</li>
</ul>

<p><strong>How this becomes clustering without fake ML:</strong>
the useful “clusters” are these short derived tags, not embeddings.
I kept the rollup and buildability enums small on purpose — enough tags to separate the ultimate decision
(can an engineer start today, or who has to say yes?) and not so many that every row is unique.
<code>business_type</code> clusters search behaviour; <code>access_tier_rollup</code> / <code>buildability</code> /
<code>unblocker</code> cluster the backlog for humans. Auth stays an implementation detail, not a cluster key.</p>

<h2>Verification</h2>
<p>Hand-labelled sample: {deep['sample_apps']} apps across <strong>three</strong> ground-truth sets
(4 scored fields each). Pooled: {deep['overall']['correct']} correct,
{deep['overall']['wrong']} wrong, {deep['overall']['honestly_unknown']} honestly unknown
→ <strong>{deep['overall']['correct_pct_of_base']}%</strong> of {deep['overall']['base']}.
Average of three trial overall scores: <strong>{trial_avg}%</strong>.</p>
<p><strong>Judgement vs fact:</strong> weakest is <code>access_tier</code> at {tier['correct_pct_of_base']}%;
most factual is <code>api_type</code> at {api['correct_pct_of_base']}%.
Auth {auth['correct_pct_of_base']}%; MCP {mcp['correct_pct_of_base']}%.</p>

{table(['trial', 'overall', '%', 'tier', 'auth', 'api', 'MCP'], trial_rows)}
{table(['field', 'correct/base', '%'], field_rows)}

<p><strong>One sample miss:</strong> {esc(sample_app)} · {esc(sample_field)} —
expected <code>{esc(sample_exp)}</code>, got <code>{esc(sample_act)}</code>.
Typical misses are boundary calls (trial vs free; partner vs plan) or missing first-party docs.
Same rules engine on GT and agent output → a verdict gap always traces to a fact gap.</p>

<h2>Constraints</h2>
<div class="box">
<ul>
<li><strong>Local compute.</strong> Laptop hangs under Ollama / local models, so local open-weight inference was ruled out.</li>
<li><strong>Model choice.</strong> Used Gemini Flash-Lite (free-tier) instead — weak reasoning for boundary judgements
(<code>access_tier</code> especially), but usable free API quota.</li>
<li><strong>Key rotation.</strong> Rotated through four free Gemini API keys to stay inside free quota for the 100-app run.</li>
<li><strong>Search / crawl budget.</strong> Hard cap of six Tavily search tool calls per app (plus a small second-round budget).
That limit meant many documentation links were never found or fetched → incomplete evidence
→ the model had to fill gaps → hallucinations and field errors.</li>
<li><strong>API rate limits.</strong> Free-tier Gemini + Tavily rate limits slowed runs and forced conservative budgets
(roughly two model calls and a handful of page fetches per app; no paid vendor accounts).</li>
<li><strong>No second verification agent.</strong> Budget did not allow a separate verifier pass over scored fields.</li>
<li><strong>If unconstrained, next steps would be:</strong>
(1) add a second verification agent;
(2) use a stronger reasoning model to lift judgement fields;
(3) raise search tooling from 6 → ~15 calls;
(4) allow 3–5 research rounds instead of one optional second round.</li>
<li><strong>Near-term with remaining free quota:</strong> ship three prompt fixes
(trial/free detect, MCP gated-from-page-text, tighter auth conflict handling) —
projected accuracy lift ~8 points (~60–61% → ~65–68%).</li>
</ul>
</div>

<h2>Buildability by product category</h2>
<p class="meta">Ten apps in each category. Cells are % of that category (not % of 100).</p>
{table(
    ['category', 'easy_win', 'easy_but_paid', 'needs_review', 'needs_outreach', 'blocked', 'unknown'],
    cat_pct_rows,
)}

<h2>Buildability by business_type (Call-1 prior)</h2>
<p class="meta">Same verdict mix, grouped by the incentive prior that steered search.</p>
{table(
    ['business_type', 'n', 'easy_win', 'easy_but_paid', 'needs_review', 'needs_outreach', 'blocked', 'unknown'],
    bt_pct_rows,
)}

<h2>Patterns</h2>
<ul>
<li><strong>Permission, not engineering difficulty.</strong>
{queues['engineering_ready_nobody']} of {n} are ready for an engineer today (<code>nobody</code> must act).
{queues['non_engineering_queues']} of {n} wait on vendor review, finance, or BD.
Top real blocker: <strong>{esc(h['most_common_blocker'])}</strong> ({h['most_common_blocker_count']} of {n}).</li>
<li><strong>Auth type does not predict shipability.</strong>
{e['api_key_not_easy_win']} of {e['api_key_total']} <code>api_key</code> apps are still not easy wins;
<code>oauth2</code> lands across {e['oauth2_distinct_buildability_count']} different verdicts.
Triage by who must say yes — not by how “hard” the auth looks.</li>
<li><strong>Category skew (10 apps each).</strong>
Most open access rollup: {esc(bcat['most_open_category'])} ({bcat['most_open_detail']}).
Most gated: {esc(bcat['most_gated_category'])} ({bcat['most_gated_detail']}).
Data/SEO is almost all easy wins; Ecommerce / Dev-infra skew toward vendor review.</li>
<li><strong>Business-type prior matters for search, not as the final verdict.</strong>
Call 1 clusters each app (infra usage-based, SaaS seat-based, ads, data vendor, commerce, enterprise sales, AI-native)
because companies that monetise open APIs usually put docs where strangers can find them —
enterprise / partner products usually do not. That prior steers queries; a rules engine still decides buildability.</li>
<li><strong>MCP ≠ credentials.</strong>
{g['mcp_present_not_easy_win']} of {g['mcp_present']} apps that advertise an MCP server are still not easy wins.</li>
<li><strong>Coverage holes become unknowns, not confident wrong answers when honest.</strong>
{cov['access_tier_unknown']} of {n} came back <code>access_tier=unknown</code>
(thin, missing, or paywalled docs — e.g. fanbasis, PitchBook).</li>
</ul>

</main>

<div class="full-wrap">
<main class="full">
<h2>Appendix — all {n} apps</h2>
<p class="meta">Skim the sections above first. Full matrix sorted easy → hard.</p>
{''.join(full_bits)}
<footer>
<p>Research code (public): <a href="{esc(research_repo)}">{esc(research_repo)}</a> ·
Findings generator on same repo · generated {esc(date.today().isoformat())}</p>
</footer>
</main>
</div>

<script type="application/json" id="data">{data_json}</script>
<script type="application/json" id="stats">{stats_json}</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", default="data/stats.json")
    parser.add_argument("--final", default="data/final.json")
    parser.add_argument("--out", default="index.html")
    parser.add_argument(
        "--research-repo",
        default="https://github.com/Aacashi/composio-toolkit-research",
    )
    parser.add_argument(
        "--findings-repo",
        default="https://github.com/Aacashi/composio-toolkit-findings",
    )
    args = parser.parse_args(argv)

    def R(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else ROOT / path

    import sys

    sys.path.insert(0, str(ROOT))
    from scripts.build_stats import build_stats  # noqa: E402

    final = load(R(args.final))
    gt_paths = [
        ROOT / "ground_truth.json",
        ROOT / "data" / "ground_truth_batch2.json",
        ROOT / "data" / "ground_truth_batch3.json",
    ]
    stats = build_stats(final, gt_paths)
    R(args.stats).write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    html_out = build_html(
        stats,
        final,
        research_repo=args.research_repo,
        findings_repo=args.findings_repo,
    )
    out = R(args.out)
    out.write_text(html_out, encoding="utf-8")
    print(f"[page] wrote {out} ({len(html_out)} bytes) — local only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
