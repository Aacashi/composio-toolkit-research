"""Unit checks for Stage 2 derive_verdict (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.domains import merge_discovered_domains, seed_first_party_domains
from pipeline.verdict import assert_verdict_invariants, derive_verdict, rollup_access_tier


def test_verdict_table() -> None:
    cases = [
        ({"api_type": "cli_only"}, "blocked", "no_api", "n_a", "gated"),
        ({"api_type": "none", "docs_access": "public", "auth_primary": "api_key", "access_tier": "open"}, "blocked", "no_api", "n_a", "open"),
        ({"api_type": "rest", "docs_access": "none_found", "auth_primary": "api_key", "access_tier": "open"}, "blocked", "no_docs", "n_a", "open"),
        ({"api_type": "rest", "docs_access": "public", "auth_primary": "session_only", "access_tier": "open"}, "blocked", "no_api", "n_a", "open"),
        ({"api_type": "rest", "docs_access": "public", "auth_primary": "oauth2", "access_tier": "partner_gated"}, "needs_outreach", "partnership", "composio_bd", "gated"),
        ({"api_type": "rest", "docs_access": "public", "auth_primary": "oauth2", "access_tier": "approval_gated"}, "needs_review", "vendor_review", "vendor_human", "gated"),
        ({"api_type": "rest", "docs_access": "public", "auth_primary": "api_key", "access_tier": "plan_gated"}, "easy_but_paid", "payment", "composio_finance", "paid"),
        ({"api_type": "rest", "docs_access": "public", "auth_primary": "api_key", "access_tier": "self_serve_free"}, "easy_win", "none", "nobody", "open"),
        ({"api_type": "rest", "docs_access": "public", "auth_primary": "unknown", "access_tier": "unknown"}, "unknown", "unknown", "n_a", "gated"),
    ]
    for atoms, b, bt, u, rollup in cases:
        row = derive_verdict(dict(atoms))
        assert row["buildability"] == b, (atoms, row)
        assert row["blocker_type"] == bt, (atoms, row)
        assert row["unblocker"] == u, (atoms, row)
        assert row["access_tier_rollup"] == rollup, (atoms, row)
        assert "wait_class" not in row or row.get("wait_class") in (None, "")
        assert_verdict_invariants(row)


def test_rollup() -> None:
    assert rollup_access_tier("self_serve_trial") == "open"
    assert rollup_access_tier("card_required") == "paid"
    assert rollup_access_tier("approval_gated") == "gated"
    assert rollup_access_tier("unknown") is None


def test_cli_shortcircuit() -> None:
    row = derive_verdict({"api_type": "cli_only"})
    assert row["docs_access"] == "public"
    assert row["access_tier"] == "no_public_access"
    assert row["auth_primary"] == "none"


def test_harvest_seeds() -> None:
    app = {"app_name": "Harvest", "hint_url": "https://help.getharvest.com/api-v2"}
    seeds = seed_first_party_domains(app)
    assert "getharvest.com" in seeds and "harvestapp.com" in seeds


def test_merge_never_drops_seed() -> None:
    merged = merge_discovered_domains(["stripe.com"], ["evil-blog.com", "docs.stripe.com"])
    assert "stripe.com" in merged and "docs.stripe.com" in merged
    assert "evil-blog.com" not in merged


if __name__ == "__main__":
    test_verdict_table()
    test_rollup()
    test_cli_shortcircuit()
    test_harvest_seeds()
    test_merge_never_drops_seed()
    print("all verdict/domain checks passed")
