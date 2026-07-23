"""Deterministic post-checks. No LLM. Stage 1."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from pipeline.debug_log import DebugRecorder
from pipeline.domains import domain_in_first_party
from pipeline.verdict import CLI_SHORTCIRCUIT_FIELDS
from schema import GEMINI_FACT_FIELDS, HINT_FIELD_MAP

# Prefer second-round value when merge_extract logged a contradiction.
SECOND_ROUND_PREFER_FIELDS = (
    "auth_primary",
    "integration_paths",
    "private_path_access",
    "public_path_access",
)

_CONTRADICTION_RE = re.compile(
    r"contradiction\s+(\w+)\s*:\s*kept\s+['\"](.+?)['\"]\s*,\s*second said\s+['\"](.+?)['\"]",
    re.IGNORECASE,
)

MCP_PRESENCE_VALUES = frozenset({"official_open", "official_gated", "community"})

STRICT_FIRST_PARTY_FIELDS = (
    "auth_primary",
    "access_tier",
    "mcp_exists",
    "has_openapi_spec",
    "is_open_source",
)

FREE_TEXT_EVIDENCE_KEYS = (
    "one_liner",
    "auth_detail",
    "access_cost_note",
    "business_type_supported",
)

# Topic-related URL substrings for absence/presence guards.
FIELD_URL_HINTS: dict[str, tuple[str, ...]] = {
    "mcp_exists": ("mcp", "modelcontextprotocol", "model-context"),
    "has_webhooks": ("webhook",),
    "has_openapi_spec": ("openapi", "swagger", "/oas"),
}

ABSENCE_VALUES: dict[str, str] = {
    "mcp_exists": "none",
    "has_webhooks": "no",
    "has_openapi_spec": "no",
}

PRESENCE_VALUES: dict[str, frozenset[str]] = {
    "mcp_exists": frozenset({"official_open", "official_gated", "community"}),
    "has_webhooks": frozenset({"yes"}),
    "has_openapi_spec": frozenset({"yes"}),
}

DOCS_NONE_CAPABILITY_FIELDS = (
    "auth_primary",
    "access_tier",
    "api_type",
    "mcp_exists",
    "has_webhooks",
    "has_openapi_spec",
    "needs_instance_url",
    "is_open_source",
    "integration_paths",
    "private_path_access",
    "public_path_access",
)

MCP_GATED_SIGNALS = (
    "paywall",
    "waitlist",
    "preview",
    "enterprise",
    "paid plan",
    "subscription",
    "pricing tier",
    "plan tier",
    "upgrade",
    "pro plan",
    "business plan",
    "license",
    "celeste",
)

# Positive evidence that an official MCP is usable with ordinary credentials.
MCP_OPEN_SIGNALS = (
    "api key",
    "api_key",
    "access token",
    "oauth",
    "get started",
    "quickstart",
    "install",
    "npx ",
    "claude desktop",
    "cursor",
    "with your",
    "available to all",
    "free to use",
)


def canonicalize_url(url: str) -> str:
    """Normalize for evidence/source membership checks."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def url_in_sources(url: str, sources: list[str] | set[str]) -> bool:
    target = canonicalize_url(url)
    if not target:
        return False
    canon_sources = {canonicalize_url(s) for s in sources if s}
    return target in canon_sources


def url_matches_hints(url: str, hints: tuple[str, ...]) -> bool:
    low = (url or "").lower()
    return any(h in low for h in hints)


def sources_match_hints(sources: list[str], hints: tuple[str, ...]) -> bool:
    return any(url_matches_hints(u, hints) for u in sources)


