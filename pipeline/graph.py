"""Stage 1 orchestration: discover → fetch → extract → guard → write facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from crosscheck.composio_check import finalize_agreement
from pipeline.debug_log import DebugRecorder
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
from pipeline.tavily_client import TavilyClient
from schema import empty_unknown_row


class AppState(TypedDict, total=False):
    app: dict
    row: dict


def process_one_app(
    app: dict,
    tv: TavilyClient,
    *,
    run_id: Optional[str] = None,
    composio_fields: Optional[dict[str, Any]] = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Stage 1 only: facts + audit + composio cross-check.
    Does NOT compute derived verdict fields.
    """
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flags: list[str] = []
    tv.tracker.set_app(app["app_name"])
    dbg = DebugRecorder(app["app_name"])
    tv.verbose = verbose

    try:
        discover = node_discover(app, tv, dbg)
        fetch = node_fetch(discover, tv, dbg)

        if len(fetch["pages"]) < 1:
            flags.append("retry_used")
            discover = node_discover(
                app,
                tv,
                dbg,
                failure_reason="fewer than one page fetched on first attempt",
            )
            fetch = node_fetch(discover, tv, dbg)

        flags.extend(fetch.get("flags") or [])
        sources = list(fetch.get("sources_fetched") or [])
        pages = list(fetch.get("pages") or [])

        if not pages:
            row = empty_unknown_row(app, flags=flags + ["no_docs_found"], docs_access="none_found")
            row["business_type"] = discover.get("business_type") or "ai_native"
            row["first_party_domains"] = discover.get("first_party_domains") or []
            row["backup_links"] = discover.get("backup_links") or []
            row["run_id"] = run_id
            dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
            dbg.set_tavily_provider(tv.provider_debug())
            dbg.write()
            return _attach_composio(row, composio_fields)

        extract = node_extract(app, discover, pages, dbg)
        err = validate_extract(extract)
        if err:
            extract = node_extract(app, discover, pages, dbg, repair_error=err)
            err2 = validate_extract(extract)
            if err2:
                row = empty_unknown_row(app, flags=flags + ["schema_fail"], docs_access="unknown")
                row["business_type"] = discover.get("business_type") or "ai_native"
                row["first_party_domains"] = discover.get("first_party_domains") or []
                row["backup_links"] = discover.get("backup_links") or []
                row["sources_fetched"] = sources
                row["run_id"] = run_id
                row["notes"] = f"schema_fail: {err2}"
                dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
                dbg.set_tavily_provider(tv.provider_debug())
                dbg.write()
                return _attach_composio(row, composio_fields)

        provisional = {
            k: extract.get(k)
            for k in (
                "access_tier",
                "auth_primary",
                "api_type",
                "has_openapi_spec",
                "has_webhooks",
                "mcp_exists",
            )
        }
        missing = needs_second_round(provisional)
        if missing:
            extras = second_round_targets(missing, app, discover, tv, dbg)
            if extras:
                flags.append("second_round_used")
                fetch2 = node_fetch(
                    discover,
                    tv,
                    dbg,
                    extra_urls=extras,
                    extras_only=True,
                    already_fetched=set(sources),
                    page_budget=min(3, len(extras)),
                )
                new_pages = [p for p in fetch2["pages"] if p["url"] not in sources]
                pages = pages + new_pages
                sources = sources + [p["url"] for p in new_pages]
                flags.extend(f for f in (fetch2.get("flags") or []) if f not in flags)
                extract2 = node_extract(app, discover, pages, dbg, field_subset=missing)
                err3 = validate_extract(extract2)
                if err3:
                    extract2 = node_extract(
                        app, discover, pages, dbg, field_subset=missing, repair_error=err3
                    )
                extract = merge_extract(extract, extract2)

        row = build_row(
            app,
            discover,
            extract,
            sources_fetched=sources,
            flags=flags,
            run_id=run_id,
            dbg=dbg,
        )
        dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
        dbg.set_tavily_provider(tv.provider_debug())
        dbg.write()
        return _attach_composio(row, composio_fields)

    except Exception as e:
        print(f"[graph] FAIL {app.get('app_name')}: {e}")
        dbg.add_error(str(e))
        dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
        dbg.set_tavily_provider(tv.provider_debug())
        dbg.write()
        row = empty_unknown_row(app, flags=["schema_fail"], docs_access="unknown")
        row["notes"] = f"pipeline exception: {e}"
        row["run_id"] = run_id
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
    from langgraph.graph import END, StateGraph

    def run_node(state: AppState) -> AppState:
        return state

    g = StateGraph(AppState)
    g.add_node("run", run_node)
    g.set_entry_point("run")
    g.add_edge("run", END)
    return g.compile()
