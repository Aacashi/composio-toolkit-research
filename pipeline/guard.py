"""Deterministic post-checks. No LLM. Stage 1."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from pipeline.debug_log import DebugRecorder
from pipeline.domains import domain_in_first_party
from pipeline.verdict import CLI_SHORTCIRCUIT_FIELDS
from schema import GEMINI_FACT_FIELDS, HINT_FIELD_MAP

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


def apply_guard(
    row: dict[str, Any],
    *,
    cli_shortcircuit: bool = False,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = list(row.get("sources_fetched") or [])
    first_party = list(row.get("first_party_domains") or [])
    skip_fields = CLI_SHORTCIRCUIT_FIELDS if cli_shortcircuit else frozenset()

    for field in GEMINI_FACT_FIELDS:
        if field in skip_fields:
            continue
        value = row.get(field)
        if value in (None, "", "unknown"):
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
        if field in STRICT_FIRST_PARTY_FIELDS:
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
    row = apply_docs_none_invariant(row, dbg=dbg)
    row = enforce_evidence_subset(row, dbg=dbg)
    return row
