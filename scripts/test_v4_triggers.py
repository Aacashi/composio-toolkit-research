"""Unit tests for V4 pricing triggers, site: ban, path evidence validation."""

from __future__ import annotations

from pipeline.gemini_client import classify_search_target, is_deep_site_query
from pipeline.nodes import (
    coerce_uncited_path_fields,
    derive_access_tier_from_paths,
    needs_second_round,
    provisional_access_tier,
    sources_have_pricing,
    validate_extract,
)


def test_sources_have_pricing():
    assert sources_have_pricing(["https://www.zendesk.com/pricing"])
    assert sources_have_pricing(["https://ahrefs.com/api/subscription"])
    assert sources_have_pricing(["https://x.com/plans"])
    assert not sources_have_pricing(["https://docs.stripe.com/api"])
    assert not sources_have_pricing([])


def test_deep_site_query_ban():
    assert is_deep_site_query("site:shopify.dev/docs/apps/auth")
    assert is_deep_site_query("site:shopify.dev/docs/api/usage/pricing-plans")
    assert not is_deep_site_query("site:shopify.dev authentication")
    assert not is_deep_site_query("site:shopify.dev pricing API")
    assert not is_deep_site_query("Shopify API pricing")


def test_classify_search_target():
    assert classify_search_target("Notion API pricing plans") == "pricing"
    assert classify_search_target("site:zendesk.com authentication") == "auth"
    assert classify_search_target("Stripe MCP server") is None


def test_validate_extract_requires_path_evidence():
    data = {
        "one_liner": "x",
        "business_type_supported": "yes",
        "docs_access": "public",
        "auth_primary": "oauth2",
        "auth_detail": "",
        "access_cost_note": "",
        "api_type": "rest",
        "has_openapi_spec": "unknown",
        "needs_instance_url": "no",
        "has_webhooks": "unknown",
        "mcp_exists": "unknown",
        "is_open_source": "no",
        "integration_paths": "two_paths",
        "private_path_access": "self_serve_free",
        "public_path_access": "approval_gated",
        "path_evidence": "review required",
        "evidence": {
            "docs_access": "https://example.com/a",
            "auth_primary": "https://example.com/a",
            "api_type": "https://example.com/a",
            "is_open_source": "https://example.com/a",
            "needs_instance_url": "https://example.com/a",
            "integration_paths": "https://example.com/a",
            # missing private/public evidence on purpose
        },
        "confidence": {},
        "notes": "",
    }
    err = validate_extract(data)
    assert err
    assert "private_path_access" in err or "public_path_access" in err


def test_coerce_uncited_path_fields():
    data = {
        "integration_paths": "two_paths",
        "private_path_access": "self_serve_free",
        "public_path_access": "approval_gated",
        "evidence": {"integration_paths": "https://x.com"},
    }
    out = coerce_uncited_path_fields(data)
    assert out["private_path_access"] == "unknown"
    assert out["public_path_access"] == "unknown"
    assert out["integration_paths"] == "two_paths"


def test_needs_second_round_pricing_missing():
    extract = {
        "integration_paths": "one_path",
        "private_path_access": "self_serve_free",
        "public_path_access": "n_a",
        "auth_primary": "api_key",
        "api_type": "rest",
        "has_openapi_spec": "yes",
        "has_webhooks": "yes",
        "mcp_exists": "none",
        "evidence": {
            "private_path_access": "https://docs.example.com/oauth",
            "integration_paths": "https://docs.example.com/oauth",
        },
    }
    missing = needs_second_round(extract, sources=["https://docs.example.com/oauth"])
    assert "pricing_coverage" in missing


def test_provisional_and_derive():
    extract = {
        "integration_paths": "two_paths",
        "private_path_access": "self_serve_free",
        "public_path_access": "approval_gated",
        "flags": [],
        "evidence": {
            "public_path_access": "https://x.com/pricing",
            "private_path_access": "https://x.com/pricing",
        },
    }
    assert provisional_access_tier(extract) == "approval_gated"
    row = derive_access_tier_from_paths(dict(extract))
    assert row["access_tier"] == "approval_gated"
    assert "path_selection_applied" in row["flags"]


if __name__ == "__main__":
    test_sources_have_pricing()
    test_deep_site_query_ban()
    test_classify_search_target()
    test_validate_extract_requires_path_evidence()
    test_coerce_uncited_path_fields()
    test_needs_second_round_pricing_missing()
    test_provisional_and_derive()
    print("test_v4_triggers: OK")
