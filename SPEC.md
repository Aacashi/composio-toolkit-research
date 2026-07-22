# Composio Toolkit Research Agent — Build Spec

This file is the complete instruction set for building this project. Read it fully before writing any code.

**Author context:** this is a take-home assignment for an AI Product Ops Intern role at Composio. The deliverable is (1) a research pipeline that classifies 100 apps for toolkit buildability, and (2) a single deployed page presenting the findings. Accuracy and clarity of presentation are what is being graded, not code sophistication.

---

## 0. Build order

Build in this order. Do not skip ahead.

1. Repo scaffold + schema definitions
2. `data/apps_100.json` (the input list)
3. Pipeline nodes 1–5, runnable on a 10-app subset
4. `eval/score.py`
5. Export script (JSON → CSV)
6. Composio cross-check script
7. Next.js site with placeholders, no content

**Do not implement the clustering logic.** It is specified in section 9 for reference only. It will be reviewed and implemented separately.

---

## 1. Stack

- Python 3.10+
- LangGraph for the agent graph
- Google Gemini 2.5 Flash (both LLM calls)
- Firecrawl API for search and scrape
- Composio Python SDK (`pip install composio`) for the post-run cross-check
- Storage: JSON files on disk. No database.
- Site: Next.js, static export, deployed to Vercel

Environment variables in `.env`:
```
GEMINI_API_KEY=
FIRECRAWL_API_KEY=
COMPOSIO_API_KEY=
```

---

## 2. Repo layout

```
composio-toolkit-research/
  README.md
  DEFINITIONS.md          # generated from section 4 of this spec
  .env.example
  requirements.txt
  schema.py               # dataclasses / pydantic models + enum definitions
  prompts/
    call1_discover.txt
    call2_extract.txt
    chunk_filter.txt
  pipeline/
    graph.py              # LangGraph graph definition
    nodes.py              # individual node functions
    firecrawl_client.py   # search, scrape, disk cache
    guard.py              # deterministic post-checks, no LLM
    run.py                # CLI entrypoint
  crosscheck/
    composio_check.py
  eval/
    score.py
  export/
    to_csv.py
  data/
    apps_100.json
    apps_10.json
    ground_truth.json     # hand-filled by the human, do not generate
    run_v1.json
  cache/                  # gitignored
  site/                   # Next.js app
```

`.gitignore` must include `cache/`, `.env`, `node_modules/`, `.next/`.

---

## 3. Input data

`data/apps_100.json` — array of objects:

```json
{
  "app_name": "Zendesk",
  "category": "Support and Helpdesk",
  "hint": "zendesk.com",
  "hint_type": "domain"
}
```

`hint_type` is one of:
- `docs_url` — the hint is a direct documentation URL (e.g. `developers.notion.com`, `api.docs.dealcloud.com`). Fetch this first, before any search.
- `domain` — the hint is a marketing domain. Use it only to establish the first-party domain list. Do not treat it as a docs URL.
- `note` — the hint contains a parenthetical observation from the assignment author (e.g. `consensus.app (OAuth requested)`, `otter.ai (MCP server)`). Pass the note to Call 1 as context but **never** let it become an answer. If the claim cannot be confirmed from a first-party page, the relevant field is `unknown`.

Classify all 100 hints into these three types when building the file.

`data/apps_10.json` — subset for iteration. Use exactly these ten:
Notion, Firecrawl, Meta Ads, DealCloud, Twenty, Shopify, Ahrefs, Zendesk, Stripe, fanbasis.

---

## 4. Schema

Write this to `schema.py` and mirror it in `DEFINITIONS.md` in prose.

### 4.1 Design rules

- **Tag columns are closed enums.** No free values. Small lists.
- **Free-text columns are for human debugging only.** They are never clustered or aggregated.
- `other` is not an allowed value on any enum. If a value does not fit, use `unknown` and write the reason in `notes`.
- Extra procedural steps never change a tag. Five clicks to obtain a free API key is still `api_key` and still `easy_win`.

### 4.2 Identity

