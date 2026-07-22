"""Rebuild atoms-only ground_truth template for the 10-app subset.

Human fills atomic fields only. Run scripts/apply_verdict.py afterwards.
Does NOT invent values from a model.
"""

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
    "business_type": "infra_usage_based | saas_seat_based | ad_platform | data_vendor | commerce_platform | enterprise_sales | open_source | ai_native",
    "business_type_confirmed": "yes | no",
    "docs_access": "public | login_required | on_request | none_found",
    "docs_location": "own_domain | docs_subdomain | third_party_host | none",
    "auth_primary": "api_key | pat | oauth2 | oauth1 | basic | jwt_keypair | hmac_signed | aws_sigv4 | session_only | none | unknown",
    "access_tier": "open | self_serve_free | self_serve_trial | card_required | plan_gated | approval_gated | partner_gated | no_public_access",
    "api_type": "rest | graphql | both | soap | sdk_only | cli_tool | none | unknown",
    "api_breadth": "narrow | medium | broad | unknown",
    "has_openapi_spec": "yes | no | unknown",
    "needs_instance_url": "yes | no | unknown",
    "has_webhooks": "yes | no | unknown",
    "mcp_exists": "official | community | none | unknown",
    "mcp_access": "same_as_api | paid_only | waitlist | n_a",
}

# Human does NOT fill these — apply_verdict.py derives them
DERIVED = ("buildability", "blocker_type", "unblocker", "wait_class", "blocker")

FREE_TEXT = [
    "one_liner",
    "auth_detail",
    "access_cost_note",
    "rate_limit_note",
    "notes",
]


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
            "auth_secondary": [],
            "first_party_domains": [],
            "evidence": {f: "" for f in ATOMIC_ALLOWED},
            "confidence": {f: "high" for f in ATOMIC_ALLOWED},
        }
        if not rows:
            row["_allowed_values"] = ATOMIC_ALLOWED
            row["_note"] = (
                "Fill ATOMS only. Leave derived fields empty; "
                "run: python scripts/apply_verdict.py"
            )
        for f in FREE_TEXT:
            row[f] = ""
        for f in ATOMIC_ALLOWED:
            row[f] = ""
        for f in DERIVED:
            row[f] = ""  # placeholder; filled by apply_verdict.py
        rows.append(row)

    out = ROOT / "data" / "ground_truth.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(rows)} atom-only template rows)")
    print("derived fields empty until: python scripts/apply_verdict.py")


if __name__ == "__main__":
    main()
