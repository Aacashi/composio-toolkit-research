# Composio toolkit research

Stage-1 research agent that classifies apps for toolkit **buildability** (credential access gates), then a rules engine derives verdicts. Findings HTML lives in a [separate repo](https://github.com/Aacashi/composio-toolkit-findings).

## Run on another laptop

**Needs:** Python 3.11+ (3.12/3.13 fine), and API keys below.

```bash
git clone https://github.com/Aacashi/composio-toolkit-research.git
cd composio-toolkit-research

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# edit .env with your keys
```

### Keys (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | Discover + extract (Gemini Flash-Lite) |
| `TAVILY_API_KEY` | yes | Search / page extract; also used to connect Tavily in Composio |
| `COMPOSIO_API_KEY` | yes | Composio SDK (Tavily toolkit + catalog cross-check) |
| `COMPOSIO_USER_ID` | yes | Composio user/entity that has Tavily connected |
| `COMPOSIO_AUTH_CONFIG_ID` | yes | Auth config id for that Tavily connection (`ac_…`) |
| `COMPOSIO_TAVILY_VERSION` | yes | Toolkit version from Composio dashboard (see `.env.example`) |
| `COMPOSIO_CONNECTED_ACCOUNT_ID` | optional | Passed to `tools.execute` when set |

1. Create a [Gemini](https://aistudio.google.com/apikey) key and a [Tavily](https://tavily.com) key (free tier is enough for smoke tests).
2. In Composio → Toolkits → Tavily, authenticate with your Tavily key for `COMPOSIO_USER_ID`.
3. Copy the auth-config / version ids into `.env`.

If Composio’s Tavily execute fails, the client warns and falls back to direct `api.tavily.com` (still needs `TAVILY_API_KEY`).

### Smoke test (one app, nothing written to a run file)

```bash
python -m pipeline.run --app Stripe --verbose
```

You should see discover → fetch → extract stages and a JSON result in the terminal. Traces land under `debug/`; HTTP/LLM responses are cached under `cache/`.

### Batch run (writes `data/run_vN.json`)

```bash
# 10-app list
python -m pipeline.run --apps apps_10.json --resume

# full 100 (resumes; skips apps already in the latest run file)
python -m pipeline.run --apps apps_100.json --resume --batch-size 25
```

App lists live in `data/` (`apps_10.json`, `apps_100.json`, …). Use `--limit N` to cap how many apps process in one invocation.

### Offline: guards, verdicts, stats (no network)

After a Stage-1 run:

```bash
# optional cheap post-loop guards on a run file
python scripts/apply_post_loop_guards.py --in data/run_vN.json --out data/run_vN_postguard.json

# prepare final rows + derive buildability / unblocker
python scripts/prepare_final.py --in data/run_vN_postguard.json

# rules-engine counts for the findings page
python scripts/build_stats.py
python scripts/build_page.py --out index.html   # local only; publish via findings repo
```

Score against hand labels (atoms in `ground_truth.json` + `data/ground_truth_batch*.json`):

```bash
python -m eval.score --run data/final.json
```

### Windows note

Prefer `.\.venv\Scripts\python.exe -m pipeline.run ...` if activation is awkward in PowerShell.

## What this repo is / isn’t

- **Is:** research code, prompts, schema, ground truth, run artifacts you choose to commit.
- **Isn’t:** the deployed case-study page — see [composio-toolkit-findings](https://github.com/Aacashi/composio-toolkit-findings).

Enums and public-path assumptions: `DEFINITIONS.md`. Pipeline decisions: `LOGIC_FREEZE.md` / `AMENDMENT_3.md`.