| field | type | notes |
|---|---|---|
| `app_name` | string | from input |
| `category` | string | from input, one of the 10 assignment categories |
| `one_liner` | free text | max 15 words, what the product does |

### 4.3 Business classification

**`business_type`** — enum. This is the prior that drives the search strategy.

| tag | definition | expected API posture |
|---|---|---|
| `infra_usage_based` | revenue scales with API calls, compute, or volume consumed | wide open, key-based, well documented; they want high call volume |
| `saas_seat_based` | revenue is per-user subscription | open API as a retention/stickiness feature; little reason to gate |
| `ad_platform` | revenue from advertising or attention on their own surface | docs public, but production access requires app review; agents bypass their surface |
| `data_vendor` | the proprietary dataset is the product being sold | API gated or expensive; open API would cannibalise the subscription |
| `commerce_platform` | merchants pay to sell through them | open per-merchant API; almost always requires a shop/instance URL |
| `enterprise_sales` | sold via contracts, no self-serve signup exists | docs on request; partnership required |
| `open_source` | source is public and self-hostable; no vendor gatekeeper | auth is configured by whoever hosts it |
| `ai_native` | recently launched AI product | inconsistent; some fully open, some waitlisted or invite-only |

**`business_type_confirmed`** — `yes` / `no`. Did the fetched first-party pages support the classification. A `no` is a useful finding, not an error.

### 4.4 Documentation

**`docs_access`**

| tag | meaning |
|---|---|
| `public` | readable without an account |
| `login_required` | must create an account to read the docs |
| `on_request` | docs provided only after contacting the vendor |
| `none_found` | no documentation located |

**`docs_location`**

| tag | meaning |
|---|---|
| `own_domain` | docs on the main marketing domain |
| `docs_subdomain` | dedicated docs/developers subdomain |
| `third_party_host` | hosted on GitHub, Stoplight, Readme.io, Mintlify, GitBook, Postman, or similar |
| `none` | not found |

A third-party documentation *host* (GitHub, Stoplight, Readme.io, Mintlify, GitBook, Postman, Apiary, Swagger Hub) counts as **first-party evidence** when the vendor clearly controls that page — for example `api.docs.dealcloud.com` on Stoplight, or `highlevel.stoplight.io`, or a vendor's own GitHub org. This is a documentation hosting choice, not a third-party opinion. Blogs, aggregators, comparison sites, group-buy sites, and SEO content are never first-party regardless of host.

### 4.5 Authentication

**`auth_primary`** — enum

| tag | meaning | build impact |
|---|---|---|
| `api_key` | static key from a settings page | trivial |
| `pat` | personal access token, scoped, tied to a user | trivial |
| `oauth2` | standard OAuth2 authorization code flow | standard; register one app |
| `oauth1` | OAuth 1.0a, per-request signing | painful, legacy |
| `basic` | username/email plus token or password, base64 header | trivial |
| `jwt_keypair` | client generates and signs with a key pair | moderate |
| `hmac_signed` | each request signed with a shared secret | moderate |
| `aws_sigv4` | AWS Signature Version 4 | moderate |
| `session_only` | no API auth; only browser session/cookie login exists | blocking |
| `none` | no authentication required | trivial |
| `unknown` | not stated on any first-party page reached | — |

**`auth_secondary`** — array, same enum. Many apps offer both API key and OAuth2.

**`auth_detail`** — free text, one line, describing the mechanical specifics: header name, whether the key goes in a query parameter, whether a key/secret pair is needed, whether a subdomain forms part of the credential. Quote or closely paraphrase the docs. **Never clustered.**

**Critical rule:** header-vs-query-parameter differences, key-plus-secret pairs, and multi-step key generation flows all go in `auth_detail`. They do **not** create new `auth_primary` tags and they do **not** downgrade the buildability verdict.

### 4.6 Access

**`access_tier`** — can Composio obtain working credentials.

