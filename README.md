# Composio Toolkit Research Agent

Research pipeline that classifies apps for Composio toolkit **buildability** — focusing on credential access gates, not auth-mechanism complexity — plus a static findings page. Built for a Composio AI Product Ops Intern take-home.

Atomic facts come from Gemini Flash-Lite + Firecrawl (first-party pages only). Buildability verdicts are derived in pure Python (`derive_verdict`) so the model cannot invent inconsistent triage labels.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill GEMINI_API_KEY, FIRECRAWL_API_KEY, COMPOSIO_API_KEY
```

Site (optional):

```bash
cd site && npm install && npm run dev
```

## Run (10-app subset)

```bash
python -m pipeline.run --apps apps_10.json --resume
```

Creates the next unused `data/run_vN.json` (or resumes the file passed with `--run`). Apps already present are skipped when the file exists / `--resume` is set.

## Run (full 100)

Green the 10-app subset first. Then:

```bash
python -m pipeline.run --apps apps_100.json --resume --batch-size 25
```

Firecrawl credits are tracked; the run aborts if the projected total would exceed **450**. Every scrape/search and Gemini call is disk-cached under `cache/`.

## Score

```bash
python -m eval.score --run run_v1.json
```

Reports **primary** (`access_tier`, `auth_primary`), **derived** (separately), then **secondary** fields. Deep (10 GT apps) and shallow (Composio agreement) are never blended.

## Ground truth (atoms only)

1. Edit `data/ground_truth.json` — fill atomic enums + evidence. Do **not** hand-write verdict fields.
2. Apply the same derivation the pipeline uses:

```bash
python scripts/apply_verdict.py
```

Regenerate an empty template (wipes labels):

```bash
python scripts/build_template.py
```

## Composio cross-check

Loaded once at pipeline startup. Catalog failure **degrades** to null fields and does not stop the run. Ambiguous fuzzy matches → `composio_supports=false`, `agrees_with_composio=n_a`.

Re-run against an existing file:

```bash
python -m crosscheck.composio_check --run run_v1.json
```

Optional Sheets sink (never fails the pipeline):

```bash
python -m pipeline.run --apps apps_10.json --export-sheets
# or
python -m crosscheck.composio_check --run run_v1.json --export-sheets
```

Requires `COMPOSIO_SHEETS_ID` and a Google Sheets connected account in the Composio dashboard.

## Export CSV

```bash
python -m export.to_csv --run run_v1.json
```

## Outputs

| path | purpose |
|---|---|
| `data/run_vN.json` | versioned pipeline results (never overwrite prior N) |
| `data/ground_truth.json` | hand-labelled atoms (10 apps) |
| `cache/` | Firecrawl + Gemini caches (gitignored) |
| `site/public/data.json` | dataset for the static page |

## Data notes

- **Harvest:** first-party seeds include both `harvestapp.com` and `getharvest.com`. The hint note is a URL clarification only — it does not drive scored fields.
- **Paygent Connect:** no URL; empty domain seed; unconstrained Call 1 search. High `unknown` is expected.

## Known limitations

- Flash-Lite is used for all LLM calls; accuracy depends on first-party page coverage and guard strictness.
- `api_breadth` is low-confidence by design.
- Clustering / findings content are intentionally not implemented yet.
- Composio catalog is a free auth cross-check only — not an answer key for access tier or buildability.

## Stated assumptions (also on the site)

1. Verdicts assume the **public / distributed** toolkit path.
2. `cli_tool` rows are not connector candidates.
