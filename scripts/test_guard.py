"""Unit tests for narrow absence guard (mcp / webhooks / openapi only)."""

from __future__ import annotations

from pipeline.guard import apply_absence_guard, apply_guard


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


if __name__ == "__main__":
    test_mcp_none_without_mcp_url_downgrades()
    test_mcp_none_with_mcp_url_kept()
    test_webhooks_no_without_webhook_url_downgrades()
    test_openapi_no_without_openapi_url_downgrades()
    test_auth_primary_none_not_downgraded_by_absence_guard()
    test_full_guard_still_runs_absence()
    print("test_guard: OK")