| tag | definition |
|---|---|
| `open` | no account needed at all |
| `self_serve_free` | free signup, no payment card, credentials in minutes |
| `self_serve_trial` | free but time-limited trial |
| `card_required` | free tier exists but a payment card must be added first |
| `plan_gated` | API access only included on a specific paid tier |
| `approval_gated` | credentials obtainable, but the vendor must review and approve the app before production use |
| `partner_gated` | requires contacting sales or joining a partner programme |
| `no_public_access` | no path to credentials found |
| `self_hosted` | you run the software; credentials are self-configured |

**`access_cost_note`** — free text. Specific tier and price when known, e.g. "Advanced plan, $449/mo or above".

### 4.7 API surface

| field | type | values |
|---|---|---|
| `api_type` | enum | `rest` · `graphql` · `both` · `soap` · `sdk_only` · `none` · `unknown` |
| `api_breadth` | enum | `narrow` (<20 endpoints) · `medium` · `broad` (100+) · `unknown` |
| `has_openapi_spec` | enum | `yes` · `no` · `unknown` |
| `needs_instance_url` | enum | `yes` · `no` · `unknown` |
| `has_webhooks` | enum | `yes` · `no` · `unknown` |
| `rate_limit_note` | free text | e.g. "60 req/min, 429 on exceedance" |

`api_breadth` should default to low confidence. It cannot be judged reliably from a single page.

### 4.8 MCP

| field | values |
|---|---|
| `mcp_exists` | `official` · `community` · `none` · `unknown` |
| `mcp_access` | `same_as_api` · `paid_only` · `waitlist` · `n_a` |

These are deliberately separate. An official MCP server that draws on a paid quota is not an easy win.

### 4.9 Buildability verdict

This is the most important field. See section 6 for the full reasoning rules that go into the prompt.

**`buildability`**

| tag | definition |
|---|---|
| `easy_win` | a Composio engineer can obtain credentials and complete the toolkit alone, today, with no spend approval and no external human involved |
| `easy_but_paid` | mechanically simple, but someone internally must approve spend before work can complete. Short internal delay only |
| `needs_review` | credentials obtainable, but a human at the vendor must review and approve the application before production use. Multi-day to multi-week wait outside Composio's control |
| `needs_outreach` | no self-serve path exists. Requires contacting the vendor, negotiating, or joining a partner programme before any build can start. Multi-week to multi-month, and may fail |
| `blocked` | no usable API exists, or no documentation could be found. Not buildable now |
| `unknown` | insufficient evidence to decide |

**`blocker`** — free text, one sentence. Empty string when `easy_win`.

**`blocker_type`** — enum for clustering: `none` · `payment` · `vendor_review` · `partnership` · `no_api` · `no_docs` · `unknown`

**`unblocker`** — enum: who has to act. `nobody` · `composio_finance` · `vendor_human` · `composio_bd` · `n_a`

**`wait_class`** — enum: how long the external wait is. `none` · `hours` · `days` · `weeks` · `months` · `unknown`

`unblocker` and `wait_class` are the two axes that actually define the verdict. They are stored separately so the findings section can cross-tabulate them.

### 4.10 Evidence and audit

| field | type | notes |
|---|---|---|
| `evidence` | object `{field_name: url}` | first-party URLs only |
| `backup_links` | array of `{url, why}` | non-first-party links found during discovery. Stored for later human review, never used as evidence |
| `confidence` | object `{field_name: high\|med\|low}` | |
| `flags` | array | `unsourced` · `thin_content` · `no_docs_found` · `schema_fail` · `chunked` · `retry_used` · `hint_unconfirmed` |
| `sources_fetched` | array of urls | every page actually downloaded this run |
| `first_party_domains` | array of domains | as determined by Call 1; the guard checks against this |
| `notes` | free text | human debugging only |
| `run_id` | string | timestamp of the run |

### 4.11 Added after the run

| field | source |
|---|---|
| `composio_supports` | Composio SDK toolkit list |
| `composio_auth_scheme` | Composio SDK auth scheme lookup |
| `agrees_with_composio` | computed: `yes` · `no` · `n_a` |
| `human_verdict` | filled manually: `correct` · `partial` · `wrong` |
| `human_notes` | filled manually |

---

## 5. Pipeline

LangGraph graph. One app per graph invocation. Apps processed sequentially with a 2-second sleep between them.

