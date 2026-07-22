"""Score a run file against hand-filled ground truth.

Priority order (most prominent first):
  1. access_tier, auth_primary  (primary / deep)
  2. derived fields             (reported separately)
  3. everything else            (secondary)

Deep verification = 10 hand-labelled apps vs ground_truth.json
Shallow verification = agrees_with_composio across the run (never blended)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schema import DERIVED_SCORED, PRIMARY_SCORED, SECONDARY_SCORED  # noqa: E402


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def index_by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["app_name"]: r for r in rows}


def score_field(gt: dict, pred: dict, field: str) -> bool | None:
    expected = gt.get(field)
    actual = pred.get(field)
    if expected in (None, ""):
        return None  # not labelled
    return expected == actual


def print_table(title: str, fields: tuple[str, ...], results: dict[str, list[bool]]) -> float:
    print(f"\n=== {title} ===")
    print(f"{'field':<22} {'correct':>10} {'accuracy':>10}")
    total_ok = 0
    total_n = 0
    for f in fields:
        vals = results.get(f, [])
        if not vals:
            print(f"{f:<22} {'—':>10} {'n/a':>10}")
            continue
        ok = sum(1 for v in vals if v)
        n = len(vals)
        total_ok += ok
        total_n += n
        pct = 100.0 * ok / n if n else 0.0
        print(f"{f:<22} {f'{ok}/{n}':>10} {pct:9.1f}%")
    overall = 100.0 * total_ok / total_n if total_n else 0.0
    print("-" * 44)
    print(f"{'overall':<22} {f'{total_ok}/{total_n}':>10} {overall:9.1f}%")
    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score pipeline run vs ground truth")
    parser.add_argument("--run", required=True, help="run_vN.json path")
    parser.add_argument(
        "--gt",
        default=str(ROOT / "data" / "ground_truth.json"),
        help="ground_truth.json path",
    )
    args = parser.parse_args(argv)

    run_path = Path(args.run)
    if not run_path.is_absolute():
        run_path = ROOT / "data" / run_path
    gt_path = Path(args.gt)
    if not gt_path.is_absolute():
        gt_path = ROOT / gt_path

    run_rows = load_json(run_path)
    gt_rows = load_json(gt_path)
    gt_idx = index_by_name(gt_rows)
    run_idx = index_by_name(run_rows)

    primary: dict[str, list[bool]] = defaultdict(list)
    secondary: dict[str, list[bool]] = defaultdict(list)
    derived: dict[str, list[bool]] = defaultdict(list)
    misses: list[tuple[str, str, str, str, list]] = []

    labelled = 0
    confirmed_no = 0
    confirmed_total = 0

    for name, gt in gt_idx.items():
        pred = run_idx.get(name)
        if not pred:
            print(f"[score] missing from run: {name}")
            continue
        labelled += 1

        bt_conf = pred.get("business_type_confirmed")
        if bt_conf in ("yes", "no"):
            confirmed_total += 1
            if bt_conf == "no":
                confirmed_no += 1

        for field in PRIMARY_SCORED:
            hit = score_field(gt, pred, field)
            if hit is None:
                continue
            primary[field].append(hit)
            if not hit:
                misses.append(
                    (name, field, str(gt.get(field)), str(pred.get(field)), pred.get("flags") or [])
                )

        for field in SECONDARY_SCORED:
            hit = score_field(gt, pred, field)
            if hit is None:
                continue
            secondary[field].append(hit)
            if not hit:
                misses.append(
                    (name, field, str(gt.get(field)), str(pred.get(field)), pred.get("flags") or [])
                )

        for field in DERIVED_SCORED:
            hit = score_field(gt, pred, field)
            if hit is None:
                continue
            derived[field].append(hit)
            if not hit:
                misses.append(
                    (name, field, str(gt.get(field)), str(pred.get(field)), pred.get("flags") or [])
                )

    print(f"Deep verification apps compared: {labelled}")
    print_table("PRIMARY (deep)", PRIMARY_SCORED, primary)
    print_table("DERIVED (inherited — report separately)", DERIVED_SCORED, derived)
    print_table("SECONDARY (deep)", SECONDARY_SCORED, secondary)

    # business_type_confirmed=no rate across the full run (finding, not failure)
    run_conf_no = sum(1 for r in run_rows if r.get("business_type_confirmed") == "no")
    run_conf_n = sum(1 for r in run_rows if r.get("business_type_confirmed") in ("yes", "no"))
    if run_conf_n:
        print(
            f"\nbusiness_type_confirmed=no rate (full run): "
            f"{run_conf_no}/{run_conf_n} ({100.0 * run_conf_no / run_conf_n:.1f}%)"
        )

    # Shallow: Composio agreement — never blended into deep overall
    agrees = [r for r in run_rows if r.get("agrees_with_composio") in ("yes", "disagrees")]
    yes = sum(1 for r in agrees if r.get("agrees_with_composio") == "yes")
    print("\n=== SHALLOW verification (Composio auth agreement) ===")
    if agrees:
        print(f"agrees_with_composio  {yes}/{len(agrees)}  {100.0 * yes / len(agrees):.1f}%")
    else:
        print("agrees_with_composio  n/a (no matched toolkits or catalog unavailable)")
    print("(Deep and shallow are separate numbers — never blended.)")

    print("\n=== Miss table ===")
    print(f"{'app':<24} {'field':<20} {'expected':<20} {'actual':<20} flags")
    for app, field, exp, act, flags in misses:
        print(f"{app:<24} {field:<20} {exp:<20} {act:<20} {flags}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
