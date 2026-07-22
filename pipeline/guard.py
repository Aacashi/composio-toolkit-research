"""Deterministic post-checks. No LLM. Cannot fail the run."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pipeline.domains import domain_in_first_party
from pipeline.verdict import CLI_SHORTCIRCUIT_FIELDS
from schema import HINT_FIELD_MAP


# Fields that require first-party evidence domain check
STRICT_FIRST_PARTY_FIELDS = (
    "auth_primary",
    "auth_secondary",
    "access_tier",
    "mcp_exists",
    "mcp_access",
    "has_openapi_spec",
)


def apply_guard(row: dict[str, Any], *, cli_shortcircuit: bool = False) -> dict[str, Any]:
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})
    sources = set(row.get("sources_fetched") or [])
    first_party = list(row.get("first_party_domains") or [])

    skip_fields = CLI_SHORTCIRCUIT_FIELDS if cli_shortcircuit else frozenset()

    check_fields = [
        "docs_access",
        "docs_location",
        "auth_primary",
        "access_tier",
        "api_type",
        "api_breadth",
        "has_openapi_spec",
        "needs_instance_url",
        "has_webhooks",
        "mcp_exists",
        "mcp_access",
    ]

    for field in check_fields:
        if field in skip_fields:
            continue
        value = row.get(field)
        if value in (None, "", "unknown"):
            continue
        # auth_secondary is a list — handled below
        ev = evidence.get(field)
        if not ev:
            row[field] = "unknown"
            if "unsourced" not in flags:
                flags.append("unsourced")
            continue
        if ev not in sources:
            # allow if same URL ignoring trailing slash
            normalized = {s.rstrip("/") for s in sources}
            if ev.rstrip("/") not in normalized:
                row[field] = "unknown"
                evidence.pop(field, None)
                if "unsourced" not in flags:
                    flags.append("unsourced")
                continue
        if field in STRICT_FIRST_PARTY_FIELDS:
            if not domain_in_first_party(ev, first_party):
                row[field] = "unknown"
                evidence.pop(field, None)
                if "unsourced" not in flags:
                    flags.append("unsourced")

    # auth_secondary entries
    if not cli_shortcircuit:
        secondary = row.get("auth_secondary") or []
        if secondary:
            ev = evidence.get("auth_secondary") or evidence.get("auth_primary")
            if not ev or (
                ev not in sources
                and ev.rstrip("/") not in {s.rstrip("/") for s in sources}
            ):
                row["auth_secondary"] = []
                if "unsourced" not in flags:
                    flags.append("unsourced")
            elif not domain_in_first_party(ev, first_party):
                row["auth_secondary"] = []
                if "unsourced" not in flags:
                    flags.append("unsourced")

    # Hint contamination (LOGIC_FREEZE §10)
    app_name = row.get("app_name", "")
    for field in HINT_FIELD_MAP.get(app_name, ()):
        ev = evidence.get(field)
        if not ev or not domain_in_first_party(ev, first_party):
            if "hint_unconfirmed" not in flags:
                flags.append("hint_unconfirmed")
            break

    row["flags"] = flags
    row["evidence"] = evidence
    return row