```
                    [app record]
                         |
                         v
                 +---------------+
                 | NODE 1        |
                 | discover      |  Gemini 2.5 Flash + Firecrawl search tool
                 +---------------+  max 4 tool calls
                         |
                         | returns: business_type, one_liner,
                         |          first_party_domains[],
                         |          auth_url, pricing_url, api_index_url,
                         |          backup_links[]
                         v
                 +---------------+
                 | NODE 2        |
                 | fetch         |  Firecrawl scrape, disk-cached
                 +---------------+  order: auth, pricing, api_index
                         |
              +----------+----------+
              |                     |
        page > 60k chars      fetch failed / no answer
              |                     |
              v                     v
     +---------------+      +---------------+
     | NODE 2a       |      | retry once    |
     | chunk filter  |      | back to NODE 1|
     +---------------+      | with failure  |
              |             | reason        |
              |             +---------------+
              +----------+----------+
                         v
                 +---------------+
                 | NODE 3        |
                 | clean         |  pure Python, no LLM
                 +---------------+
                         |
                         v
                 +---------------+
                 | NODE 4        |
                 | extract       |  Gemini 2.5 Flash, no tools, temp 0
                 +---------------+  strict JSON output
                         |
                         v
                 +---------------+
                 | NODE 5        |
                 | guard         |  pure Python, no LLM
                 +---------------+
                         |
                         v
                 +---------------+
                 | NODE 6        |
                 | write         |  append to run_v1.json immediately
                 +---------------+
                         |
                         v
                    [next app]
```

### Node 1 — discover

Model: Gemini 2.5 Flash, with a Firecrawl search tool bound.

Hard cap: 4 tool calls. If exceeded, return whatever has been gathered.

If `hint_type` is `docs_url`, that URL is passed in as a strong seed and should be treated as the likely `api_index_url` or `auth_url` without needing a search to find it.

Returns a JSON object:
```json
{
  "one_liner": "...",
  "business_type": "data_vendor",
  "business_type_reason": "one sentence",
  "first_party_domains": ["ahrefs.com", "docs.ahrefs.com"],
  "auth_url": "https://docs.ahrefs.com/docs/authentication",
  "pricing_url": "https://ahrefs.com/pricing",
  "api_index_url": "https://docs.ahrefs.com/docs/api",
  "backup_links": [
    {"url": "https://someblog.com/ahrefs-api", "why": "third-party pricing summary"}
  ]
}
```

Any of the three URLs may be `null` if no first-party page was found. `null` is correct and expected; a third-party URL substituted in its place is a failure.

### Node 2 — fetch

For each non-null URL, in order: auth, pricing, api_index.

- Check `cache/{sha256(url)}.md` first. Hit → load. Miss → Firecrawl scrape, markdown mode, then save.
- On 403, timeout, or empty response: log the reason, skip that URL, continue.
- If a page exceeds 60,000 characters → route to Node 2a.
- If fewer than one page is successfully fetched → retry Node 1 once, passing the failure reason and asking for alternative first-party URLs. Set flag `retry_used`. Maximum one retry per app.
- If the retry also fails → proceed to Node 4 with whatever exists, or write an `unknown` row flagged `no_docs_found`.

Maximum 3 pages fetched per app.

### Node 2a — chunk filter

Triggered only when a fetched page exceeds 60,000 characters and no shorter alternative URL is available.

- Split into 15,000-character chunks.
- For each chunk, one Gemini 2.5 Flash-lite call using `prompts/chunk_filter.txt`: does this text state an authentication method, a pricing tier, an API type, or a rate limit? If yes, return the relevant sentences. If no, return `NONE`.
- Concatenate the hits. Set flag `chunked`.
- Cap at 12 chunks; beyond that, take the first 12.

### Node 3 — clean

Pure Python. No LLM. No keyword matching.

- Remove lines that contain only markdown links and no prose (navigation menus).
- Remove code blocks longer than 20 lines.
- Truncate each page to 10,000 characters.
- If a page yields fewer than 500 characters after cleaning, set flag `thin_content`.

