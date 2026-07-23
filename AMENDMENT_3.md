# AMENDMENT 3 — schema reduction, Tavily-only, split execution

This supersedes SPEC.md, AMENDMENTS, and LOGIC_FREEZE wherever they conflict.
Read this fully before changing any code.

Two structural changes matter most:

1. **Providers collapse to Tavily only**, connected through the Composio SDK.
   Firecrawl is removed entirely.
2. **Execution splits into three stages.** The pipeline now writes rows as soon
   as Gemini's facts are extracted. Derived fields and clustering become
   separate scripts run afterwards. The full 100 must be runnable tonight with
   derivation and clustering happening later, without re-running anything.

---

## 1. Fields removed

| field | reason |
|---|---|
| `api_breadth` | cannot be judged from 4 pages; changes no verdict |
| `docs_location` | changes no verdict |
| `rate_limit_note` | mostly unknown in practice |
| `wait_class` | fully determined by `buildability`; adds nothing |
| `business_type_confirmed` | becomes a flag, not a column |
| `auth_secondary` | folds into `auth_detail` free text |

Remove these from the schema, the prompts, the ground-truth template, the CSV
export, and the site scaffold.

---

## 2. Fields merged

**`mcp_exists` absorbs `mcp_access`.** One field, five values:

```
official_open    official MCP server, usable with normal credentials
official_gated   official MCP exists but sits behind a paid plan or waitlist
community        unofficial / third-party MCP server exists
none             checked, no MCP server exists
unknown          could not determine
```

`official_gated` is a deliberate finding. An app with an official MCP behind a
paid quota looks like an easy win and is not.

**`api_type` absorbs "does an API exist".** Six values:

```
rest        REST API
graphql     GraphQL API
both        both REST and GraphQL
cli_only    NO API at all; only a local command-line tool
none        checked, no programmatic interface of any kind
unknown     could not determine
```

`cli_only` is reserved for tools with no API whatsoever, e.g. Mermaid CLI,
Sherlock. Firecrawl ships a CLI, an MCP server, and a REST API, so Firecrawl is
`rest`. Having a CLI alongside an API is normal and does not change the tag.

---

## 3. Fields added

**`is_open_source`** — `yes` | `no` | `unknown`. Gemini fills it.

Its own boolean, not a `business_type` value. Firecrawl is open source *and*
usage-based infrastructure; a single enum cannot carry both facts.

**`access_tier_rollup`** — `open` | `paid` | `gated`. **Derived in code**, never
by Gemini.

```
open   <- open, self_serve_free, self_serve_trial
paid   <- card_required, plan_gated
gated  <- approval_gated, partner_gated, no_public_access
```

`access_tier` has nine values. Across 100 rows that averages eleven per bucket,
too thin for headline cross-tabs. The three-value rollup is what the charts use;
the full nine stay in the detail table.

---

## 4. `business_type` drops `open_source`

Seven values now:

```
infra_usage_based    revenue scales with API calls / volume consumed
saas_seat_based      revenue is per-user subscription
ad_platform          revenue from advertising or attention on their surface
data_vendor          the proprietary dataset is the product
commerce_platform    merchants pay to sell through them
enterprise_sales     contract sales only, no self-serve signup
ai_native            recently launched AI product
```

Open-source status is now carried by `is_open_source`.

---

## 5. `none` and `unknown` are never interchangeable

```
none      we checked and it genuinely does not exist
unknown   we looked and could not determine
```

This distinction must hold in every enum that has both. Collapsing them would
make "this app has no API" indistinguishable from "our agent failed here", which
destroys both the findings and the honesty section.

Enforce it in the extract prompt explicitly.

---

## 6. Final schema

### Gemini fills — facts, clustered (10)

```
business_type        7 values, see section 4
docs_access          public | login_required | on_request | none_found
access_tier          open | self_serve_free | self_serve_trial |
                     card_required | plan_gated | approval_gated |
                     partner_gated | no_public_access
auth_primary         api_key | pat | oauth2 | oauth1 | basic |
                     jwt_keypair | hmac_signed | aws_sigv4 |
                     session_only | none | unknown
api_type             rest | graphql | both | cli_only | none | unknown
mcp_exists           official_open | official_gated | community |
                     none | unknown
has_openapi_spec     yes | no | unknown
needs_instance_url   yes | no | unknown
has_webhooks         yes | no | unknown
is_open_source       yes | no | unknown
```

Note: `self_hosted` is removed from `access_tier`. Dual-mode products are
classified on their cloud path; `is_open_source` carries the rest.

### Gemini fills — free text, never clustered (4)

```
one_liner            max 15 words, what the product does
auth_detail          mechanics: header name, query param, key+secret pair,
                     token prefixes. One line, quoted or closely
                     paraphrased from docs.
access_cost_note     specific tier and price where stated
notes                anything useful for human debugging
```

### Python derives later — separate script (5)

```
access_tier_rollup   open | paid | gated
buildability         easy_win | easy_but_paid | needs_review |
                     needs_outreach | blocked | unknown
blocker_type         none | payment | vendor_review | partnership |
                     no_api | no_docs | unknown
unblocker            nobody | composio_finance | vendor_human |
                     composio_bd | n_a
blocker              one-line string, generated by the same function
```

### Audit fields

