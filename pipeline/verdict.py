"""Deterministic derivation — Stage 2 only (AMENDMENT_3)."""

from __future__ import annotations

from typing import Any

from schema import AccessTierRollup, BlockerType, Buildability, Unblocker

BLOCKER_TEXT = {
    "cli_only": "Local CLI only; no vendor API for Composio to connect to.",
    "no_api": "No usable programmatic API found.",
    "no_docs": "No documentation located on first-party sources.",
    "session_only": "Only browser session/cookie auth exists; no API credentials.",
    "partnership": "No self-serve path; partner programme or sales outreach required.",
    "vendor_review": "Vendor must review and approve before production use.",
    "payment": "Credentials require a paid plan or payment card first.",
    "unknown": "Insufficient first-party evidence to decide buildability.",
}

CLI_SHORTCIRCUIT_FIELDS = frozenset(
    {
        "docs_access",
        "access_tier",
        "auth_primary",
        "access_tier_rollup",
        "buildability",
        "unblocker",
        "blocker_type",
        "blocker",
    }
)

ROLLUP_OPEN = frozenset({"open", "self_serve_free", "self_serve_trial"})
ROLLUP_PAID = frozenset({"card_required", "plan_gated"})
ROLLUP_GATED = frozenset({"approval_gated", "partner_gated", "no_public_access"})


def rollup_access_tier(access_tier: str | None) -> str | None:
    t = access_tier or "unknown"
    if t in ROLLUP_OPEN:
        return AccessTierRollup.open.value
    if t in ROLLUP_PAID:
        return AccessTierRollup.paid.value
    if t in ROLLUP_GATED:
        return AccessTierRollup.gated.value
    return None


def apply_cli_shortcircuit(row: dict[str, Any]) -> dict[str, Any]:
    row["docs_access"] = "public"
    row["access_tier"] = "no_public_access"
    row["auth_primary"] = "none"
    row["access_tier_rollup"] = AccessTierRollup.gated.value
    row["buildability"] = Buildability.blocked.value
    row["unblocker"] = Unblocker.n_a.value
    row["blocker_type"] = BlockerType.no_api.value
    row["blocker"] = BLOCKER_TEXT["cli_only"]
    return row


def derive_verdict(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("api_type") == "cli_only":
        return apply_cli_shortcircuit(row)

    api_type = row.get("api_type") or "unknown"
    docs_access = row.get("docs_access") or "unknown"
    auth_primary = row.get("auth_primary") or "unknown"
    access_tier = row.get("access_tier") or "unknown"

    if api_type in ("cli_only", "none"):
        buildability = Buildability.blocked.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.no_api.value
        blocker = BLOCKER_TEXT["no_api"]
    elif docs_access == "none_found":
        buildability = Buildability.blocked.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.no_docs.value
        blocker = BLOCKER_TEXT["no_docs"]
    elif auth_primary == "session_only":
        buildability = Buildability.blocked.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.no_api.value
        blocker = BLOCKER_TEXT["session_only"]
    elif access_tier in ("partner_gated", "no_public_access"):
        buildability = Buildability.needs_outreach.value
        unblocker = Unblocker.composio_bd.value
        blocker_type = BlockerType.partnership.value
        blocker = BLOCKER_TEXT["partnership"]
    elif access_tier == "approval_gated":
        buildability = Buildability.needs_review.value
        unblocker = Unblocker.vendor_human.value
        blocker_type = BlockerType.vendor_review.value
        blocker = BLOCKER_TEXT["vendor_review"]
    elif access_tier in ("card_required", "plan_gated"):
        buildability = Buildability.easy_but_paid.value
        unblocker = Unblocker.composio_finance.value
        blocker_type = BlockerType.payment.value
        blocker = BLOCKER_TEXT["payment"]
    elif access_tier in ("open", "self_serve_free", "self_serve_trial"):
        buildability = Buildability.easy_win.value
        unblocker = Unblocker.nobody.value
        blocker_type = BlockerType.none.value
        blocker = ""
    else:
        buildability = Buildability.unknown.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.unknown.value
        blocker = BLOCKER_TEXT["unknown"]

    # Honest unknown: do not bury unknown access_tier inside gated.
    if (access_tier or "unknown") == "unknown":
        rollup = AccessTierRollup.unknown.value
    else:
        rollup = rollup_access_tier(access_tier)
        if rollup is None:
            if buildability == Buildability.easy_win.value:
                rollup = AccessTierRollup.open.value
            elif buildability == Buildability.easy_but_paid.value:
                rollup = AccessTierRollup.paid.value
            elif buildability == Buildability.unknown.value:
                rollup = AccessTierRollup.unknown.value
            else:
                rollup = AccessTierRollup.gated.value

    row["access_tier_rollup"] = rollup
    row["buildability"] = buildability
    row["unblocker"] = unblocker
    row["blocker_type"] = blocker_type
    row["blocker"] = blocker
    assert_verdict_invariants(row)
    return row


def assert_verdict_invariants(row: dict[str, Any]) -> None:
    b = row.get("buildability")
    u = row.get("unblocker")
    bt = row.get("blocker_type")
    blocker = row.get("blocker", "")
    rollup = row.get("access_tier_rollup")

    if b not in {e.value for e in Buildability}:
        raise AssertionError(f"invalid buildability: {b}")
    if rollup not in {e.value for e in AccessTierRollup}:
        raise AssertionError(f"invalid access_tier_rollup: {rollup}")

    expected = {
        Buildability.easy_win.value: (Unblocker.nobody.value, BlockerType.none.value, True),
        Buildability.easy_but_paid.value: (
            Unblocker.composio_finance.value,
            BlockerType.payment.value,
            False,
        ),
        Buildability.needs_review.value: (
            Unblocker.vendor_human.value,
            BlockerType.vendor_review.value,
            False,
        ),
        Buildability.needs_outreach.value: (
            Unblocker.composio_bd.value,
            BlockerType.partnership.value,
            False,
        ),
        Buildability.blocked.value: (Unblocker.n_a.value, None, False),
        Buildability.unknown.value: (
            Unblocker.n_a.value,
            BlockerType.unknown.value,
            False,
        ),
    }
    exp_u, exp_bt, blocker_empty = expected[b]
    if u != exp_u:
        raise AssertionError(f"unblocker {u} incompatible with {b}")
    if exp_bt is not None and bt != exp_bt:
        raise AssertionError(f"blocker_type {bt} incompatible with {b}")
    if b == Buildability.blocked.value and bt not in (
        BlockerType.no_api.value,
        BlockerType.no_docs.value,
    ):
        raise AssertionError(f"blocked requires no_api or no_docs, got {bt}")
    if blocker_empty and blocker:
        raise AssertionError("easy_win must have empty blocker")
    if (
        not blocker_empty
        and b
        in (
            Buildability.easy_but_paid.value,
            Buildability.needs_review.value,
            Buildability.needs_outreach.value,
            Buildability.blocked.value,
        )
        and not blocker
    ):
        raise AssertionError(f"{b} requires non-empty blocker")
    if b == Buildability.easy_win.value and u == Unblocker.vendor_human.value:
        raise AssertionError("easy_win + vendor_human")