Total input to Node 4 is therefore capped at roughly 30,000 characters per app.

### Node 4 — extract

Model: Gemini 2.5 Flash, temperature 0, no tools.

Input: each cleaned page prefixed with `=== SOURCE: {url} ===`.

Output: the full schema as JSON.

- Validate against the schema. On failure, retry once with the validation error appended to the prompt. On second failure, write a row with all enum fields set to `unknown` and flag `schema_fail`.
- Every non-`unknown` field must carry an entry in `evidence` pointing to a URL present in the input.

### Node 5 — guard

Pure Python. No LLM. Cannot fail.

For each field with a value other than `unknown`:

1. Does `evidence[field]` exist? If not → set field to `unknown`, add flag `unsourced`.
2. Is `evidence[field]` present in `sources_fetched`? If not → set field to `unknown`, add flag `unsourced`.
3. For `auth_primary`, `auth_secondary`, `access_tier`, `mcp_exists`, `mcp_access`, `has_openapi_spec`: is the evidence URL's domain in `first_party_domains`? If not → set field to `unknown`, add flag `unsourced`.

Additionally: if `hint_type` was `note` and the field the note referred to came back `unknown`, add flag `hint_unconfirmed`.

### Node 6 — write

Append the row to `data/run_v1.json` immediately, after every app. Never batch.

On startup, `run.py` reads the existing run file and skips apps already present, so an interrupted run resumes.

### Whole-run safety

- Every app wrapped in try/except. One failure never stops the run.
- Caps per app: 3 pages, 4 discovery tool calls, 1 retry, 12 chunks.
- 2-second sleep between apps for Gemini free-tier rate limits.
- Every Firecrawl response cached to disk, so re-runs after a fix cost zero credits.

---

## 6. Prompts

### 6.1 `prompts/call1_discover.txt`

Must contain, in this order:

**Section A — the eight business types.** Each with its definition and its expected API posture, copied from section 4.3 of this spec. Instruct the model to classify the app into exactly one and state whether the evidence it finds supports that classification.

**Section B — where to look, given the type.** Instruct that the business type is a *prior for where to search*, not a source of answers. For example: an `infra_usage_based` company will have prominent public docs and a quickstart; a `data_vendor` will often place API access behind a pricing tier and may not state which tier on the pricing page itself; an `enterprise_sales` company may have no public docs at all and a "contact us" path instead; an `ad_platform` will have public docs but a separate app-review process described elsewhere.

**Section C — first-party rule.** Evidence must come from pages the vendor controls. This includes vendor-controlled pages on third-party documentation hosts: GitHub, Stoplight, Readme.io, Mintlify, GitBook, Postman, Apiary, Swagger Hub. It does **not** include blogs, comparison sites, aggregators, SEO content, group-buy sites, or AI-generated review pages. If no first-party page can be found for a given need, return `null` for that URL. Returning a third-party URL in its place is an error.

**Section D — backup links.** Any useful non-first-party links found should be returned in `backup_links` with a one-line reason. These are stored for human review and are never used as evidence.

**Section E — payment gate handling.** If the pricing page indicates that API access requires a paid plan, that is the correct finding and must be recorded, with the tier named where stated. Do not attempt to work around a paywall. Do not infer which tier includes API access from a third-party source.

**Section F — output format.** The exact JSON object from section 5, Node 1.

### 6.2 `prompts/call2_extract.txt`

Must contain:

**Section A — the full schema** with every enum and its allowed values, copied from section 4.

**Section B — the evidence rule.** Every non-`unknown` field must cite a source URL that appears in the provided input. If the provided pages do not state something, the answer is `unknown`. Do not use knowledge from training. Do not infer.

**Section C — the tag stability rules.**
- Extra procedural steps do not change a tag. One click or five clicks to obtain a free API key is still `api_key`.
- Header versus query-parameter placement, key-plus-secret pairs, and multi-step generation flows all belong in `auth_detail`, not in `auth_primary`.
- `other` is never a valid value. Use `unknown` and explain in `notes`.

**Section D — the buildability reasoning rules.** Copied verbatim from section 6.3 below.

