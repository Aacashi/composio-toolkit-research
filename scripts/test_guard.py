"""Unit tests for Stage-1 guards (unsourced, absence, presence, none_found)."""

from __future__ import annotations

from pipeline.guard import (
    apply_absence_guard,
    apply_guard,
    canonicalize_url,
    enforce_evidence_subset,
    url_in_sources,
)


def _base_row(**overrides):
    row = {
        "app_name": "Stripe",
        "docs_access": "public",
        "auth_primary": "api_key",
        "access_tier": "self_serve_free",
        "api_type": "rest",
        "has_openapi_spec": "yes",
        "has_webhooks": "yes",
        "mcp_exists": "none",
        "is_open_source": "no",
        "needs_instance_url": "no",
        "evidence": {
            "mcp_exists": "https://docs.stripe.com/api",
            "auth_primary": "https://docs.stripe.com/api",
            "access_tier": "https://stripe.com/pricing",
            "api_type": "https://docs.stripe.com/api",
            "has_openapi_spec": "https://github.com/stripe/openapi",
            "has_webhooks": "https://docs.stripe.com/webhooks",
            "is_open_source": "https://github.com/stripe/openapi",
            "docs_access": "https://docs.stripe.com/api",
            "needs_instance_url": "https://docs.stripe.com/api",
        },
        "sources_fetched": [
            "https://docs.stripe.com/api",
            "https://stripe.com/pricing",
            "https://github.com/stripe/openapi",
            "https://docs.stripe.com/webhooks",
        ],
        "first_party_domains": ["stripe.com", "github.com"],
        "flags": [],
    }
    row.update(overrides)
    return row


def test_canonicalize_strips_www_and_slash():
    a = canonicalize_url("https://www.Notion.com/pricing/")
    b = canonicalize_url("https://notion.com/pricing")
    assert a == b


def test_mcp_none_without_mcp_url_downgrades():
    row = apply_absence_guard(_base_row(mcp_exists="none"))
    assert row["mcp_exists"] == "unknown"
    assert "unsupported_absence" in row["flags"]
    assert "mcp_exists" not in row["evidence"]


def test_mcp_none_with_mcp_url_kept():
    row = _base_row(
        mcp_exists="none",
        sources_fetched=[
            "https://docs.stripe.com/api",
            "https://docs.stripe.com/mcp",
        ],
        evidence={"mcp_exists": "https://docs.stripe.com/mcp"},
    )
    out = apply_absence_guard(row)
    assert out["mcp_exists"] == "none"
    assert "unsupported_absence" not in out["flags"]


def test_webhooks_no_without_webhook_url_downgrades():
    row = apply_absence_guard(
        _base_row(
            has_webhooks="no",
            sources_fetched=["https://docs.stripe.com/api", "https://stripe.com/pricing"],
            evidence={"has_webhooks": "https://docs.stripe.com/api"},
        )
    )
    assert row["has_webhooks"] == "unknown"
    assert "unsupported_absence" in row["flags"]


def test_openapi_no_without_openapi_url_downgrades():
    row = apply_absence_guard(
        _base_row(
            has_openapi_spec="no",
            sources_fetched=["https://docs.stripe.com/api"],
            evidence={"has_openapi_spec": "https://docs.stripe.com/api"},
        )
    )
    assert row["has_openapi_spec"] == "unknown"


def test_auth_primary_none_not_downgraded_by_absence_guard():
    """api_type / auth_primary are prompt-only — absence guard must not touch them."""
    row = apply_absence_guard(
        _base_row(
            auth_primary="none",
            mcp_exists="unknown",
            sources_fetched=["https://example.com/pricing"],
            evidence={"auth_primary": "https://example.com/pricing"},
        )
    )
    assert row["auth_primary"] == "none"
    assert "unsupported_absence" not in row["flags"]


def test_full_guard_still_runs_absence():
    row = apply_guard(_base_row(mcp_exists="none"))
    assert row["mcp_exists"] == "unknown"
    assert "unsupported_absence" in row["flags"]


def test_notion_like_unsourced_cites_downgrade():
    """1 fetched source; 3 cited URLs none of which match -> unsourced."""
    row = apply_guard(
        {
            "app_name": "Notion",
            "docs_access": "public",
            "auth_primary": "oauth2",
            "access_tier": "self_serve_free",
            "api_type": "rest",
            "has_openapi_spec": "unknown",
            "has_webhooks": "unknown",
            "mcp_exists": "official_open",
            "is_open_source": "no",
            "needs_instance_url": "no",
            "evidence": {
                "auth_primary": "https://developers.notion.com/reference/authentication",
                "access_tier": "https://www.notion.com/pricing",
                "mcp_exists": "https://developers.notion.com/guides/mcp/overview",
                "docs_access": "https://developers.notion.com/reference/authentication",
                "api_type": "https://developers.notion.com/reference/authentication",
                "is_open_source": "https://developers.notion.com/reference/authentication",
                "needs_instance_url": "https://developers.notion.com/reference/authentication",
            },
            "sources_fetched": ["https://www.notion.com/connections/spexdock"],
            "first_party_domains": ["notion.com", "developers.notion.com"],
            "flags": [],
        }
    )
    assert row["auth_primary"] == "unknown"
    assert row["access_tier"] == "unknown"
    assert row["mcp_exists"] == "unknown"
    assert "unsourced" in row["flags"]
    for k in ("auth_primary", "access_tier", "mcp_exists"):
        assert k not in row["evidence"]