```
app_name, category, run_id
evidence{}              {field_name: url}, first-party only
confidence{}            {field_name: high|med|low}
flags[]                 unsourced | thin_content | no_docs_found |
                        schema_fail | chunked | retry_used |
                        hint_unconfirmed | business_type_unconfirmed
sources_fetched[]       every URL actually retrieved this run
first_party_domains[]   seeded in code, Gemini may only add
```

`business_type_unconfirmed` replaces the deleted `business_type_confirmed`
column: raise the flag when fetched pages do not support Call 1's guess.

### Post-run cross-check (3)

```
composio_supports       yes | no — does Composio already ship this connector
composio_auth_scheme    the auth scheme Composio uses for it
agrees_with_composio    yes | disagrees | n_a
```

Composio ships roughly 1,400 connectors. Pulling their catalog gives a free
accuracy check on `auth_primary` for the subset they already cover, plus a
coverage column showing which of the 100 are genuinely new to them.

---

## 7. Providers — Tavily only, via Composio

### Remove Firecrawl entirely

Delete `pipeline/firecrawl_client.py`, the `FIRECRAWL_API_KEY` env var, all
Firecrawl credit tracking, and every reference in README, SPEC and prompts.
It is not a fallback. It is gone.

Brave was never part of the plan. Ignore any reference to it.

### Tavily is the only web provider

```
free tier      1,000 credits/month, no card
search         1 credit (basic) — use basic, not advanced
extract        1-2 credits per 5 successful URLs
```

**Batch every extract call.** Collect all URLs for an app and send them as one
extract request of up to 5. Never extract a single URL at a time — that wastes
the batch pricing and burns the budget roughly fivefold.

Tavily `/extract` returns clean markdown directly, so it replaces the previous
scrape step entirely.

Budget:

```
100 apps x 3 searches            = 300 credits
400 URLs, batched 5 at a time    = 160 credits
second round on ~30 apps         =  60 credits
                          total  = ~520 of 1,000
```

Warn at 700, abort at 850. Log the running total after every app.

### Connect through the Composio SDK

There is a Tavily toolkit in the Composio catalog. Route search and extract
through the Composio SDK rather than calling Tavily's HTTP API directly. This
matches Composio's own reference architecture — their published deep-research
agent uses Composio-provided search with LangGraph — and makes SDK usage
structural rather than decorative.

If the toolkit does not expose the parameters needed (particularly batched
extract), fall back to calling Tavily directly, keep the same
`search_provider` interface, and state the reason in the README.

Cache search results and extract results to disk exactly as before, keyed on
query string and URL respectively. Re-runs must never re-call the API.

---

## 8. Execution sequence — this changes the flow

Three stages, run separately.

### Stage 1 — pipeline run

```
discover -> fetch -> clean -> extract -> guard -> WRITE ROW
```

The row is written **as soon as Gemini's facts pass the guard**. Derived fields
are not computed here and are absent from the written row. Composio cross-check
fields are filled inline if the catalog loaded at startup, null otherwise.

```
python -m pipeline.run --apps apps_100.json --resume --batch-size 25
```

Output: `data/run_v1.json`

### Stage 2 — derivation

```
python scripts/derive.py --run run_v1.json
```

Reads the run file, computes the five derived fields for every row using the
pure function from the logic freeze, writes `data/run_v1_derived.json`.

Runs over `ground_truth.json` identically, so human labels and agent output pass
through the same function and can never disagree on derivation.

### Stage 3 — clustering

**Do not implement.** The clustering rules will be supplied separately by the
human. When they arrive: pure pandas, `crosstab` over the enum columns, no LLM
involvement of any kind. Analysis only, on a finished derived run file.

### Why the split

The 100-app run can complete tonight. Derivation and clustering happen the next
day without re-running the pipeline or spending another credit. It also isolates
failures: a bug in the verdict function costs a five-second re-run of Stage 2,
not a full re-crawl.

---

## 9. Testing and visibility

The human previously worked in n8n and is used to watching a canvas execute.
Console and file output must give equivalent or better visibility.

### Single-app mode

```
python -m pipeline.run --app Stripe --verbose
```

Runs one app. Prints every stage to the console. Writes nothing to the run file.
This is the first thing that must work.

### Per-app debug file

Every app writes `debug/{app_name}.json` containing:

```
search queries sent
URLs returned by each search
raw markdown retrieved per URL
the exact prompt sent to Gemini
Gemini's raw response, before validation
every field the guard changed, and why
credits consumed
wall-clock duration per stage
```

When a row looks wrong, this file must show exactly which stage broke.

### Console output

Per app, print: app name, current stage, URL being fetched, credits consumed
this app, running credit total. Keep it one line per event, readable while
scrolling.

---

## 10. Build order from here

1. Strip Firecrawl out completely
2. Apply the schema changes above to `schema.py`, both prompts, the ground-truth
   template, and the CSV export
3. Wire Tavily through the Composio SDK, with batched extract
4. Add `--app` single-app mode and the `debug/` writer
5. Split `derive.py` out of the pipeline into its own script
6. Verify: `python -m pipeline.run --app Stripe --verbose` runs clean end to end
7. Stop. Report what the Stripe run produced before touching the 100.

Stage 3 stays unimplemented. The site stays placeholder-only.