**Section E — output format.** Strict JSON matching the schema, nothing else, no markdown fences.

### 6.3 Buildability reasoning rules (goes verbatim into Call 2 prompt)

> Decide the buildability verdict by walking the full path a Composio engineer would take to ship a working toolkit for this app, from zero to a tested integration. Ask these questions in order.
>
> **1. Can the engineer obtain working credentials by themselves, today, without spending money and without any other human being involved?**
> If yes, the verdict is `easy_win`. This holds regardless of how many clicks, forms, or configuration steps the process involves, and regardless of which auth mechanism is used. A five-step free API key signup and a one-step free API key signup produce the same verdict. OAuth2 and API key produce the same verdict.
>
> **2. If not, is the only obstacle money?**
> That is, credentials are freely obtainable in a mechanical sense, but a paid plan or a payment card is required first. The verdict is `easy_but_paid`. The unblocker is internal — someone at Composio approves the spend. The external wait is zero; the internal wait is hours to days.
>
> **3. If not, does a human at the vendor have to approve something before the integration can be used in production?**
> This includes app review, developer program approval, scope review, security review, or account verification. The engineer can start building immediately in a sandbox or development mode, but cannot ship. The verdict is `needs_review`. The wait is outside Composio's control and typically runs from several days to several weeks.
>
> **4. If not, is there no self-serve path at all — meaning the engineer must first contact the vendor, negotiate access, sign an agreement, or join a partner programme before any credentials exist?**
> The verdict is `needs_outreach`. This is a business development task, not an engineering one. The wait runs from weeks to months and may never resolve.
>
> **5. If there is no usable programmatic API at all, or no documentation could be located, the verdict is `blocked`.**
>
> **6. If the app is open source and self-hosted, the verdict is `easy_win`**, because nobody outside Composio needs to say yes.
>
> **7. If the evidence gathered does not allow you to answer question 1, the verdict is `unknown`.** Do not guess.
>
> Along with the verdict, record two fields separately:
>
> - `unblocker`: who must act for this to become buildable. One of `nobody`, `composio_finance`, `vendor_human`, `composio_bd`, `n_a`.
> - `wait_class`: how long the *external* wait is, not the engineering time. One of `none`, `hours`, `days`, `weeks`, `months`, `unknown`.
>
> Engineering effort is deliberately not part of this verdict. Assume the engineering work is roughly constant across apps. What varies, and what this verdict measures, is whether someone outside the engineer's control has to say yes, and how long that takes.

---

## 7. Composio cross-check

`crosscheck/composio_check.py`, run once after the main pipeline completes.

Using the Composio Python SDK:
- List all toolkits in the Composio catalog.
- For each of the 100 apps, determine whether a matching toolkit exists (fuzzy match on slug and name; log ambiguous matches for human review rather than guessing).
- For matched apps, retrieve the auth scheme Composio uses.
- Write three fields onto each row: `composio_supports`, `composio_auth_scheme`, `agrees_with_composio`.

Mapping between Composio's auth scheme names and this project's `auth_primary` enum should live in a small explicit dictionary in this file, not be inferred at runtime.

This serves two purposes: it is an independent accuracy check on `auth_primary` for a large subset of apps at zero labelling cost, and it produces a coverage column showing which of the 100 Composio already supports.

---

## 8. Evaluation

### 8.1 Ground truth

`data/ground_truth.json` is filled **by hand, by the human, before the pipeline runs.** Do not generate it. Do not populate it from pipeline output. It uses the same schema, with all confidence values set to `high` and evidence URLs filled manually.

### 8.2 `eval/score.py`

Takes a run file and the ground truth file. Compares field by field across the enum fields only (free-text fields are not scored).

Outputs:

1. A per-field accuracy table:
```
field                 correct   accuracy
auth_primary            8/10       80%
access_tier             5/10       50%
buildability            6/10       60%
has_openapi_spec        4/10       40%
...
------------------------------------------
overall                            64%
```

2. A miss table: app name, field, expected value, actual value, flags present on that row.

The script must be runnable standalone against any run file, so accuracy across pipeline versions can be compared directly.

