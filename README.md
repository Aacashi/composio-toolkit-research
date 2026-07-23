# Composio Toolkit Research Agent

Research pipeline that classifies apps for Composio toolkit **buildability** (credential access gates), plus a static findings page.

**AMENDMENT_3 + Call 1 agent fix:** Tavily-only web access (via Composio SDK, with direct Tavily fallback). **Call 1 is a Gemini agent with `tavily_search` bound (max 4 tool calls)** — business-type prior drives queries. Call 2 is a no-tools extractor. Stage 2 derives verdicts later. Gemini 2.5 Flash-Lite for all LLM calls.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### API keys you must provide

| Variable | Where to get it | Used for |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) | Discover / extract / chunk-filter |
| `COMPOSIO_API_KEY` | [Composio dashboard](https://app.composio.dev) | Tavily toolkit execute + catalog cross-check |
| `COMPOSIO_USER_ID` | Composio entity / user id with Tavily connected | `tools.execute(..., user_id=...)` |
| `COMPOSIO_AUTH_CONFIG_ID` | Auth config for the Tavily connection (e.g. `ac_...`) | Stored for connection setup / debugging |
| `COMPOSIO_CONNECTED_ACCOUNT_ID` | Optional explicit connected-account id | Passed to `tools.execute` when set |
| `TAVILY_API_KEY` | [Tavily](https://tavily.com) free tier | Connect Tavily inside Composio; also direct fallback |
| `COMPOSIO_SHEETS_ID` | Optional | `--export-sheets` only |

**Connect Tavily in Composio**

1. Create a free Tavily API key (1,000 credits/month, no card).
2. In Composio dashboard → Toolkits → Tavily → authenticate with that API key for your `COMPOSIO_USER_ID`.
3. Set all env vars in `.env`.
4. Verify: `python -m pipeline.run --app Stripe --verbose`

If Composio’s Tavily toolkit cannot batch-extract, the client falls back to `https://api.tavily.com` automatically and prints `provider=direct`. That fallback is intentional and documented here.

Firecrawl is **removed**. Do not set `FIRECRAWL_API_KEY`.

## Three stages

### Stage 1 — facts only

```bash
python -m pipeline.run --app Stripe --verbose   # one app, no run file write
python -m pipeline.run --apps apps_10.json --resume
python -m pipeline.run --apps apps_100.json --resume --batch-size 25
```

Writes `data/run_vN.json` with Gemini facts + audit + composio cross-check.  
**No** `buildability` / `access_tier_rollup` yet.

Tavily credits: warn at 700, abort projected at 850. Every search/extract and Gemini call is disk-cached under `cache/`. Per-app traces land in `debug/{app}.json`.

### Stage 2 — derivation (no network)

```bash
python scripts/derive.py --run run_v1.json
# → data/run_v1_derived.json

python scripts/derive.py --gt   # ground_truth.json atoms → verdicts
```

### Stage 3 — clustering

**Not implemented.** Pure pandas crosstabs when you supply rules.

## Ground truth

1. Edit `data/ground_truth.json` — atoms only (see DEFINITIONS.md).
2. `python scripts/derive.py --gt`
3. Score a **derived** run: `python -m eval.score --run run_v1_derived.json`

## Other commands

```bash
python -m export.to_csv --run run_v1_derived.json
python -m crosscheck.composio_check --run run_v1.json
python scripts/test_verdict.py
```

## Site

```bash
cd site && npm install && npm run build
```

Placeholders only. Copy a derived run into `site/public/data.json` when ready.

## Outputs

| path | purpose |
|---|---|
| `data/run_vN.json` | Stage 1 facts |
| `data/run_vN_derived.json` | Stage 2 + verdicts |
| `debug/*.json` | Per-app traces |
| `cache/` | Tavily + Gemini caches |

## Known limitations

- Flash-Lite for all LLM calls; accuracy depends on first-party coverage + guard.
- Clustering / findings content not built yet.
- Composio catalog is a free auth cross-check only — not an answer key for access_tier.