def apply_absence_guard(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """Downgrade unsupported absence assertions when no related URL was fetched."""
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = list(row.get("sources_fetched") or [])

    for field, absence_value in ABSENCE_VALUES.items():
        if row.get(field) != absence_value:
            continue
        hints = FIELD_URL_HINTS[field]
        if sources_match_hints(sources, hints):
            continue
        before = row[field]
        row[field] = "unknown"
        evidence.pop(field, None)
        if "unsupported_absence" not in flags:
            flags.append("unsupported_absence")
        if dbg:
            dbg.add_guard_change(
                field,
                before,
                "unknown",
                "unsupported absence: no related URL in sources_fetched",
            )

    row["flags"] = flags
    row["evidence"] = evidence
    return row


def apply_presence_guard(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """Downgrade presence claims without a topic-related fetched URL."""
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = list(row.get("sources_fetched") or [])

    for field, values in PRESENCE_VALUES.items():
        if row.get(field) not in values:
            continue
        hints = FIELD_URL_HINTS[field]
        if sources_match_hints(sources, hints):
            continue
        before = row[field]
        row[field] = "unknown"
        evidence.pop(field, None)
        if "unsupported_presence" not in flags:
            flags.append("unsupported_presence")
        if dbg:
            dbg.add_guard_change(
                field,
                before,
                "unknown",
                "unsupported presence: no related URL in sources_fetched",
            )

    row["flags"] = flags
    row["evidence"] = evidence
    return row


def apply_docs_none_invariant(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """If docs_access=none_found, capabilities cannot be known."""
    if row.get("docs_access") != "none_found":
        return row
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    wiped = False
    for field in DOCS_NONE_CAPABILITY_FIELDS:
        before = row.get(field)
        if before in (None, "", "unknown"):
            evidence.pop(field, None)
            continue
        row[field] = "unknown"
        evidence.pop(field, None)
        wiped = True
        if dbg:
            dbg.add_guard_change(
                field,
                before,
                "unknown",
                "docs_access=none_found: capability wiped",
            )
    if wiped and "docs_none_capabilities" not in flags:
        flags.append("docs_none_capabilities")
    row["flags"] = flags
    row["evidence"] = evidence
    return row


def enforce_evidence_subset(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """Invariant: every remaining evidence URL must be in sources_fetched."""
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = list(row.get("sources_fetched") or [])
    for key, ev in list(evidence.items()):
        if not ev:
            evidence.pop(key, None)
            continue
        if url_in_sources(ev, sources):
            continue
        print(f"[guard] INVARIANT FAIL {row.get('app_name')} field={key} evidence={ev!r}")
        evidence.pop(key, None)
        if key in GEMINI_FACT_FIELDS and row.get(key) not in (None, "", "unknown"):
            before = row[key]
            row[key] = "unknown"
            if dbg:
                dbg.add_guard_change(key, before, "unknown", "guard_invariant_fail")
        if "guard_invariant_fail" not in flags:
            flags.append("guard_invariant_fail")
    row["flags"] = flags
    row["evidence"] = evidence
    return row


def apply_mcp_gate_from_pages(
    row: dict[str, Any],
    pages: list[dict[str, Any]],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """
    If mcp_exists is official_open/official_gated, constrain using MCP page text.
    Gated signals on the MCP page force official_gated; empty/unclear text -> unknown.
    """
    val = row.get("mcp_exists")
    if val not in ("official_open", "official_gated"):
        return row
    hints = FIELD_URL_HINTS["mcp_exists"]
    mcp_pages = [p for p in pages if url_matches_hints(p.get("url") or "", hints)]
    if not mcp_pages:
        # Presence guard should already have fired; if not, unknown.
        before = val
        row["mcp_exists"] = "unknown"
        evidence = dict(row.get("evidence") or {})
        evidence.pop("mcp_exists", None)
        row["evidence"] = evidence
        flags = list(row.get("flags") or [])
        if "unsupported_presence" not in flags:
            flags.append("unsupported_presence")
        row["flags"] = flags
        if dbg:
            dbg.add_guard_change(
                "mcp_exists", before, "unknown", "mcp gate: no mcp page text"
            )
        return row

    text = " ".join((p.get("text") or "") for p in mcp_pages).lower()
    if not text.strip():
        before = val
        row["mcp_exists"] = "unknown"
        flags = list(row.get("flags") or [])
        if "mcp_gate_unclear" not in flags:
            flags.append("mcp_gate_unclear")
        row["flags"] = flags
        if dbg:
            dbg.add_guard_change("mcp_exists", before, "unknown", "mcp gate: empty page text")
        return row

    has_gated = any(sig in text for sig in MCP_GATED_SIGNALS)
    has_open = any(sig in text for sig in MCP_OPEN_SIGNALS)
    if has_gated:
        if val != "official_gated":
            before = val
            row["mcp_exists"] = "official_gated"
            flags = list(row.get("flags") or [])
            if "mcp_gate_forced" not in flags:
                flags.append("mcp_gate_forced")
            row["flags"] = flags
            if dbg:
                dbg.add_guard_change(
                    "mcp_exists",
                    before,
                    "official_gated",
                    "mcp gate: gated signals on page",
                )
        return row

    # No gated signals. official_open only sticks with positive open evidence;
    # otherwise we cannot tell open vs gated → unknown.
    if val == "official_open" and not has_open:
        before = val
        row["mcp_exists"] = "unknown"
        flags = list(row.get("flags") or [])
        if "mcp_gate_unclear" not in flags:
            flags.append("mcp_gate_unclear")
        row["flags"] = flags
        if dbg:
            dbg.add_guard_change(
                "mcp_exists",
                before,
                "unknown",
                "mcp gate: no gated or open signals",
            )
    return row


def apply_auth_detail_conflict(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """api_key + Basic-auth wording in auth_detail -> basic + auth_detail_conflict."""
    if row.get("auth_primary") != "api_key":
        return row
    detail = (row.get("auth_detail") or "").lower()
    basic_signals = (
        "basic auth",
        "http basic",
        "basic authentication",
        "base64",
        "email/token",
        "email:token",
        "username:password",
        "-u ",
        "authorization: basic",
    )
    if not any(s in detail for s in basic_signals):
        return row
    before = row["auth_primary"]
    row["auth_primary"] = "basic"
    flags = list(row.get("flags") or [])
    if "auth_detail_conflict" not in flags:
        flags.append("auth_detail_conflict")
    row["flags"] = flags
    if dbg:
        dbg.add_guard_change(
            "auth_primary", before, "basic", "auth_detail describes Basic auth"
        )
    return row


def sources_have_mcp_url(sources: list[str] | None) -> bool:
    return any(
        "mcp" in (u or "").lower() or "modelcontext" in (u or "").lower()
        for u in (sources or [])
    )


def apply_second_round_preference(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """
    Post-loop: if merge logged contradiction field: kept X, second said Y,
    prefer Y for auth_primary and path fields (second round saw more pages).
    """
    notes = row.get("notes") or ""
    if "contradiction" not in notes.lower():
        return row
    flags: list[str] = list(row.get("flags") or [])
    changed = False
    for match in _CONTRADICTION_RE.finditer(notes):
        field, kept, second = match.group(1), match.group(2), match.group(3)
        if field not in SECOND_ROUND_PREFER_FIELDS:
            continue
        if row.get(field) != kept:
            # Already diverged from the logged "kept" value; skip.
            continue
        if second in (None, "", "unknown") and field == "auth_primary":
            continue
        before = row.get(field)
        row[field] = second
        changed = True
        if dbg:
            dbg.add_guard_change(
                field,
                before,
                second,
                "post-loop: prefer second-round contradiction value",
            )
    if changed and "second_round_preferred" not in flags:
        flags.append("second_round_preferred")
    row["flags"] = flags
    return row


def apply_mcp_presence_url_guard(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """Post-loop: official/community MCP claims require an MCP-related fetched URL."""
    val = row.get("mcp_exists")
    if val not in MCP_PRESENCE_VALUES:
        return row
    if sources_have_mcp_url(row.get("sources_fetched")):
        return row
    before = val
    row["mcp_exists"] = "unknown"
    evidence = dict(row.get("evidence") or {})
    evidence.pop("mcp_exists", None)
    row["evidence"] = evidence
    flags = list(row.get("flags") or [])
    if "mcp_presence_no_url" not in flags:
        flags.append("mcp_presence_no_url")
    row["flags"] = flags
    if dbg:
        dbg.add_guard_change(
            "mcp_exists",
            before,
            "unknown",
            "post-loop: MCP presence without mcp URL in sources_fetched",
        )
    return row


def apply_post_loop_guards(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """
    Cheap deterministic fixes after the agent loop (no LLM / no cache replay).
    1) Prefer second-round values logged in contradiction notes.
    2) Wipe MCP presence claims with no MCP URL fetched.
    Caller should re-derive access_tier after this.
    """
    row = apply_second_round_preference(row, dbg=dbg)
    row = apply_mcp_presence_url_guard(row, dbg=dbg)
    return row


def apply_guard(
    row: dict[str, Any],
    *,
    cli_shortcircuit: bool = False,
    dbg: Optional[DebugRecorder] = None,
    pages: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = list(row.get("sources_fetched") or [])
    first_party = list(row.get("first_party_domains") or [])
    skip_fields = CLI_SHORTCIRCUIT_FIELDS if cli_shortcircuit else frozenset()

    # Path fields Gemini emits; access_tier is derived after guard and skipped here.
    path_fields = ("integration_paths", "private_path_access", "public_path_access")
    check_fields = [f for f in list(GEMINI_FACT_FIELDS) + list(path_fields) if f != "access_tier"]

    for field in check_fields:
        if field in skip_fields:
            continue
        value = row.get(field)
        if value in (None, "", "unknown", "n_a"):
            continue
        ev = evidence.get(field)
        if not ev:
            before = row[field]
            row[field] = "unknown"
            if "unsourced" not in flags:
                flags.append("unsourced")
            if dbg:
                dbg.add_guard_change(field, before, "unknown", "missing evidence")
            continue
        if not url_in_sources(ev, sources):
            before = row[field]
            row[field] = "unknown"
            evidence.pop(field, None)
            if "unsourced" not in flags:
                flags.append("unsourced")
            if dbg:
                dbg.add_guard_change(
                    field, before, "unknown", "evidence not in sources_fetched"
                )
            continue
        if field in STRICT_FIRST_PARTY_FIELDS or field in path_fields:
            if not domain_in_first_party(ev, first_party):
                before = row[field]
                row[field] = "unknown"
                evidence.pop(field, None)
                if "unsourced" not in flags:
                    flags.append("unsourced")
                if dbg:
                    dbg.add_guard_change(
                        field, before, "unknown", "evidence not first-party"
                    )

    # Free-text evidence must also cite a fetched source.
    for key in FREE_TEXT_EVIDENCE_KEYS:
        ev = evidence.get(key)
        if not ev:
            continue
        if not url_in_sources(ev, sources):
            evidence.pop(key, None)
            if "unsourced" not in flags:
                flags.append("unsourced")
            if dbg:
                dbg.add_guard_change(key, ev, None, "free-text evidence not in sources")

    row["flags"] = flags
    row["evidence"] = evidence

    app_name = row.get("app_name", "")
    for field in HINT_FIELD_MAP.get(app_name, ()):
        ev = evidence.get(field)
        if not ev or not domain_in_first_party(ev, first_party):
            if "hint_unconfirmed" not in flags:
                flags.append("hint_unconfirmed")
            break

    row = apply_absence_guard(row, dbg=dbg)
    row = apply_presence_guard(row, dbg=dbg)
    row = apply_mcp_gate_from_pages(row, pages or [], dbg=dbg)
    row = apply_auth_detail_conflict(row, dbg=dbg)
    row = apply_docs_none_invariant(row, dbg=dbg)
    row = enforce_evidence_subset(row, dbg=dbg)
    return row
