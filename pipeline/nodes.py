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
from pipeline.url_check import url_is_live
from schema import (
    ALLOWED_VALUES,
    GEMINI_EMIT_FIELDS,
    GEMINI_FACT_FIELDS,
    PROMPTS_VERSION,
    ExtractResult,
)

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CLEAN_CAP = 10_000
EXTRACT_TOTAL_CAP = 40_000
MAX_PAGES = 6
SECOND_ROUND_SEARCH_CAP = 2

PRICING_URL_HINTS = ("pricing", "plans", "/price", "subscription", "billing")
AUTH_URL_HINTS = (
    "auth",
    "oauth",
    "api-key",
    "apikey",
    "api_key",
    "token",
    "authentication",
    "login",
    "security-and-auth",
)
MCP_URL_HINTS = ("mcp", "model-context", "modelcontextprotocol")
JUNK_URL_MARKERS = (
    "/_next/image",
    "/static/",
    "/assets/",
    "/l/zh/",
    "/l/ja/",
    "/l/ko/",
    "/l/es/",
    "/l/fr/",
    "/l/de/",
)
JUNK_URL_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".map",
    ".woff",
    ".woff2",
)

SECOND_ROUND_PRIORITY = (
    "pricing_coverage",
    "auth_coverage",
    "integration_paths",
    "private_path_access",
    "public_path_access",
    "auth_primary",
    "api_type",
    "has_openapi_spec",
    "has_webhooks",
    "mcp_exists",
)


def sources_have_pricing(sources: list[str]) -> bool:
    return any(
        any(h in (u or "").lower() for h in PRICING_URL_HINTS) for u in (sources or [])
    )


def sources_have_auth(sources: list[str]) -> bool:
    return any(any(h in (u or "").lower() for h in AUTH_URL_HINTS) for u in (sources or []))


def sources_have_mcp(sources: list[str]) -> bool:
    return any(any(h in (u or "").lower() for h in MCP_URL_HINTS) for u in (sources or []))


def is_junk_url(url: str) -> bool:
    u = (url or "").lower().split("?", 1)[0]
    if any(m in u for m in JUNK_URL_MARKERS):
        return True
    return any(u.endswith(sfx) for sfx in JUNK_URL_SUFFIXES)


def provisional_access_tier(extract: dict[str, Any]) -> str:
    """Derive tier from extract path fields without guard."""
    row = {
        "integration_paths": extract.get("integration_paths") or "unknown",
        "private_path_access": extract.get("private_path_access") or "unknown",
        "public_path_access": extract.get("public_path_access") or "n_a",
        "flags": [],
        "evidence": dict(extract.get("evidence") or {}),
    }
    return derive_access_tier_from_paths(row).get("access_tier") or "unknown"


def coerce_uncited_path_fields(data: dict[str, Any]) -> dict[str, Any]:
    """After failed repair: uncited concrete path values become unknown."""
    evidence = dict(data.get("evidence") or {})
    for field in ("integration_paths", "private_path_access", "public_path_access"):
        val = data.get(field)
        if val in (None, "", "unknown", "n_a"):
            continue
        if not evidence.get(field):
            data[field] = "unknown"
    data["evidence"] = evidence
    return data


