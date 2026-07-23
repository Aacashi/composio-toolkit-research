"""CLI — Stage 1 pipeline (facts only). AMENDMENT_3."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crosscheck.composio_check import (  # noqa: E402
    attach_composio_to_row,
    load_catalog,
    maybe_export_sheets,
)
from pipeline.graph import process_one_app  # noqa: E402
from pipeline.tavily_client import CreditTracker, TavilyClient  # noqa: E402

DATA = ROOT / "data"
SLEEP_BETWEEN_APPS = 10.0
BATCH_SIZE = 25


def next_run_path(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = DATA / p
        return p
    n = 1
    while True:
        candidate = DATA / f"run_v{n}.json"
        if not candidate.exists():
            return candidate
        n += 1


def latest_run_path() -> Path | None:
    """Highest existing data/run_vN.json, or None."""
    latest: Path | None = None
    n = 1
    while True:
        candidate = DATA / f"run_v{n}.json"
        if not candidate.exists():
            return latest
        latest = candidate
        n += 1


def load_apps(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_app(name: str) -> dict:
    for fname in ("apps_100.json", "apps_10.json"):
        apps = load_apps(DATA / fname)
        for a in apps:
            if a["app_name"].lower() == name.lower():
                return a
    raise SystemExit(f"app not found: {name}")


def load_run(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_run(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Composio toolkit research — Stage 1")
    parser.add_argument("--apps", default="apps_10.json")
    parser.add_argument("--run", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--export-sheets", action="store_true")
    parser.add_argument("--sleep", type=float, default=SLEEP_BETWEEN_APPS)
    parser.add_argument(
        "--app",
        default=None,
        help="Run a single app by name. Prints stages; writes NOTHING to run file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose console output (implied by --app).",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or bool(args.app)

    # Single-app dry mode
    if args.app:
        app = find_app(args.app)
        print(f"[run] single-app mode: {app['app_name']} (no run file write)")
        catalog = load_catalog()
        tracker = CreditTracker()
        tv = TavilyClient(tracker=tracker, verbose=verbose)
        composio = attach_composio_to_row(app["app_name"], catalog)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        row = process_one_app(
            app, tv, run_id=run_id, composio_fields=composio, verbose=verbose
        )
        print("[run] RESULT (not saved):")
        print(json.dumps(row, indent=2, ensure_ascii=False)[:8000])
        print(f"[run] credits app={tracker.per_app.get(app['app_name'], 0)} total={tracker.total}")
        print(f"[run] tavily provider={tv.mode}")
        return 0

    apps_path = DATA / args.apps if not Path(args.apps).is_absolute() else Path(args.apps)
    apps = load_apps(apps_path)
    if args.limit is not None:
        apps = apps[: args.limit]

    if args.run:
        run_path = Path(args.run)
        if not run_path.is_absolute():
            run_path = DATA / run_path
    elif args.resume:
        # Continue the latest run file so apps_10 then apps_100 share one file.
        run_path = latest_run_path() or next_run_path()
    else:
        run_path = next_run_path()

    rows = load_run(run_path) if (args.resume or run_path.exists()) else []
    # Treat schema_fail / pipeline exceptions as not done so --resume retries them.
    done_names = {
        r.get("app_name")
        for r in rows
        if r.get("app_name")
        and "schema_fail" not in (r.get("flags") or [])
        and not str(r.get("notes") or "").startswith("pipeline exception")
    }
    pending = (
        [a for a in apps if a["app_name"] not in done_names]
        if args.resume or rows
        else list(apps)
    )

    print(f"[run] apps={len(apps)} pending={len(pending)} out={run_path}")
    if done_names:
        print(f"[run] already filled ({len(done_names)}): {sorted(done_names)}")

    catalog = load_catalog()
    tracker = CreditTracker()
    tv = TavilyClient(tracker=tracker, verbose=verbose)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    apps_total = len(apps)
    processed = 0

    for i, app in enumerate(pending):
        if processed > 0:
            remaining = len(pending) - i
            if not tracker.projected_ok(processed, apps_total, remaining):
                print("[run] aborting for credit budget; partial run saved")
                break

        print(f"[run] ({i+1}/{len(pending)}) {app['app_name']}")
        composio = attach_composio_to_row(app["app_name"], catalog)
        row = process_one_app(
            app, tv, run_id=run_id, composio_fields=composio, verbose=verbose
        )
        # Replace any prior failed row for this app
        rows = [r for r in rows if r.get("app_name") != app["app_name"]]
        rows.append(row)
        save_run(run_path, rows)
        processed += 1
        print(
            f"[run] wrote {app['app_name']} credits_app="
            f"{tracker.per_app.get(app['app_name'], 0)} total={tracker.total}"
        )

        if i < len(pending) - 1:
            time.sleep(args.sleep)

    print(f"[run] complete rows={len(rows)} credits={tracker.total} file={run_path}")
    print(f"[run] tavily provider={tv.mode}")
    print("[run] per-app credits:", json.dumps(tracker.per_app, indent=2))

    if args.export_sheets:
        maybe_export_sheets(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
