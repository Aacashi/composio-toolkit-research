"""Pipeline nodes — Stage 1 facts only (AMENDMENT_3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pipeline.clean import assemble_extract_input, chunk_text, clean_page
from pipeline.debug_log import DebugRecorder
from pipeline.domains import merge_discovered_domains, seed_first_party_domains
from pipeline.gemini_client import chunk_filter_call, discover_with_search_agent, generate_json
from pipeline.guard import apply_guard
from pipeline.tavily_client import TavilyClient
from schema import ALLOWED_VALUES, GEMINI_FACT_FIELDS, PROMPTS_VERSION, ExtractResult

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CLEAN_CAP = 10_000
EXTRACT_TOTAL_CAP = 40_000
MAX_PAGES = 6
SECOND_ROUND_SEARCH_CAP = 2

SECOND_ROUND_PRIORITY = (
    "access_tier",
    "auth_primary",
    "api_type",
    "has_openapi_spec",
    "has_webhooks",
    "mcp_exists",
)


def node_discover(
    app: dict,
    tv: TavilyClient,
    dbg: DebugRecorder,
    *,
    failure_reason: Optional[str] = None,
) -> dict[str, Any]:
    """
    Call 1 AGENT: Gemini with Tavily search tool bound.
    Gemini decides every query (business-type prior drives search). Max 6 tool calls.
    """
    dbg.stage_start("discover")
    seeded = seed_first_party_domains(app)
    system = (PROMPTS / "call1_discover.txt").read_text(encoding="utf-8")

    user_parts = [
        f"app_name: {app['app_name']}",
        f"category: {app.get('category')}",
        f"hint_type: {app.get('hint_type')}",
        f"hint_url: {app.get('hint_url')}",
        f"hint_note: {app.get('hint_note')}",
        f"hint_raw: {app.get('hint_raw')}",
        f"SEEDED first_party_domains (you may only ADD to this list): {json.dumps(seeded)}",
        "",
        "You have the tavily_search tool. Classify business_type first (as a prior), then "
        "call tavily_search yourself with queries that prior implies. Max 4 searches. "
        "When done, return the final JSON object described in the system prompt.",
    ]
    if failure_reason:
        user_parts.append(
            f"PREVIOUS FETCH FAILED: {failure_reason}. "
            "Search again for alternative first-party auth/pricing/api URLs."
        )
    if app.get("hint_type") == "docs_url" and app.get("hint_url"):
        user_parts.append(
            f"STRONG SEED docs_url: {app['hint_url']} — treat as likely api_index_url or auth_url; "
            "still search for pricing/access and auth if needed."
        )
    if app.get("hint_type") == "note" and app.get("hint_note"):
        user_parts.append(
            f"NOTE (context only, NEVER an answer): {app['hint_note']}"
        )

    user_prompt = "\n".join(user_parts)

    cache_payload = {
        "prompts_version": PROMPTS_VERSION,
        "hint_type": app.get("hint_type"),
        "hint_url": app.get("hint_url"),
        "hint_note": app.get("hint_note"),
        "hint_raw": app.get("hint_raw"),
        "seeded_domains": seeded,
        "failure_reason": failure_reason,
        # Do NOT include search results — agent chooses queries live
    }

    def _search(query: str, max_results: int) -> list[dict[str, Any]]:
        return tv.search(query, limit=max_results)

    def _on_search(query: str, results: list[dict[str, Any]]) -> None:
        dbg.add_search(query, results)

    data, tool_calls, trace = discover_with_search_agent(
        app_name=app["app_name"],
        system_prompt=system,
        user_prompt=user_prompt,
        cache_payload=cache_payload,
        search_fn=_search,
        max_tool_calls=6,
        on_search=_on_search,
    )
    dbg.add_gemini(
        "discover_agent",
        user_prompt,
        {"result": data, "tool_calls": tool_calls, "trace_queries": [t.get("query") for t in trace]},
    )

    discovered_domains = data.get("first_party_domains") or []
    data["first_party_domains"] = merge_discovered_domains(seeded, discovered_domains)
    data["_seeded_domains"] = seeded
    data["_tool_calls"] = tool_calls
    data["app_name"] = app["app_name"]
    dbg.stage_end(
        "discover",
        business_type=data.get("business_type"),
        tool_calls=tool_calls,
        urls={
            "auth": data.get("auth_url"),
            "pricing": data.get("pricing_url"),
            "api_index": data.get("api_index_url"),
        },
    )
    return data


def node_fetch(
    discover: dict,
    tv: TavilyClient,
    dbg: DebugRecorder,
    *,
    extra_urls: Optional[list[tuple[str, str]]] = None,
    extras_only: bool = False,
    already_fetched: Optional[set[str]] = None,
    page_budget: int = MAX_PAGES,
) -> dict[str, Any]:
    dbg.stage_start("fetch")
    already = set(already_fetched or [])
    url_plan: list[tuple[str, str]] = []

    if not extras_only:
        for role, url in [
            ("auth", discover.get("auth_url")),
            ("pricing", discover.get("pricing_url")),
            ("api_index", discover.get("api_index_url")),
            ("openapi", discover.get("openapi_url")),
            ("webhooks", discover.get("webhooks_url")),
            ("mcp", discover.get("mcp_url")),
        ]:
            if url:
                url_plan.append((role, url))
    if extra_urls:
        url_plan.extend(extra_urls)

    seen: set[str] = set(already)
    plan: list[tuple[str, str]] = []
    for role, url in url_plan:
        if not url or url in seen:
            continue
        seen.add(url)
        plan.append((role, url))
        if len(plan) >= page_budget:
            break

    urls = [u for _, u in plan]
    extracted = tv.extract_batch(urls) if urls else []
    by_url = {e["url"]: e for e in extracted}

    pages: list[dict] = []
    flags: list[str] = []
    sources: list[str] = []
    app_name = discover.get("app_name") or "app"

    for role, url in plan:
        item = by_url.get(url) or {"url": url, "markdown": "", "error": "missing"}
        md = item.get("markdown") or ""
        err = item.get("error")
        kept = bool(md) and not err
        dbg.add_extract(url, md, err, kept=kept)
        print(f"[fetch] {app_name} url={url} err={err} kept={kept}")
        if not kept:
            continue
        raw_len = len(md)
        text = md
        if raw_len > CLEAN_CAP:
            chunks = chunk_text(md, size=15_000, max_chunks=12)
            hits = []
            for i, ch in enumerate(chunks):
                filtered = chunk_filter_call(ch, app_name, i)
                if filtered.strip().upper() != "NONE":
                    hits.append(filtered)
            text = "\n".join(hits) if hits else md[:CLEAN_CAP]
            if "chunked" not in flags:
                flags.append("chunked")

        cleaned, thin = clean_page(text, max_chars=CLEAN_CAP)
        if thin and "thin_content" not in flags:
            flags.append("thin_content")
        pages.append({"role": role, "url": url, "text": cleaned, "raw_len": raw_len})
        sources.append(url)

    dbg.stage_end("fetch", pages=len(pages), sources=sources)
    return {"pages": pages, "flags": flags, "sources_fetched": sources}


def node_extract(
    app: dict,
    discover: dict,
    pages: list[dict],
    dbg: DebugRecorder,
    *,
    repair_error: Optional[str] = None,
    field_subset: Optional[list[str]] = None,
) -> dict[str, Any]:
    dbg.stage_start("extract" + ("_repair" if repair_error else "") + ("_r2" if field_subset else ""))
    system = (PROMPTS / "call2_extract.txt").read_text(encoding="utf-8")
    body = assemble_extract_input(pages, total_cap=EXTRACT_TOTAL_CAP)
    prior = discover.get("business_type", "unknown")
    user = (
        f"app_name: {app['app_name']}\n"
        f"category: {app.get('category')}\n"
        f"business_type PRIOR (do not overwrite): {prior}\n"
        f"first_party_domains: {json.dumps(discover.get('first_party_domains'))}\n"
    )
    if field_subset:
        user += (
            f"SECOND ROUND: fill ONLY these fields if currently unknown: {field_subset}\n"
            "Do not invent values for other fields; omit them or set unknown.\n"
        )
    if repair_error:
        user += f"VALIDATION ERROR from previous attempt: {repair_error}\nFix and return full JSON.\n"
    user += f"\nPAGES:\n{body}"
    full_prompt = f"{system}\n\n---\n\n{user}"

    cache_payload = {
        "prompts_version": PROMPTS_VERSION,
        "hint_url": app.get("hint_url"),
        "hint_note": app.get("hint_note"),
        "seeded": discover.get("_seeded_domains"),
        "sources": [p["url"] for p in pages],
        "repair": repair_error,
        "subset": field_subset,
        "body_hash": str(hash(body)),
    }

    raw = generate_json(
        app_name=app["app_name"],
        call_name="extract"
        + ("_round2" if field_subset else "")
        + ("_repair" if repair_error else ""),
        system_prompt=system,
        user_prompt=user,
        cache_payload=cache_payload,
        temperature=0.0,
    )
    dbg.add_gemini("extract", full_prompt[:50000], raw)
    dbg.stage_end("extract")
    return raw


def validate_extract(data: dict[str, Any]) -> Optional[str]:
    errors = []
    skip = {"buildability", "blocker_type", "unblocker", "access_tier_rollup", "business_type"}
    for field, allowed in ALLOWED_VALUES.items():
        if field in skip or field not in data:
            continue
        val = data[field]
        if field == "business_type_supported":
            if val not in ("yes", "no"):
                errors.append("business_type_supported must be yes|no")
            continue
        if field in GEMINI_FACT_FIELDS or field in ("docs_access",):
            if val not in allowed:
                errors.append(f"{field}={val} not in {allowed}")
    if data.get("access_tier") == "self_hosted":
        errors.append("self_hosted retired")
    try:
        ExtractResult.model_validate({k: data.get(k) for k in ExtractResult.model_fields})
    except Exception as e:
        errors.append(str(e))
    return "; ".join(errors) if errors else None


def merge_extract(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    out = dict(first)
    notes = [out.get("notes") or ""]
    ev1 = dict(out.get("evidence") or {})
    ev2 = dict(second.get("evidence") or {})
    conf = dict(out.get("confidence") or {})

    fields = list(GEMINI_FACT_FIELDS) + [
        "auth_detail",
        "access_cost_note",
        "one_liner",
        "business_type_supported",
        "notes",
    ]
    for field in fields:
        old = out.get(field)
        new = second.get(field)
        if new in (None, "", [], "unknown"):
            continue
        old_ev = ev1.get(field)
        sourced = old not in (None, "", [], "unknown") and bool(old_ev)
        if sourced:
            if new != old:
                notes.append(f"contradiction {field}: kept {old!r}, second said {new!r}")
            continue
        out[field] = new
        if field in ev2:
            ev1[field] = ev2[field]
        if field in (second.get("confidence") or {}):
            conf[field] = second["confidence"][field]

    out["evidence"] = ev1
    out["confidence"] = conf
    out["notes"] = " | ".join(n for n in notes if n)
    return out


def needs_second_round(row: dict[str, Any]) -> list[str]:
    return [f for f in SECOND_ROUND_PRIORITY if row.get(f) in (None, "", "unknown")]


def second_round_targets(
    missing: list[str], app: dict, discover: dict, tv: TavilyClient, dbg: DebugRecorder
) -> list[tuple[str, str]]:
    name = app["app_name"]
    query_map = {
        "access_tier": f"{name} API access pricing plan documentation",
        "auth_primary": f"{name} API authentication documentation",
        "api_type": f"{name} REST GraphQL API reference",
        "has_openapi_spec": f"{name} OpenAPI Swagger specification",
        "has_webhooks": f"{name} API webhooks documentation",
        "mcp_exists": f"{name} MCP server Model Context Protocol",
    }
    role_map = {
        "access_tier": "pricing",
        "auth_primary": "auth",
        "api_type": "api_index",
        "has_openapi_spec": "openapi",
        "has_webhooks": "webhooks",
        "mcp_exists": "mcp",
    }
    extras: list[tuple[str, str]] = []
    calls = 0
    existing = {
        discover.get("auth_url"),
        discover.get("pricing_url"),
        discover.get("api_index_url"),
        discover.get("openapi_url"),
        discover.get("webhooks_url"),
        discover.get("mcp_url"),
    }
    from pipeline.domains import domain_in_first_party

    for field in missing:
        if calls >= SECOND_ROUND_SEARCH_CAP:
            break
        q = query_map.get(field)
        if not q:
            continue
        results = tv.search(q, limit=5)
        calls += 1
        dbg.add_search(q, results)
        fp = list(discover.get("first_party_domains") or [])
        for r in results:
            url = r.get("url") or ""
            if not url or url in existing:
                continue
            if domain_in_first_party(url, fp):
                extras.append((role_map.get(field, "api_index"), url))
                existing.add(url)
                break
    return extras


def build_row(
    app: dict,
    discover: dict,
    extract: dict,
    *,
    sources_fetched: list[str],
    flags: list[str],
    run_id: str,
    dbg: DebugRecorder,
) -> dict[str, Any]:
    """Stage 1: facts + audit only. No derived verdict fields."""
    row: dict[str, Any] = {
        "app_name": app["app_name"],
        "category": app.get("category"),
        "one_liner": extract.get("one_liner") or discover.get("one_liner") or "",
        "business_type": discover.get("business_type"),
        "docs_access": extract.get("docs_access") or "unknown",
        "auth_primary": extract.get("auth_primary") or "unknown",
        "auth_detail": extract.get("auth_detail") or "",
        "access_tier": extract.get("access_tier") or "unknown",
        "access_cost_note": extract.get("access_cost_note") or "",
        "api_type": extract.get("api_type") or "unknown",
        "has_openapi_spec": extract.get("has_openapi_spec") or "unknown",
        "needs_instance_url": extract.get("needs_instance_url") or "unknown",
        "has_webhooks": extract.get("has_webhooks") or "unknown",
        "mcp_exists": extract.get("mcp_exists") or "unknown",
        "is_open_source": extract.get("is_open_source") or "unknown",
        "evidence": extract.get("evidence") or {},
        "confidence": extract.get("confidence") or {},
        "flags": list(flags),
        "sources_fetched": sources_fetched,
        "first_party_domains": discover.get("first_party_domains") or [],
        "backup_links": discover.get("backup_links") or [],
        "notes": extract.get("notes") or "",
        "run_id": run_id,
    }
    if extract.get("business_type_supported") == "no":
        if "business_type_unconfirmed" not in row["flags"]:
            row["flags"].append("business_type_unconfirmed")

    cli = row.get("api_type") == "cli_only"
    before = {f: row.get(f) for f in GEMINI_FACT_FIELDS}
    row = apply_guard(row, cli_shortcircuit=cli, dbg=dbg)
    for f in GEMINI_FACT_FIELDS:
        if before.get(f) != row.get(f):
            dbg.add_guard_change(f, before.get(f), row.get(f), "guard")
    return row