def null_dead_discover_urls(discover: dict[str, Any]) -> list[str]:
    """Null auth/pricing URLs that fail liveness. Return flag names to attach."""
    flags: list[str] = []
    for key, flag in (
        ("auth_url", "no_auth_page_fetched"),
        ("pricing_url", "no_pricing_page_fetched"),
    ):
        url = discover.get(key)
        if not url:
            if flag not in flags:
                flags.append(flag)
            continue
        if not url_is_live(url):
            print(f"[discover] dead {key}={url} — nulling")
            discover[key] = None
            flags.append(flag)
            if "dead_url_skipped" not in flags:
                flags.append("dead_url_skipped")
    if not discover.get("auth_url") and "no_auth_page_fetched" not in flags:
        flags.append("no_auth_page_fetched")
    if not discover.get("pricing_url") and "no_pricing_page_fetched" not in flags:
        flags.append("no_pricing_page_fetched")
    return flags


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
    data["_discover_flags"] = null_dead_discover_urls(data)
    dbg.stage_end(
        "discover",
        business_type=data.get("business_type"),
        tool_calls=tool_calls,
        urls={
            "auth": data.get("auth_url"),
            "pricing": data.get("pricing_url"),
            "api_index": data.get("api_index_url"),
        },
        discover_flags=data.get("_discover_flags"),
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
    flags: list[str] = []
    for role, url in url_plan:
        if not url or url in seen:
            continue
        if is_junk_url(url):
            print(f"[fetch] junk url={url} — skipping")
            if "junk_url_skipped" not in flags:
                flags.append("junk_url_skipped")
            continue
        if not url_is_live(url):
            print(f"[fetch] dead url={url} — skipping extract")
            if "dead_url_skipped" not in flags:
                flags.append("dead_url_skipped")
            continue
        seen.add(url)
        plan.append((role, url))
        if len(plan) >= page_budget:
            break

    urls = [u for _, u in plan]
    extracted = tv.extract_batch(urls) if urls else []
    by_url = {e["url"]: e for e in extracted}

    pages: list[dict] = []
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
        pages.append(
            {
                "role": role,
                "url": url,
                "text": cleaned,
                "raw_len": raw_len,
                "thin": thin,
            }
        )
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
    skip = {
        "buildability",
        "blocker_type",
        "unblocker",
        "access_tier_rollup",
        "business_type",
        "access_tier",  # derived in code — must not be required from Gemini
    }
    for field, allowed in ALLOWED_VALUES.items():
        if field in skip or field not in data:
            continue
        val = data[field]
        if field == "business_type_supported":
            if val not in ("yes", "no"):
                errors.append("business_type_supported must be yes|no")
            continue
        if field in GEMINI_EMIT_FIELDS or field in ("docs_access", "private_path_access", "public_path_access"):
            if val not in allowed:
                errors.append(f"{field}={val} not in {allowed}")
    if data.get("access_tier") == "self_hosted":
        errors.append("self_hosted retired")

    evidence = data.get("evidence") or {}
    for field in ("integration_paths", "private_path_access", "public_path_access"):
        val = data.get(field)
        if val in (None, "", "unknown", "n_a"):
            continue
        if not evidence.get(field):
            errors.append(
                f"{field}={val} requires evidence[{field}] cite a SOURCE url "
                "(or set the field to unknown)"
            )

    try:
        payload = {k: data.get(k) for k in ExtractResult.model_fields}
        ExtractResult.model_validate(payload)
    except Exception as e:
        errors.append(str(e))
    return "; ".join(errors) if errors else None


def derive_access_tier_from_paths(row: dict[str, Any]) -> dict[str, Any]:
    """Select access_tier from structured path fields. Never trust Gemini access_tier."""
    paths = row.get("integration_paths") or "unknown"
    private = row.get("private_path_access") or "unknown"
    public = row.get("public_path_access") or "n_a"
    flags: list[str] = list(row.get("flags") or [])
    evidence: dict[str, str] = dict(row.get("evidence") or {})

    if paths == "two_paths":
        tier = public if public not in (None, "", "n_a") else "unknown"
        row["access_tier"] = tier
        if "path_selection_applied" not in flags:
            flags.append("path_selection_applied")
        if evidence.get("public_path_access"):
            evidence["access_tier"] = evidence["public_path_access"]
    elif paths == "one_path":
        tier = private if private not in (None, "", "n_a") else "unknown"
        row["access_tier"] = tier
        if evidence.get("private_path_access"):
            evidence["access_tier"] = evidence["private_path_access"]
    else:
        row["access_tier"] = "unknown"

    row["flags"] = flags
    row["evidence"] = evidence
    return row


def merge_extract(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    out = dict(first)
    notes = [out.get("notes") or ""]
    ev1 = dict(out.get("evidence") or {})
    ev2 = dict(second.get("evidence") or {})
    conf = dict(out.get("confidence") or {})

    fields = list(GEMINI_EMIT_FIELDS) + [
        "auth_detail",
        "access_cost_note",
        "one_liner",
        "business_type_supported",
        "path_evidence",
        "notes",
    ]
    for field in fields:
        old = out.get(field)
        new = second.get(field)
        if new in (None, "", [], "unknown", "n_a"):
            # Allow filling n_a only when old is empty/unknown for path fields
            if field in ("public_path_access", "private_path_access") and new == "n_a":
                if old in (None, "", "unknown"):
                    out[field] = new
                continue
            continue
        old_ev = ev1.get(field)
        sourced = old not in (None, "", [], "unknown", "n_a") and bool(old_ev)
        if sourced:
            if new != old:
                notes.append(f"contradiction {field}: kept {old!r}, second said {new!r}")
            continue
        out[field] = new
        if field in ev2:
            ev1[field] = ev2[field]
        if field in (second.get("confidence") or {}):
            conf[field] = second["confidence"][field]

    if second.get("path_evidence") and not (out.get("path_evidence") or "").strip():
        out["path_evidence"] = second.get("path_evidence")

    out["evidence"] = ev1
    out["confidence"] = conf
    out["notes"] = " | ".join(n for n in notes if n)
    return out


def needs_second_round(
    row: dict[str, Any],
    *,
    sources: Optional[list[str]] = None,
) -> list[str]:
    """
    Fields / synthetic triggers for the single targeted second round.
    Includes missing pricing coverage and provisional unknown access_tier.
    """
    missing: list[str] = []
    src = list(sources or [])
    if not sources_have_pricing(src):
        missing.append("pricing_coverage")
    if not sources_have_auth(src):
        missing.append("auth_coverage")

    for f in SECOND_ROUND_PRIORITY:
        if f in ("pricing_coverage", "auth_coverage"):
            continue
        if row.get(f) in (None, "", "unknown"):
            # MCP nudge: only chase when unknown AND no MCP-ish source yet
            if f == "mcp_exists" and sources_have_mcp(src):
                continue
            missing.append(f)

    # Provisional derived tier unknown → chase path + pricing evidence
    if provisional_access_tier(row) == "unknown":
        for f in ("integration_paths", "private_path_access", "public_path_access", "pricing_coverage"):
            if f not in missing:
                if f == "pricing_coverage" and sources_have_pricing(src):
                    continue
                missing.append(f)
    return missing


def second_round_targets(
    missing: list[str], app: dict, discover: dict, tv: TavilyClient, dbg: DebugRecorder
) -> list[tuple[str, str]]:
    name = app["app_name"]
    query_map = {
        "pricing_coverage": [
            f"{name} pricing",
            f"{name} API pricing plans",
        ],
        "auth_coverage": [
            f"{name} API authentication documentation",
            f"{name} OAuth API key auth",
        ],
        "integration_paths": [f"{name} public integration app review vs private custom app"],
        "private_path_access": [f"{name} API pricing plans access"],
        "public_path_access": [f"{name} public app review marketplace pricing"],
        "auth_primary": [f"{name} API authentication documentation"],
        "api_type": [f"{name} REST GraphQL API reference"],
        "has_openapi_spec": [f"{name} OpenAPI Swagger specification"],
        "has_webhooks": [f"{name} API webhooks documentation"],
        "mcp_exists": [f"{name} MCP server Model Context Protocol"],
    }
    role_map = {
        "pricing_coverage": "pricing",
        "auth_coverage": "auth",
        "integration_paths": "pricing",
        "private_path_access": "pricing",
        "public_path_access": "pricing",
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
        queries = query_map.get(field) or []
        for q in queries:
            if calls >= SECOND_ROUND_SEARCH_CAP:
                break
            results = tv.search(q, limit=5)
            calls += 1
            dbg.add_search(q, results)
            fp = list(discover.get("first_party_domains") or [])
            picked = None
            for r in results:
                url = r.get("url") or ""
                if not url or url in existing:
                    continue
                if not domain_in_first_party(url, fp):
                    continue
                if field == "pricing_coverage":
                    if any(h in url.lower() for h in PRICING_URL_HINTS):
                        picked = url
                        break
                    if picked is None:
                        picked = url  # fallback: first first-party hit
                    continue
                if field == "auth_coverage":
                    if any(h in url.lower() for h in AUTH_URL_HINTS):
                        picked = url
                        break
                    if picked is None:
                        picked = url
                    continue
                if field == "mcp_exists":
                    if any(h in url.lower() for h in MCP_URL_HINTS):
                        picked = url
                        break
                    if picked is None:
                        picked = url
                    continue
                picked = url
                break
            if picked:
                extras.append((role_map.get(field, "api_index"), picked))
                existing.add(picked)
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
    pages: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Stage 1: facts + audit only. access_tier derived from path fields."""
    row: dict[str, Any] = {
        "app_name": app["app_name"],
        "category": app.get("category"),
        "one_liner": extract.get("one_liner") or discover.get("one_liner") or "",
        "business_type": discover.get("business_type"),
        "docs_access": extract.get("docs_access") or "unknown",
        "auth_primary": extract.get("auth_primary") or "unknown",
        "auth_detail": extract.get("auth_detail") or "",
        "access_cost_note": extract.get("access_cost_note") or "",
        "api_type": extract.get("api_type") or "unknown",
        "has_openapi_spec": extract.get("has_openapi_spec") or "unknown",
        "needs_instance_url": extract.get("needs_instance_url") or "unknown",
        "has_webhooks": extract.get("has_webhooks") or "unknown",
        "mcp_exists": extract.get("mcp_exists") or "unknown",
        "is_open_source": extract.get("is_open_source") or "unknown",
        "integration_paths": extract.get("integration_paths") or "unknown",
        "private_path_access": extract.get("private_path_access") or "unknown",
        "public_path_access": extract.get("public_path_access") or "n_a",
        "path_evidence": extract.get("path_evidence") or "",
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
    # OFFLINE_GUARDS: skip apply_guard during publish; store raw for later.
    # row = apply_guard(row, cli_shortcircuit=cli, dbg=dbg, pages=pages or [])
    _ = (cli, apply_guard)  # keep import used for offline / re-enable
    row = derive_access_tier_from_paths(row)
    row["guard_applied"] = False
    row["pages_meta"] = [
        {
            "url": p.get("url"),
            "role": p.get("role"),
            "thin": bool(p.get("thin")),
            "char_len": len(p.get("text") or ""),
        }
        for p in (pages or [])
        if p.get("url")
    ]
    for f in GEMINI_FACT_FIELDS:
        if before.get(f) != row.get(f):
            dbg.add_guard_change(f, before.get(f), row.get(f), "derive")
    return row
