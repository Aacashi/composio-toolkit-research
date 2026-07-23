"""Stage 1 orchestration: plan → gather → fill → derive access_tier (v10)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from crosscheck.composio_check import finalize_agreement
from pipeline.debug_log import DebugRecorder
from pipeline.nodes import (
    build_row,
    coerce_uncited_path_fields,
    validate_extract,
)
from pipeline.tavily_client import TavilyClient
from pipeline.v10_flow import node_fill, node_gather, node_plan
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
    v10: max 2 Gemini calls (plan + fill); optional 3rd plan if gather empty.
    """
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flags: list[str] = []
    tv.tracker.set_app(app["app_name"])
    dbg = DebugRecorder(app["app_name"])
    tv.verbose = verbose
    gemini_calls = [0]  # mutable counter

    try:
        plan = node_plan(app, tv, dbg, gemini_calls=gemini_calls)
        gathered = node_gather(app, plan, tv, dbg)
        flags.extend(f for f in (gathered.get("flags") or []) if f not in flags)
        pages = list(gathered.get("pages") or [])
        sources = list(gathered.get("sources_fetched") or [])

        if not pages:
            flags.append("retry_used")
            plan = node_plan(
                app,
                tv,
                dbg,
                failure_reason="fewer than one live page on first gather",
                gemini_calls=gemini_calls,
            )
            gathered = node_gather(app, plan, tv, dbg)
            flags.extend(f for f in (gathered.get("flags") or []) if f not in flags)
            pages = list(gathered.get("pages") or [])
            sources = list(gathered.get("sources_fetched") or [])

        if not pages:
            row = empty_unknown_row(
                app, flags=flags + ["no_docs_found"], docs_access="none_found"
            )
            row["business_type"] = plan.get("business_type") or "ai_native"
            row["first_party_domains"] = plan.get("first_party_domains") or []
            row["backup_links"] = plan.get("backup_links") or []
            row["run_id"] = run_id
            row["notes"] = f"gemini_calls={gemini_calls[0]}"
            dbg.data["gemini_calls"] = gemini_calls[0]
            dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
            dbg.set_tavily_provider(tv.provider_debug())
            dbg.write()
            return _attach_composio(row, composio_fields)

        extract = node_fill(app, plan, pages, dbg, gemini_calls=gemini_calls)
        err = validate_extract(extract)
        if err:
            # Repair uses cache key with repair_error — counts as another Gemini call
            # only when not cached. Cap: allow one repair (may push to 3 calls total).
            extract = node_fill(
                app, plan, pages, dbg, gemini_calls=gemini_calls, repair_error=err
            )
            err2 = validate_extract(extract)
            if err2:
                if "requires evidence" in err2:
                    extract = coerce_uncited_path_fields(extract)
                else:
                    row = empty_unknown_row(
                        app, flags=flags + ["schema_fail"], docs_access="unknown"
                    )
                    row["business_type"] = plan.get("business_type") or "ai_native"
                    row["first_party_domains"] = plan.get("first_party_domains") or []
                    row["backup_links"] = plan.get("backup_links") or []
                    row["sources_fetched"] = sources
                    row["run_id"] = run_id
                    row["notes"] = f"schema_fail: {err2}; gemini_calls={gemini_calls[0]}"
                    dbg.data["gemini_calls"] = gemini_calls[0]
                    dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
                    dbg.set_tavily_provider(tv.provider_debug())
                    dbg.write()
                    return _attach_composio(row, composio_fields)

        # build_row expects discover-shaped dict
        discover = {
            "business_type": plan.get("business_type"),
            "one_liner": extract.get("one_liner") or "",
            "first_party_domains": plan.get("first_party_domains") or [],
            "backup_links": plan.get("backup_links") or [],
            "_seeded_domains": plan.get("_seeded_domains"),
        }
        row = build_row(
            app,
            discover,
            extract,
            sources_fetched=sources,
            flags=flags,
            run_id=run_id,
            dbg=dbg,
            pages=pages,
        )
        row["notes"] = (row.get("notes") or "") + f" | gemini_calls={gemini_calls[0]}"
        dbg.data["gemini_calls"] = gemini_calls[0]
        print(f"[v10] {app['app_name']} gemini_calls={gemini_calls[0]} pages={len(pages)}")

        dbg.set_credits(tv.tracker.per_app.get(app["app_name"], 0))
        dbg.set_tavily_provider(tv.provider_debug())
        dbg.write()
        return _attach_composio(row, composio_fields)

    except Exception as e:
        print(f"[graph] FAIL {app.get('app_name')}: {e}")
        dbg.add_error(str(e))
        dbg.data["gemini_calls"] = gemini_calls[0]
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