def test_fanbasis_presence_without_mcp_url():
    row = apply_guard(
        _base_row(
            app_name="fanbasis",
            docs_access="public",
            mcp_exists="official_open",
            has_webhooks="unknown",
            has_openapi_spec="unknown",
            sources_fetched=["https://www.fanbasis.com"],
            evidence={
                "mcp_exists": "https://www.fanbasis.com",
                "docs_access": "https://www.fanbasis.com",
                "auth_primary": "https://www.fanbasis.com",
                "access_tier": "https://www.fanbasis.com",
                "api_type": "https://www.fanbasis.com",
                "is_open_source": "https://www.fanbasis.com",
                "needs_instance_url": "https://www.fanbasis.com",
            },
            first_party_domains=["fanbasis.com"],
        )
    )
    assert row["mcp_exists"] == "unknown"
    assert "unsupported_presence" in row["flags"]


def test_docs_none_found_wipes_capabilities():
    row = apply_guard(
        _base_row(
            docs_access="none_found",
            auth_primary="api_key",
            access_tier="self_serve_free",
            api_type="rest",
            mcp_exists="official_open",
            has_webhooks="yes",
            has_openapi_spec="yes",
            sources_fetched=["https://www.fanbasis.com"],
            evidence={
                "docs_access": "https://www.fanbasis.com",
                "auth_primary": "https://www.fanbasis.com",
                "access_tier": "https://www.fanbasis.com",
                "api_type": "https://www.fanbasis.com",
                "mcp_exists": "https://www.fanbasis.com",
                "has_webhooks": "https://www.fanbasis.com",
                "has_openapi_spec": "https://www.fanbasis.com",
                "is_open_source": "https://www.fanbasis.com",
                "needs_instance_url": "https://www.fanbasis.com",
            },
            first_party_domains=["fanbasis.com"],
        )
    )
    assert row["auth_primary"] == "unknown"
    assert row["access_tier"] == "unknown"
    assert row["api_type"] == "unknown"
    assert row["mcp_exists"] == "unknown"
    assert "docs_none_capabilities" in row["flags"]


def test_invariant_no_evidence_outside_sources():
    row = apply_guard(
        _base_row(
            auth_primary="api_key",
            sources_fetched=["https://docs.stripe.com/api"],
            evidence={
                "auth_primary": "https://docs.stripe.com/api",
                "docs_access": "https://docs.stripe.com/api",
                "access_tier": "https://stripe.com/pricing",  # not fetched
                "api_type": "https://docs.stripe.com/api",
                "is_open_source": "https://docs.stripe.com/api",
                "needs_instance_url": "https://docs.stripe.com/api",
                "has_webhooks": "https://docs.stripe.com/webhooks",
                "has_openapi_spec": "https://github.com/stripe/openapi",
                "one_liner": "https://invented.example/page",
            },
            access_tier="self_serve_free",
            has_webhooks="yes",
            has_openapi_spec="yes",
            mcp_exists="unknown",
        )
    )
    sources = row["sources_fetched"]
    for _k, ev in (row.get("evidence") or {}).items():
        assert url_in_sources(ev, sources), (_k, ev)


def test_enforce_evidence_subset_flags_invariant():
    row = {
        "app_name": "X",
        "auth_primary": "api_key",
        "evidence": {"auth_primary": "https://evil.example/x"},
        "sources_fetched": ["https://good.example/y"],
        "flags": [],
    }
    out = enforce_evidence_subset(row)
    assert out["auth_primary"] == "unknown"
    assert "guard_invariant_fail" in out["flags"]
    assert "auth_primary" not in out["evidence"]


if __name__ == "__main__":
    test_canonicalize_strips_www_and_slash()
    test_mcp_none_without_mcp_url_downgrades()
    test_mcp_none_with_mcp_url_kept()
    test_webhooks_no_without_webhook_url_downgrades()
    test_openapi_no_without_openapi_url_downgrades()
    test_auth_primary_none_not_downgraded_by_absence_guard()
    test_full_guard_still_runs_absence()
    test_notion_like_unsourced_cites_downgrade()
    test_fanbasis_presence_without_mcp_url()
    test_docs_none_found_wipes_capabilities()
    test_invariant_no_evidence_outside_sources()
    test_enforce_evidence_subset_flags_invariant()
    print("test_guard: OK")
