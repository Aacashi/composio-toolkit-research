"""CLI entrypoint: versioned run files, resume, credit budget, optional sheets export."""

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
from pipeline.firecrawl_client import CreditTracker, FirecrawlClient  # noqa: E402
from pipeline.graph import process_one_app  # noqa: E402

DATA = ROOT / "data"
SLEEP_BETWEEN_APPS = 2.0
BATCH_SIZE = 25
CREDIT_LIMIT = 450


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


def load_apps(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_run(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_run(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Composio toolkit research pipeline")
    parser.add_argument(
        "--apps",
        default="apps_10.json",
        help="Apps JSON under data/ (default: apps_10.json)",
    )
    parser.add_argument(
        "--run",
        default=None,
        help="Run file path or name (default: next unused data/run_vN.json)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip apps already present in the run file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N apps from the input list",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help="Abort projection checked every batch (default 25)",
    )
    parser.add_argument(
        "--export-sheets",
        action="store_true",
        help="After run, optionally push rows to Sheets via Composio (never fails pipeline)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=SLEEP_BETWEEN_APPS,
        help="Seconds between apps",
    )
    args = parser.parse_args(argv)

    apps_path = DATA / args.apps if not Path(args.apps).is_absolute() else Path(args.apps)
    apps = load_apps(apps_path)
    if args.limit is not None:
        apps = apps[: args.limit]

    run_path = next_run_path(args.run)
    # If --run points at existing file, use it (resume-friendly)
    if args.run:
        run_path = Path(args.run)
        if not run_path.is_absolute():
            run_path = DATA / run_path

    rows = load_run(run_path) if (args.resume or run_path.exists()) else []
    done_names = {r.get("app_name") for r in rows}
    pending = [a for a in apps if a["app_name"] not in done_names] if args.resume or rows else list(apps)

    print(f"[run] apps={len(apps)} pending={len(pending)} out={run_path}")

    catalog = load_catalog()  # degrades to None on failure
    tracker = CreditTracker(limit=CREDIT_LIMIT)
    fc = FirecrawlClient(tracker=tracker)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    apps_total = len(apps)
    apps_done_before = len(done_names)
    processed_this_session = 0

    for i, app in enumerate(pending):
        # credit projection abort
        remaining_in_batch = min(args.batch_size, len(pending) - i)
        if not tracker.projected_ok(
            apps_done_before + processed_this_session,
            apps_total,
            remaining_in_batch,
        ):
            print("[run] aborting for credit budget; partial run saved")
            break

        print(f"[run] ({i+1}/{len(pending)}) {app['app_name']}")
        composio = attach_composio_to_row(app["app_name"], catalog)
        row = process_one_app(app, fc, run_id=run_id, composio_fields=composio)
        rows.append(row)
        save_run(run_path, rows)
        processed_this_session += 1

        if i < len(pending) - 1:
            time.sleep(args.sleep)

    print(f"[run] complete rows={len(rows)} credits={tracker.total} file={run_path}")
    print("[run] per-app credits:", json.dumps(tracker.per_app, indent=2))

    if args.export_sheets:
        maybe_export_sheets(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
