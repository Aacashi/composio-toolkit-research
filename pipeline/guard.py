"""Deterministic post-checks. No LLM. Stage 1."""

from __future__ import annotations

from typing import Any, Optional

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

# Narrow absence guard: only these fields. Do NOT include api_type / auth_primary —
# their URL substrings match almost every docs page.
ABSENCE_URL_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mcp_exists": ("none", ("mcp", "modelcontextprotocol", "model-context")),
    "has_webhooks": ("no", ("webhook",)),
    "has_openapi_spec": ("no", ("openapi", "swagger", "/oas")),
}


def url_matches_hints(url: str, hints: tuple[str, ...]) -> bool:
    low = (url or "").lower()
    return any(h in low for h in hints)


def apply_absence_guard(
    row: dict[str, Any],
    *,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    """Downgrade unsupported absence assertions when no related URL was fetched."""
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = list(row.get("sources_fetched") or [])

    for field, (absence_value, hints) in ABSENCE_URL_HINTS.items():
        if row.get(field) != absence_value:
            continue
        if any(url_matches_hints(u, hints) for u in sources):
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


def apply_guard(
    row: dict[str, Any],
    *,
    cli_shortcircuit: bool = False,
    dbg: Optional[DebugRecorder] = None,
) -> dict[str, Any]:
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = set(row.get("sources_fetched") or [])
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
        normalized = {s.rstrip("/") for s in sources}
        if ev not in sources and ev.rstrip("/") not in normalized:
            before = row[field]
            row[field] = "unknown"
            evidence.pop(field, None)
            if "unsourced" not in flags:
                flags.append("unsourced")
            if dbg:
                dbg.add_guard_change(field, before, "unknown", "evidence not in sources_fetched")
            continue
        if field in STRICT_FIRST_PARTY_FIELDS:
            if not domain_in_first_party(ev, first_party):
                before = row[field]
                row[field] = "unknown"
                evidence.pop(field, None)
                if "unsourced" not in flags:
                    flags.append("unsourced")
                if dbg:
                    dbg.add_guard_change(field, before, "unknown", "evidence not first-party")

    row["flags"] = flags
    row["evidence"] = evidence

    app_name = row.get("app_name", "")
    for field in HINT_FIELD_MAP.get(app_name, ()):
        ev = evidence.get(field)
        if not ev or not domain_in_first_party(ev, first_party):
            if "hint_unconfirmed" not in flags:
                flags.append("hint_unconfirmed")
            break

    return apply_absence_guard(row, dbg=dbg)
