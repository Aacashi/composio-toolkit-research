"""Individual pipeline node functions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pipeline.clean import assemble_extract_input, chunk_text, clean_page
from pipeline.domains import merge_discovered_domains, seed_first_party_domains
from pipeline.firecrawl_client import FirecrawlClient
from pipeline.gemini_client import chunk_filter_call, generate_json, parse_json_loose
from pipeline.guard import apply_guard
from pipeline.verdict import derive_verdict
from schema import (
    ALLOWED_VALUES,
    ATOMIC_ENUM_FIELDS,
    PROMPTS_VERSION,
    ExtractResult,
)

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CLEAN_CAP = 10_000
EXTRACT_TOTAL_CAP = 40_000
MAX_PAGES = 6
SECOND_ROUND_SEARCH_CAP = 2

SECOND_ROUND_TRIGGERS = (
    "access_tier",
    "auth_primary",
    "api_type",
    "has_openapi_spec",
    "has_webhooks",
    "mcp_exists",
)

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
    fc: FirecrawlClient,
    *,
    failure_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Call 1: discover URLs + business_type prior. Max 4 search tool calls (manual loop)."""
    seeded = seed_first_party_domains(app)
    system = (PROMPTS / "call1_discover.txt").read_text(encoding="utf-8")

    user_parts = [
        f"app_name: {app['app_name']}",
        f"category: {app.get('category')}",
        f"hint_type: {app.get('hint_type')}",
        f"hint_url: {app.get('hint_url')}",
        f"hint_note: {app.get('hint_note')}",
        f"hint_raw: {app.get('hint_raw')}",
        f"SEEDED first_party_domains: {json.dumps(seeded)}",
    ]
    if failure_reason:
        user_parts.append(
            f"PREVIOUS FETCH FAILED: {failure_reason}. "
            "Propose alternative first-party auth/pricing/api URLs."
        )
    if app.get("hint_type") == "docs_url" and app.get("hint_url"):
        user_parts.append(
            f"STRONG SEED docs_url: {app['hint_url']} — treat as likely api_index_url or auth_url."
        )
    if app.get("hint_type") == "note" and app.get("hint_note"):
        user_parts.append(
            f"NOTE (context only, NEVER an answer): {app['hint_note']}"
        )

    # Manual search loop (up to 4), then final JSON synthesis from observations
    observations: list[str] = []
    tool_calls = 0

    # If docs_url, no search required first — still allow searches for pricing/auth
    queries = _discover_queries(app)
    for q in queries:
        if tool_calls >= 4:
            break
        results = fc.search(q, limit=5)
        tool_calls += 1
        observations.append(f"SEARCH q={q!r} -> {json.dumps(results)[:3000]}")

    user_parts.append("OBSERVATIONS:\n" + "\n".join(observations))
    user_prompt = "\n".join(user_parts)

    cache_payload = {
        "prompts_version": PROMPTS_VERSION,
        "hint_type": app.get("hint_type"),
        "hint_url": app.get("hint_url"),
        "hint_note": app.get("hint_note"),
        "hint_raw": app.get("hint_raw"),
        "seeded_domains": seeded,
        "failure_reason": failure_reason,
        "observations_hash": str(hash(tuple(observations))),
    }

    data = generate_json(
        app_name=app["app_name"],
        call_name="discover" + ("_retry" if failure_reason else ""),
        system_prompt=system,
        user_prompt=user_prompt,
        cache_payload=cache_payload,
        temperature=0.0,
    )

    discovered_domains = data.get("first_party_domains") or []
    data["first_party_domains"] = merge_discovered_domains(seeded, discovered_domains)
    data["_seeded_domains"] = seeded
    data["_tool_calls"] = tool_calls
    return data


def _discover_queries(app: dict) -> list[str]:
    name = app["app_name"]
    domain = ""
    if app.get("hint_url"):
        from urllib.parse import urlparse

        domain = urlparse(app["hint_url"]).hostname or ""
    qs = [
        f"{name} API authentication documentation",
        f"{name} API pricing access tier",
        f"{name} API reference OpenAPI",
    ]
    if domain:
        qs.insert(0, f"site:{domain} API authentication")
    return qs[:4]


def node_fetch(
    discover: dict,
    fc: FirecrawlClient,
    *,
    extra_urls: Optional[list[tuple[str, str]]] = None,
) -> dict[str, Any]:
    """
    Fetch pages in priority order. Returns {pages: [{role,url,text,raw_len}], flags, sources}.
    """
    url_plan: list[tuple[str, str]] = []
    mapping = [
        ("auth", discover.get("auth_url")),
        ("pricing", discover.get("pricing_url")),
        ("api_index", discover.get("api_index_url")),
        ("openapi", discover.get("openapi_url")),
        ("webhooks", discover.get("webhooks_url")),
        ("mcp", discover.get("mcp_url")),
    ]
    for role, url in mapping:
        if url:
            url_plan.append((role, url))
    if extra_urls:
        url_plan.extend(extra_urls)

    # dedupe by url, keep first role, max MAX_PAGES
    seen: set[str] = set()
    plan: list[tuple[str, str]] = []
    for role, url in url_plan:
        if not url or url in seen:
            continue
        seen.add(url)
        plan.append((role, url))
        if len(plan) >= MAX_PAGES:
            break

    pages: list[dict] = []
    flags: list[str] = []
    sources: list[str] = []

    for role, url in plan:
        md, err = fc.scrape(url)
        if err or not md:
            print(f"[fetch] skip {url}: {err}")
            continue
        raw_len = len(md)
        text = md
        if raw_len > CLEAN_CAP:
            # chunk filter then concatenate (LOGIC_FREEZE FIX 1)
            chunks = chunk_text(md, size=15_000, max_chunks=12)
            hits = []
            for i, ch in enumerate(chunks):
                filtered = chunk_filter_call(ch, discover.get("app_name") or "app", i)
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

    return {"pages": pages, "flags": flags, "sources_fetched": sources}


