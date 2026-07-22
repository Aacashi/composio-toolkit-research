"""LangGraph (and plain sequential) orchestration for one app."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from pipeline.firecrawl_client import FirecrawlClient
from pipeline.nodes import (
    build_row,
    merge_extract,
    needs_second_round,
    node_discover,
    node_extract,
    node_fetch,
    second_round_targets,
    validate_extract,
)
from crosscheck.composio_check import finalize_agreement
from pipeline.verdict import derive_verdict
from schema import empty_unknown_row


class AppState(TypedDict, total=False):
    app: dict
    discover: dict
    pages: list
    sources_fetched: list
    flags: list
    extract: dict
    row: dict
    error: str


def process_one_app(
    app: dict,
    fc: FirecrawlClient,
    *,
    run_id: Optional[str] = None,
    composio_fields: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Full pipeline for one app: discover → fetch → extract → optional second round
    → guard → derive_verdict. Never raises out of this function.
    """
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flags: list[str] = []
    fc.tracker.set_app(app["app_name"])

    try:
        discover = node_discover(app, fc)
        fetch = node_fetch(discover, fc)

        if len(fetch["pages"]) < 1:
            # one retry of discover with failure reason
            flags.append("retry_used")
            discover = node_discover(
                app,
                fc,
                failure_reason="fewer than one page fetched on first attempt",
            )
            fetch = node_fetch(discover, fc)

        flags.extend(fetch.get("flags") or [])
        sources = list(fetch.get("sources_fetched") or [])
        pages = list(fetch.get("pages") or [])

        if not pages:
            row = empty_unknown_row(app, flags=flags + ["no_docs_found"])
            row["business_type"] = discover.get("business_type") or "ai_native"
            row["first_party_domains"] = discover.get("first_party_domains") or []
            row["backup_links"] = discover.get("backup_links") or []
            row["docs_access"] = "none_found"
            row["run_id"] = run_id
            row = derive_verdict(row)
            return _attach_composio(row, composio_fields)

        extract = node_extract(app, discover, pages)
        err = validate_extract(extract)
        if err:
            extract = node_extract(app, discover, pages, repair_error=err)
            err2 = validate_extract(extract)
            if err2:
                row = empty_unknown_row(app, flags=flags + ["schema_fail"])
                row["business_type"] = discover.get("business_type") or "ai_native"
                row["first_party_domains"] = discover.get("first_party_domains") or []
                row["backup_links"] = discover.get("backup_links") or []
                row["sources_fetched"] = sources
                row["run_id"] = run_id
                row["notes"] = f"schema_fail: {err2}"
                row = derive_verdict(row)
                return _attach_composio(row, composio_fields)

        # provisional row for second-round decision (atoms only)
        provisional = {
            **{k: extract.get(k) for k in (
                "access_tier", "auth_primary", "api_type",
                "has_openapi_spec", "has_webhooks", "mcp_exists",
            )},
        }
        missing = needs_second_round(provisional)
        if missing:
            extras = second_round_targets(missing, app, discover, fc)
            if extras:
                flags.append("second_round_used")
                fetch2 = node_fetch(discover, fc, extra_urls=extras)
                # only keep newly fetched pages not already in sources
                new_pages = [p for p in fetch2["pages"] if p["url"] not in sources]
                pages = pages + new_pages
                sources = sources + [p["url"] for p in new_pages]
                flags.extend(f for f in (fetch2.get("flags") or []) if f not in flags)
                extract2 = node_extract(
                    app, discover, pages, field_subset=missing
                )
                err3 = validate_extract(extract2)
                if err3:
                    extract2 = node_extract(
                        app, discover, pages, field_subset=missing, repair_error=err3
                    )
                extract = merge_extract(extract, extract2)

        row = build_row(
            app,
            discover,
            extract,
            sources_fetched=sources,
            flags=flags,
            run_id=run_id,
        )
        return _attach_composio(row, composio_fields)

    except Exception as e:
        print(f"[graph] FAIL {app.get('app_name')}: {e}")
        row = empty_unknown_row(app, flags=["schema_fail"])
        row["notes"] = f"pipeline exception: {e}"
        row["run_id"] = run_id
        row = derive_verdict(row)
        return _attach_composio(row, composio_fields)


def _attach_composio(row: dict[str, Any], fields: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not fields:
        row.setdefault("composio_supports", None)
        row.setdefault("composio_auth_scheme", None)
        row.setdefault("agrees_with_composio", "n_a")
        return finalize_agreement(row)
    row["composio_supports"] = fields.get("composio_supports")
    row["composio_auth_scheme"] = fields.get("composio_auth_scheme")
    row["agrees_with_composio"] = fields.get("agrees_with_composio", "n_a")
    return finalize_agreement(row)


def build_graph():
    """
    Optional LangGraph wrapper. Prefer process_one_app for the CLI.
    Returns a compiled graph if langgraph is available.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None

    def discover_node(state: AppState) -> AppState:
        # placeholder — CLI uses process_one_app
        return state

    g = StateGraph(AppState)
    g.add_node("discover", discover_node)
    g.set_entry_point("discover")
    g.add_edge("discover", END)
    return g.compile()
