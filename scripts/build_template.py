"""Rebuild atoms-only ground_truth template (AMENDMENT_3)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEN_NAMES = [
    "Notion",
    "Firecrawl",
    "Meta Ads",
    "DealCloud",
    "Twenty",
    "Shopify",
    "Ahrefs",
    "Zendesk",
    "Stripe",
    "fanbasis",
]

ATOMIC_ALLOWED = {
    "business_type": "infra_usage_based | saas_seat_based | ad_platform | data_vendor | commerce_platform | enterprise_sales | ai_native",
    "docs_access": "public | login_required | on_request | none_found",
    "auth_primary": "api_key | pat | oauth2 | oauth1 | basic | jwt_keypair | hmac_signed | aws_sigv4 | session_only | none | unknown",
    "access_tier": "open | self_serve_free | self_serve_trial | card_required | plan_gated | approval_gated | partner_gated | no_public_access",
    "api_type": "rest | graphql | both | cli_only | none | unknown",
    "has_openapi_spec": "yes | no | unknown",
    "needs_instance_url": "yes | no | unknown",
    "has_webhooks": "yes | no | unknown",
    "mcp_exists": "official_open | official_gated | community | none | unknown",
    "is_open_source": "yes | no | unknown",
}

DERIVED = (
    "access_tier_rollup",
    "buildability",
    "blocker_type",
    "unblocker",
    "blocker",
)

FREE_TEXT = ["one_liner", "auth_detail", "access_cost_note", "notes"]


def main() -> None:
    apps10 = json.loads((ROOT / "data" / "apps_10.json").read_text(encoding="utf-8"))
    by_name = {a["app_name"]: a for a in apps10}
    rows = []
    for name in TEN_NAMES:
        app = by_name.get(name) or {"app_name": name, "category": "", "hint_url": ""}
        row = {
            "app_name": name,
            "category": app.get("category", ""),
            "hint_url": app.get("hint_url") or "",
            "first_party_domains": [],
            "evidence": {f: "" for f in ATOMIC_ALLOWED},
            "confidence": {f: "high" for f in ATOMIC_ALLOWED},
        }
        if not rows:
            row["_allowed_values"] = ATOMIC_ALLOWED
            row["_note"] = (
                "Fill ATOMS only. Leave derived empty; "
                "run: python scripts/derive.py --gt"
            )
        for f in FREE_TEXT:
            row[f] = ""
        for f in ATOMIC_ALLOWED:
            row[f] = ""
        for f in DERIVED:
            row[f] = ""
        rows.append(row)

    out = ROOT / "data" / "ground_truth.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(rows)} atom-only template rows)")


if __name__ == "__main__":
    main()
