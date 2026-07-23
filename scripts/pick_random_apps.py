"""Pick N random apps from apps_100.json (or another apps list)."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Randomly sample apps into a new apps JSON")
    parser.add_argument(
        "--from",
        dest="infile",
        default="data/apps_100.json",
        help="Source apps JSON (default: data/apps_100.json)",
    )
    parser.add_argument(
        "--out",
        default="data/apps_10_random.json",
        help="Output path (default: data/apps_10_random.json)",
    )
    parser.add_argument("-n", type=int, default=10, help="How many apps to pick (default: 10)")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducible picks",
    )
    args = parser.parse_args(argv)

    in_path = Path(args.infile)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    apps = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(apps, list) or not apps:
        raise SystemExit(f"expected a non-empty JSON list in {in_path}")
    if args.n < 1:
        raise SystemExit("-n must be >= 1")
    if args.n > len(apps):
        raise SystemExit(f"-n={args.n} exceeds pool size {len(apps)}")

    rng = random.Random(args.seed)
    picked = rng.sample(apps, args.n)
    # Stable order by original id when present
    picked.sort(key=lambda a: (a.get("id") is None, a.get("id") or 0, a.get("app_name") or ""))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(picked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    names = [a.get("app_name") for a in picked]
    seed_note = f" seed={args.seed}" if args.seed is not None else " seed=None"
    print(f"[pick] {len(picked)} apps{seed_note} -> {out_path}")
    for name in names:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
