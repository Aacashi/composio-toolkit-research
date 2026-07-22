"""Deterministic buildability derivation. Shared by pipeline and ground truth."""

from __future__ import annotations

from typing import Any

from schema import Buildability, BlockerType, Unblocker, WaitClass


WAIT_CLASS_MAP = {
    Buildability.easy_win.value: WaitClass.none.value,
    Buildability.easy_but_paid.value: WaitClass.none.value,
    Buildability.needs_review.value: WaitClass.weeks.value,
    Buildability.needs_outreach.value: WaitClass.months.value,
    Buildability.blocked.value: WaitClass.n_a.value,
    Buildability.unknown.value: WaitClass.unknown.value,
}

BLOCKER_TEXT = {
    "cli_tool": "Local CLI only; no vendor API for Composio to connect to.",
    "no_api": "No usable programmatic API found.",
    "no_docs": "No documentation located on first-party sources.",
    "session_only": "Only browser session/cookie auth exists; no API credentials.",
    "partnership": "No self-serve path; partner programme or sales outreach required.",
    "vendor_review": "Vendor must review and approve before production use.",
    "payment": "Credentials require a paid plan or payment card first.",
    "unknown": "Insufficient first-party evidence to decide buildability.",
}

# Fields forced by cli_tool short-circuit; guard skips evidence for these.
CLI_SHORTCIRCUIT_FIELDS = frozenset(
    {
        "docs_access",
        "docs_location",
        "access_tier",
        "auth_primary",
        "buildability",
        "unblocker",
        "wait_class",
        "blocker_type",
        "blocker",
    }
)


def apply_cli_shortcircuit(row: dict[str, Any]) -> dict[str, Any]:
    """Force atoms + verdict when api_type is cli_tool. Mutates and returns row."""
    row["docs_access"] = "public"
    row["docs_location"] = "third_party_host"
    row["access_tier"] = "no_public_access"
    row["auth_primary"] = "none"
    row["mcp_access"] = "n_a"
    row["buildability"] = Buildability.blocked.value
    row["unblocker"] = Unblocker.n_a.value
    row["wait_class"] = WaitClass.n_a.value
    row["blocker_type"] = BlockerType.no_api.value
    row["blocker"] = BLOCKER_TEXT["cli_tool"]
    return row


def derive_verdict(row: dict[str, Any]) -> dict[str, Any]:
    """
    Pure function: atomic facts -> verdict bundle.
    Worst-wait-wins via top-down first match (LOGIC_FREEZE §4).
    """
    if row.get("api_type") == "cli_tool":
        return apply_cli_shortcircuit(row)

    api_type = row.get("api_type") or "unknown"
    docs_access = row.get("docs_access") or "unknown"
    auth_primary = row.get("auth_primary") or "unknown"
    access_tier = row.get("access_tier") or "unknown"

    buildability: str
    unblocker: str
    blocker_type: str
    blocker: str

    # Rank 1
    if api_type in ("cli_tool", "none"):
        buildability = Buildability.blocked.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.no_api.value
        blocker = BLOCKER_TEXT["no_api"]
    elif docs_access == "none_found":
        buildability = Buildability.blocked.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.no_docs.value
        blocker = BLOCKER_TEXT["no_docs"]
    # Rank 2
    elif auth_primary == "session_only":
        buildability = Buildability.blocked.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.no_api.value
        blocker = BLOCKER_TEXT["session_only"]
    # Rank 3
    elif access_tier in ("partner_gated", "no_public_access"):
        buildability = Buildability.needs_outreach.value
        unblocker = Unblocker.composio_bd.value
        blocker_type = BlockerType.partnership.value
        blocker = BLOCKER_TEXT["partnership"]
    # Rank 4
    elif access_tier == "approval_gated":
        buildability = Buildability.needs_review.value
        unblocker = Unblocker.vendor_human.value
        blocker_type = BlockerType.vendor_review.value
        blocker = BLOCKER_TEXT["vendor_review"]
    # Rank 5
    elif access_tier in ("card_required", "plan_gated"):
        buildability = Buildability.easy_but_paid.value
        unblocker = Unblocker.composio_finance.value
        blocker_type = BlockerType.payment.value
        blocker = BLOCKER_TEXT["payment"]
    # Rank 6
    elif access_tier in ("open", "self_serve_free", "self_serve_trial"):
        buildability = Buildability.easy_win.value
        unblocker = Unblocker.nobody.value
        blocker_type = BlockerType.none.value
        blocker = ""
    # Rank 7
    else:
        buildability = Buildability.unknown.value
        unblocker = Unblocker.n_a.value
        blocker_type = BlockerType.unknown.value
        blocker = BLOCKER_TEXT["unknown"]

    wait_class = WAIT_CLASS_MAP[buildability]

    row["buildability"] = buildability
    row["unblocker"] = unblocker
    row["wait_class"] = wait_class
    row["blocker_type"] = blocker_type
    row["blocker"] = blocker

    assert_verdict_invariants(row)
    return row


def assert_verdict_invariants(row: dict[str, Any]) -> None:
    """Raise if derived fields contradict each other or the fixed wait map."""
    b = row.get("buildability")
    u = row.get("unblocker")
    w = row.get("wait_class")
    bt = row.get("blocker_type")
    blocker = row.get("blocker", "")

    if b not in WAIT_CLASS_MAP:
        raise AssertionError(f"invalid buildability: {b}")
    if w != WAIT_CLASS_MAP[b]:
        raise AssertionError(f"wait_class {w} != map for {b}")

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
        Buildability.blocked.value: (Unblocker.n_a.value, None, False),  # blocker_type varies
        Buildability.unknown.value: (
            Unblocker.n_a.value,
            BlockerType.unknown.value,
            False,
        ),
    }

    exp_u, exp_bt, blocker_empty = expected[b]
    if u != exp_u:
        raise AssertionError(f"unblocker {u} incompatible with {b} (expected {exp_u})")
    if exp_bt is not None and bt != exp_bt:
        raise AssertionError(f"blocker_type {bt} incompatible with {b} (expected {exp_bt})")
    if b == Buildability.blocked.value and bt not in (
        BlockerType.no_api.value,
        BlockerType.no_docs.value,
    ):
        raise AssertionError(f"blocked requires no_api or no_docs, got {bt}")
    if blocker_empty and blocker:
        raise AssertionError("easy_win must have empty blocker")
    if not blocker_empty and b != Buildability.unknown.value and not blocker:
        # unknown may still have text; blocked/paid/review/outreach must have text
        if b in (
            Buildability.easy_but_paid.value,
            Buildability.needs_review.value,
            Buildability.needs_outreach.value,
            Buildability.blocked.value,
        ) and not blocker:
            raise AssertionError(f"{b} requires non-empty blocker")

    # Forbidden contradictions called out in freeze
    if b == Buildability.easy_win.value and u == Unblocker.vendor_human.value:
        raise AssertionError("easy_win + vendor_human")
    if b == Buildability.easy_win.value and w != WaitClass.none.value:
        raise AssertionError("easy_win + non-none wait")
