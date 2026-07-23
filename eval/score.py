"""Score Stage 2 derived run vs hand-filled ground truth (AMENDMENT_3)."""

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
        return None
    return expected == actual


def print_table(title: str, fields: tuple[str, ...], results: dict[str, list[bool]]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'field':<22} {'correct':>10} {'accuracy':>10}")
    total_ok = total_n = 0
    for f in fields:
        vals = results.get(f, [])
        if not vals:
            print(f"{f:<22} {'—':>10} {'n/a':>10}")
            continue
        ok = sum(1 for v in vals if v)
        n = len(vals)
        total_ok += ok
        total_n += n
        print(f"{f:<22} {f'{ok}/{n}':>10} {100.0 * ok / n:9.1f}%")
    overall = 100.0 * total_ok / total_n if total_n else 0.0
    print("-" * 44)
    print(f"{'overall':<22} {f'{total_ok}/{total_n}':>10} {overall:9.1f}%")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Prefer run_vN_derived.json")
    parser.add_argument("--gt", default=str(ROOT / "data" / "ground_truth.json"))
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
    misses: list = []
    labelled = 0

    for name, gt in gt_idx.items():
        pred = run_idx.get(name)
        if not pred:
            print(f"[score] missing from run: {name}")
            continue
        labelled += 1
        for field, bucket in (
            *((f, primary) for f in PRIMARY_SCORED),
            *((f, secondary) for f in SECONDARY_SCORED),
            *((f, derived) for f in DERIVED_SCORED),
        ):
            hit = score_field(gt, pred, field)
            if hit is None:
                continue
            bucket[field].append(hit)
            if not hit:
                misses.append(
                    (name, field, str(gt.get(field)), str(pred.get(field)), pred.get("flags") or [])
                )

    print(f"Deep verification apps compared: {labelled}")
    print_table("PRIMARY (deep)", PRIMARY_SCORED, primary)
    print_table("DERIVED (inherited — report separately)", DERIVED_SCORED, derived)
    print_table("SECONDARY (deep)", SECONDARY_SCORED, secondary)

    unconfirmed = sum(
        1 for r in run_rows if "business_type_unconfirmed" in (r.get("flags") or [])
    )
    print(
        f"\nbusiness_type_unconfirmed flag rate (full run): "
        f"{unconfirmed}/{len(run_rows)} ({100.0 * unconfirmed / max(len(run_rows),1):.1f}%)"
    )

    agrees = [r for r in run_rows if r.get("agrees_with_composio") in ("yes", "disagrees")]
    yes = sum(1 for r in agrees if r.get("agrees_with_composio") == "yes")
    print("\n=== SHALLOW verification (Composio auth agreement) ===")
    if agrees:
        print(f"agrees_with_composio  {yes}/{len(agrees)}  {100.0 * yes / len(agrees):.1f}%")
    else:
        print("agrees_with_composio  n/a")
    print("(Deep and shallow are separate numbers — never blended.)")

    print("\n=== Miss table ===")
    for app, field, exp, act, flags in misses:
        print(f"{app:<24} {field:<20} {exp:<20} {act:<20} {flags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