---

## 9. Clustering logic — SPECIFICATION ONLY, DO NOT IMPLEMENT

**Do not write this code. This section documents the intended analysis for later review.**

Once the 100 rows exist and accuracy is acceptable, the findings section will be produced by cross-tabulating the enum fields. The planned analyses:

**Primary cross-tab: `business_type` × `access_tier`.** Tests whether business model predicts gating. This is the central hypothesis of the project.

**Secondary cross-tab: `auth_primary` × `buildability`.** Tests whether auth complexity predicts buildability. The expected finding is that it does not — that apps with trivially simple `api_key` auth appear across every buildability tier — which would establish that the correct triage axis is credential access, not integration difficulty.

**Cross-tab: `unblocker` × `wait_class`.** Produces the operational triage output: how many apps need nobody, how many need finance, how many need the vendor, how many need BD, and what each of those queues costs in time.

**Distribution: `blocker_type`.** Identifies the single most common blocker across the set.

**Cross-tab: `mcp_exists` × `mcp_access`.** Tests whether MCP presence implies accessibility. Apps with `mcp_exists: official` and `mcp_access: paid_only` are the counterexample.

**Correlation: `has_openapi_spec` × `api_type`.** Tests whether spec availability predicts build speed, and whether GraphQL apps systematically lack specs.

**Agreement rate: `agrees_with_composio`.** Independent accuracy measure on `auth_primary` across all apps Composio already supports.

**Confidence distribution.** Count of `unknown` values per field, and count of rows carrying each flag. This is reported openly as a limitation rather than hidden.

---

## 10. Export

`export/to_csv.py` — flattens `run_v1.json` to a wide CSV for human review in a spreadsheet.

Flattening rule: nested `evidence` and `confidence` objects become suffixed columns. For example `auth_primary`, `auth_primary_evidence`, `auth_primary_confidence` appear as three adjacent columns. Arrays are joined with `; `.

This CSV is where the human fills `human_verdict` and `human_notes` for the verification sample. The JSON remains the single source of truth for the code and the site.

---

## 11. Site scaffold

Next.js app in `site/`, static export, deployable to Vercel.

**Build the structure and placeholders only. Do not write findings content — it does not exist yet.**

The page must be understandable by a reviewer in about two minutes with no narration. Single scrolling page. Sections in this order:

1. **Headline** — one large statement of the primary finding. Placeholder text for now.
2. **Stat band** — four to six large numbers with short labels. Placeholders.
3. **Patterns** — space for two to three cross-tab visualisations with a one-line takeaway above each. Placeholders.
4. **The table** — all 100 rows, sortable and filterable by `business_type`, `access_tier`, `buildability`, `auth_primary`. Each row expandable to show evidence URLs, `auth_detail`, `blocker`, and flags. Reads from a committed `data.json` in the site directory. Do not fetch from a remote sheet at runtime.
5. **How it was built** — space for an architecture diagram plus a short section on where a human was required. Placeholders.
6. **Verification** — space for the accuracy table, the before/after comparison across pipeline versions, and the miss table. Placeholders.
7. **What defeated the agent** — space for a list of apps where the pipeline failed, with reasons. Placeholders.
8. **Repo link.**

Design constraints: no external UI framework beyond Tailwind. Legible at a glance. The table must remain usable on a laptop screen. Prefer clear typographic hierarchy over decoration.

The page should also be easy for a machine to consume: include the full dataset as a `<script type="application/json">` block or a linked `data.json`, and use semantic headings.

---

## 12. README

Short. Must cover:
- what the project does, in three sentences
- how to install and set env vars
- how to run on the 10-app subset
- how to run on the full 100
- how to run the scorer
- how to run the Composio cross-check
- where the outputs land
- known limitations, stated plainly

---

## 13. Explicit non-goals

Do not add any of the following. They are out of scope and add cost without adding accuracy:

- vector databases or embeddings
- multi-agent debate or critic loops beyond the single guard node
- browser automation
- any database engine
- authentication or user accounts on the site
- clustering implementation (section 9 is reference only)