def node_extract(
    app: dict,
    discover: dict,
    pages: list[dict],
    *,
    repair_error: Optional[str] = None,
    field_subset: Optional[list[str]] = None,
) -> dict[str, Any]:
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
        call_name="extract" + ("_round2" if field_subset else "") + ("_repair" if repair_error else ""),
        system_prompt=system,
        user_prompt=user,
        cache_payload=cache_payload,
        temperature=0.0,
    )
    return raw


def validate_extract(data: dict[str, Any]) -> Optional[str]:
    errors = []
    for field, allowed in ALLOWED_VALUES.items():
        if field in ("buildability", "blocker_type", "unblocker", "wait_class", "business_type"):
            continue
        if field not in data:
            continue
        val = data[field]
        if field == "auth_secondary":
            if not isinstance(val, list):
                errors.append("auth_secondary must be list")
            else:
                for v in val:
                    if v not in ALLOWED_VALUES["auth_primary"]:
                        errors.append(f"auth_secondary bad value {v}")
            continue
        if field == "business_type_confirmed":
            if val not in ("yes", "no"):
                errors.append("business_type_confirmed must be yes|no")
            continue
        if field in ALLOWED_VALUES and field in data:
            if val not in allowed and field in ATOMIC_ENUM_FIELDS:
                errors.append(f"{field}={val} not in {allowed}")
    # access_tier must not be self_hosted
    if data.get("access_tier") == "self_hosted":
        errors.append("self_hosted retired")
    try:
        ExtractResult.model_validate(
            {k: data.get(k) for k in ExtractResult.model_fields}
        )
    except Exception as e:
        errors.append(str(e))
    return "; ".join(errors) if errors else None


def merge_extract(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Second fills unknowns only; contradictions -> notes."""
    out = dict(first)
    notes = [out.get("notes") or ""]
    ev1 = dict(out.get("evidence") or {})
    ev2 = dict(second.get("evidence") or {})
    conf = dict(out.get("confidence") or {})

    for field in list(ATOMIC_ENUM_FIELDS) + ["auth_detail", "access_cost_note", "rate_limit_note", "mcp_access", "business_type_confirmed", "one_liner"]:
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
        # fill unknown
        out[field] = new
        if field in ev2:
            ev1[field] = ev2[field]
        if field in (second.get("confidence") or {}):
            conf[field] = second["confidence"][field]

    # auth_secondary
    if (not out.get("auth_secondary")) and second.get("auth_secondary"):
        out["auth_secondary"] = second["auth_secondary"]

    out["evidence"] = ev1
    out["confidence"] = conf
    out["notes"] = " | ".join(n for n in notes if n)
    return out


def needs_second_round(row: dict[str, Any]) -> list[str]:
    missing = []
    for f in SECOND_ROUND_PRIORITY:
        if row.get(f) in (None, "", "unknown"):
            missing.append(f)
    return missing


def second_round_targets(missing: list[str], app: dict, discover: dict, fc: FirecrawlClient) -> list[tuple[str, str]]:
    """Search up to 2 queries prioritized; return extra (role,url) pairs."""
    name = app["app_name"]
    query_map = {
        "access_tier": f"{name} API access pricing plan documentation site",
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
    for field in missing:
        if calls >= SECOND_ROUND_SEARCH_CAP:
            break
        q = query_map.get(field)
        if not q:
            continue
        results = fc.search(q, limit=5)
        calls += 1
        fp = set(discover.get("first_party_domains") or [])
        for r in results:
            url = r.get("url") or ""
            if not url or url in existing:
                continue
            from pipeline.domains import domain_in_first_party

            if domain_in_first_party(url, list(fp)):
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
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "app_name": app["app_name"],
        "category": app.get("category"),
        "one_liner": extract.get("one_liner") or discover.get("one_liner") or "",
        "business_type": discover.get("business_type"),
        "business_type_confirmed": extract.get("business_type_confirmed") or "no",
        "docs_access": extract.get("docs_access") or "unknown",
        "docs_location": extract.get("docs_location") or "none",
        "auth_primary": extract.get("auth_primary") or "unknown",
        "auth_secondary": extract.get("auth_secondary") or [],
        "auth_detail": extract.get("auth_detail") or "",
        "access_tier": extract.get("access_tier") or "unknown",
        "access_cost_note": extract.get("access_cost_note") or "",
        "api_type": extract.get("api_type") or "unknown",
        "api_breadth": extract.get("api_breadth") or "unknown",
        "has_openapi_spec": extract.get("has_openapi_spec") or "unknown",
        "needs_instance_url": extract.get("needs_instance_url") or "unknown",
        "has_webhooks": extract.get("has_webhooks") or "unknown",
        "rate_limit_note": extract.get("rate_limit_note") or "",
        "mcp_exists": extract.get("mcp_exists") or "unknown",
        "mcp_access": extract.get("mcp_access") or "n_a",
        "evidence": extract.get("evidence") or {},
        "confidence": extract.get("confidence") or {},
        "flags": flags,
        "sources_fetched": sources_fetched,
        "first_party_domains": discover.get("first_party_domains") or [],
        "backup_links": discover.get("backup_links") or [],
        "notes": extract.get("notes") or "",
        "run_id": run_id,
    }
    cli = row.get("api_type") == "cli_tool"
    row = apply_guard(row, cli_shortcircuit=cli)
    row = derive_verdict(row)
    return row
