"""Stage 1 orchestration: discover → fetch → extract → guard → write facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from crosscheck.composio_check import finalize_agreement
from pipeline.debug_log import DebugRecorder
from pipeline.nodes import (
    build_row,
    coerce_uncited_path_fields,
    merge_extract,
    needs_second_round,
    node_discover,
    node_extract,
    node_fetch,
    second_round_targets,
    sources_have_pricing,
    validate_extract,
)
from pipeline.tavily_client import TavilyClient
from schema import empty_unknown_row


class AppState(TypedDict, total=False):
    app: dict
    row: dict


def _run_targeted_round(
    *,
    app: dict,
    discover: dict,
    tv: TavilyClient,
    dbg: DebugRecorder,
    extract: dict,
    pages: list[dict],
    sources: list[str],
    flags: list[str],
    missing: list[str],
) -> tuple[dict, list[dict], list[str], list[str]]:
    """One targeted second round: search → fetch extras → re-extract → merge."""
    extras = second_round_targets(missing, app, discover, tv, dbg)
    if not extras:
        return extract, pages, sources, flags

    if "second_round_used" not in flags:
        flags.append("second_round_used")
    if "pricing_coverage" in missing and "pricing_second_round" not in flags:
        flags.append("pricing_second_round")

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

    # Re-extract path + related fields (drop synthetic pricing_coverage key)
    field_subset = [f for f in missing if f != "pricing_coverage"]
    if "pricing_coverage" in missing:
        for f in ("integration_paths", "private_path_access", "public_path_access"):
            if f not in field_subset:
                field_subset.append(f)
    if not field_subset:
        field_subset = ["integration_paths", "private_path_access", "public_path_access"]

    extract2 = node_extract(app, discover, pages, dbg, field_subset=field_subset)
    err3 = validate_extract(extract2)
    if err3:
        extract2 = node_extract(
            app, discover, pages, dbg, field_subset=field_subset, repair_error=err3
        )
        if validate_extract(extract2):
            extract2 = coerce_uncited_path_fields(extract2)
    extract = merge_extract(extract, extract2)
    return extract, pages, sources, flags


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
        for f in discover.get("_discover_flags") or []:
            if f not in flags:
                flags.append(f)

        fetch = node_fetch(discover, tv, dbg)

        if len(fetch["pages"]) < 1:
            flags.append("retry_used")
            discover = node_discover(
                app,
                tv,
                dbg,
                failure_reason="fewer than one page fetched on first attempt",
            )
            for f in discover.get("_discover_flags") or []:
                if f not in flags:
                    flags.append(f)
            fetch = node_fetch(discover, tv, dbg)

        flags.extend(f for f in (fetch.get("flags") or []) if f not in flags)
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
                # Coerce uncited path fields rather than hard-failing the whole app
                # when only path evidence is missing.
                if "requires evidence" in err2:
                    extract = coerce_uncited_path_fields(extract)
                else:
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

        missing = needs_second_round(extract, sources=sources)
        second_used = False
        if missing:
            extract, pages, sources, flags = _run_targeted_round(
                app=app,
                discover=discover,
                tv=tv,
                dbg=dbg,
                extract=extract,
                pages=pages,
                sources=sources,
                flags=flags,
                missing=missing,
            )
            second_used = "second_round_used" in flags

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

        # FIX 2 post-derive rescue: only if round not yet used
        if row.get("access_tier") == "unknown" and not second_used:
            rescue_missing = ["integration_paths", "private_path_access", "public_path_access"]
            if not sources_have_pricing(sources):
                rescue_missing = ["pricing_coverage"] + rescue_missing
            extract, pages, sources, flags = _run_targeted_round(
                app=app,
                discover=discover,
                tv=tv,
                dbg=dbg,
                extract=extract,
                pages=pages,
                sources=sources,
                flags=flags,
                missing=rescue_missing,
            )
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
