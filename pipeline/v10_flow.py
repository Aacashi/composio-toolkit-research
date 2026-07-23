"""v10 Stage-1: Plan (Gemini) → Gather (Tavily in code) → Fill (Gemini). Max 2 Gemini calls."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from pipeline.clean import assemble_extract_input, clean_page
from pipeline.debug_log import DebugRecorder
from pipeline.domains import (
    domain_in_first_party,
    host_of,
    merge_discovered_domains,
    seed_first_party_domains,
)
from pipeline.gemini_client import generate_json
from pipeline.tavily_client import (
    CRAWL_LIMIT_CAP,
    DEFAULT_CRAWL_EXCLUDE,
    DEFAULT_CRAWL_SELECT,
    TavilyClient,
)
from pipeline.url_check import url_is_live
from schema import PROMPTS_VERSION

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

CLEAN_CAP = 10_000
EXTRACT_TOTAL_CAP = 40_000
MAX_SEARCHES = 2
MAX_EXTRACT_URLS = 6
SEARCH_RESULT_LIMIT = 5

URL_ROLE_HINTS = (
    ("pricing", ("pricing", "plans", "/price", "subscription", "billing")),
    ("auth", ("auth", "oauth", "api-key", "apikey", "token", "authentication", "login")),
    ("mcp", ("mcp", "model-context")),
    ("openapi", ("openapi", "swagger", "openapi.json", "openapi.yaml")),
    ("webhooks", ("webhook", "callbacks")),
    ("api_index", ("/api", "developers", "docs", "reference")),
)

DEFAULT_FOLLOW_HINTS = (
    "pricing",
    "plans",
    "billing",
    "oauth",
    "marketplace",
    "/apps",
    "openapi",
    "swagger",
    "webhook",
    "mcp",
    "authentication",
    "api-key",
    "api_keys",
)

MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
RAW_URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")


def _guess_role(url: str) -> str:
    u = (url or "").lower()
    for role, hints in URL_ROLE_HINTS:
        if any(h in u for h in hints):
            return role
    return "api_index"


def _has_auth_like(urls: list[str]) -> bool:
    return any(_guess_role(u) == "auth" for u in urls)


def _has_pricing_like(urls: list[str]) -> bool:
    return any(_guess_role(u) == "pricing" for u in urls)


def _normalize_plan(raw: dict[str, Any], seeded: list[str]) -> dict[str, Any]:
    searches_in = raw.get("searches") or []
    searches: list[dict[str, Any]] = []
    for s in searches_in[:MAX_SEARCHES]:
        if isinstance(s, str):
            searches.append({"query": s, "include_domains": list(seeded)[:3] or None})
        elif isinstance(s, dict) and s.get("query"):
            doms = s.get("include_domains")
            if not doms:
                doms = list(seeded)[:3] or None
            searches.append({"query": str(s["query"]), "include_domains": doms})

    must: list[str] = []
    for u in raw.get("must_extract") or []:
        if isinstance(u, str) and u.startswith("http") and u not in must:
            must.append(u)

    hints = [
        str(h).lower()
        for h in (raw.get("follow_link_hints") or [])
        if h
    ]
    for h in DEFAULT_FOLLOW_HINTS:
        if h not in hints:
            hints.append(h)

    crawl = raw.get("crawl")
    crawl_out: Optional[dict[str, Any]] = None
    if isinstance(crawl, dict) and crawl.get("url"):
        crawl_out = {
            "url": str(crawl["url"]),
            "select_paths": list(crawl.get("select_paths") or DEFAULT_CRAWL_SELECT),
            "exclude_paths": list(crawl.get("exclude_paths") or DEFAULT_CRAWL_EXCLUDE),
            "limit": min(int(crawl.get("limit") or CRAWL_LIMIT_CAP), CRAWL_LIMIT_CAP),
        }

    bt = raw.get("business_type") or "ai_native"
    return {
        "business_type": bt,
        "searches": searches,
        "must_extract": must,
        "follow_link_hints": hints,
        "crawl": crawl_out,
        "first_party_domains": list(seeded),
        "backup_links": [],
        "one_liner": "",
    }


def node_plan(
    app: dict,
    tv: TavilyClient,
    dbg: DebugRecorder,
    *,
    failure_reason: Optional[str] = None,
    gemini_calls: list[int],
) -> dict[str, Any]:
    dbg.stage_start("plan")
    seeded = seed_first_party_domains(app)
    system = (PROMPTS / "plan.txt").read_text(encoding="utf-8")
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
            f"PREVIOUS GATHER FAILED: {failure_reason}. "
            "Re-plan searches/must_extract/crawl for live first-party auth and pricing docs."
        )
    if app.get("hint_type") == "docs_url" and app.get("hint_url"):
        user_parts.append(
            f"STRONG SEED docs_url — include in must_extract: {app['hint_url']}"
        )

    user_prompt = "\n".join(user_parts)
    cache_payload = {
        "prompts_version": PROMPTS_VERSION,
        "call": "plan",
        "hint_type": app.get("hint_type"),
        "hint_url": app.get("hint_url"),
        "hint_note": app.get("hint_note"),
        "seeded_domains": seeded,
        "failure_reason": failure_reason,
    }
    raw = generate_json(
        app_name=app["app_name"],
        call_name="plan",
        system_prompt=system,
        user_prompt=user_prompt,
        cache_payload=cache_payload,
    )
    gemini_calls[0] += 1
    dbg.add_gemini("plan", user_prompt, raw)
    plan = _normalize_plan(raw, seeded)
    # Prefer hint docs URL in must_extract
    if app.get("hint_type") == "docs_url" and app.get("hint_url"):
        hu = app["hint_url"]
        if hu not in plan["must_extract"]:
            plan["must_extract"].insert(0, hu)
    plan["_seeded_domains"] = seeded
    plan["app_name"] = app["app_name"]
    dbg.stage_end(
        "plan",
        business_type=plan.get("business_type"),
        searches=len(plan.get("searches") or []),
        must_extract=plan.get("must_extract"),
        crawl=plan.get("crawl"),
        gemini_calls=gemini_calls[0],
    )
    return plan


def _score_candidate(url: str, title: str = "", description: str = "") -> int:
    blob = f"{url} {title} {description}".lower()
    score = 0
    for role, hints in URL_ROLE_HINTS:
        if any(h in blob for h in hints):
            score += 3 if role in ("auth", "pricing") else 1
    if any(x in blob for x in ("docs.", "developers.", "/docs", "/api")):
        score += 1
    return score


def _extract_links_from_markdown(md: str, base_url: str) -> list[str]:
    found: list[str] = []
    for _text, href in MD_LINK_RE.findall(md or ""):
        found.append(href)
    for href in RAW_URL_RE.findall(md or ""):
        found.append(href.rstrip(".,;"))
    # relative links in markdown (](/path)
    for m in re.finditer(r"\((\s*/[^)\s]+)\)", md or ""):
        found.append(urljoin(base_url, m.group(1).strip()))
    out: list[str] = []
    seen: set[str] = set()
    for u in found:
        if not u.startswith("http"):
            u = urljoin(base_url, u)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _link_matches_hints(url: str, hints: list[str]) -> bool:
    u = url.lower()
    return any(h.lower() in u for h in hints if h)


def _clean_page_entry(url: str, markdown: str, role: str) -> Optional[dict[str, Any]]:
    cleaned, thin = clean_page(markdown or "", max_chars=CLEAN_CAP)
    if not cleaned.strip():
        return None
    return {
        "role": role,
        "url": url,
        "text": cleaned,
        "thin": thin,
        "raw_len": len(markdown or ""),
    }


def node_gather(
    app: dict,
    plan: dict[str, Any],
    tv: TavilyClient,
    dbg: DebugRecorder,
) -> dict[str, Any]:
    """Run Tavily search/extract/crawl from plan. Zero Gemini calls."""
    dbg.stage_start("gather")
    flags: list[str] = []
    seeded = plan.get("_seeded_domains") or plan.get("first_party_domains") or []
    pages: list[dict[str, Any]] = []
    sources: list[str] = []
    seen: set[str] = set()

    def _add_page(url: str, markdown: str, role: Optional[str] = None) -> bool:
        if not url or url in seen:
            return False
        if seeded and not domain_in_first_party(url, seeded):
            return False
        if not url_is_live(url):
            if "dead_url_skipped" not in flags:
                flags.append("dead_url_skipped")
            print(f"[gather] dead skip {url}")
            return False
        entry = _clean_page_entry(url, markdown, role or _guess_role(url))
        if not entry:
            return False
        seen.add(url)
        sources.append(url)
        pages.append(entry)
        dbg.add_extract(url, markdown or "", None)
        return True

    # 1) searches
    candidates: list[tuple[int, str, str, str]] = []
    for s in (plan.get("searches") or [])[:MAX_SEARCHES]:
        q = s.get("query") or ""
        if not q:
            continue
        results = tv.search(
            q,
            limit=SEARCH_RESULT_LIMIT,
            include_domains=s.get("include_domains"),
        )
        dbg.add_search(q, results)
        for r in results:
            u = r.get("url") or ""
            if not u:
                continue
            if seeded and not domain_in_first_party(u, seeded):
                continue
            sc = _score_candidate(u, r.get("title") or "", r.get("description") or "")
            candidates.append((sc, u, r.get("title") or "", r.get("description") or ""))

    candidates.sort(key=lambda x: -x[0])

    # 2) build extract list
    to_extract: list[str] = []
    for u in plan.get("must_extract") or []:
        if u and u not in to_extract:
            to_extract.append(u)
    for _sc, u, _t, _d in candidates:
        if u not in to_extract:
            to_extract.append(u)
        if len(to_extract) >= MAX_EXTRACT_URLS:
            break

    # live-filter before extract
    live_extract: list[str] = []
    for u in to_extract:
        if len(live_extract) >= MAX_EXTRACT_URLS:
            break
        if not url_is_live(u):
            if "dead_url_skipped" not in flags:
                flags.append("dead_url_skipped")
            continue
        live_extract.append(u)

    extracted = tv.extract_batch(live_extract) if live_extract else []
    for item in extracted:
        _add_page(item.get("url") or "", item.get("markdown") or "", _guess_role(item.get("url") or ""))

    # 3) selective link follow
    hints = plan.get("follow_link_hints") or list(DEFAULT_FOLLOW_HINTS)
    follow: list[str] = []
    for p in list(pages):
        for link in _extract_links_from_markdown(p.get("text") or "", p["url"]):
            if link in seen or link in follow:
                continue
            if seeded and not domain_in_first_party(link, seeded):
                continue
            if not _link_matches_hints(link, hints):
                continue
            follow.append(link)
            if len(follow) + len(seen) >= MAX_EXTRACT_URLS:
                break
        if len(follow) + len(seen) >= MAX_EXTRACT_URLS:
            break

    remain = MAX_EXTRACT_URLS - len(seen)
    if remain > 0 and follow:
        follow = [u for u in follow if url_is_live(u)][:remain]
        for item in tv.extract_batch(follow):
            _add_page(
                item.get("url") or "",
                item.get("markdown") or "",
                _guess_role(item.get("url") or ""),
            )

    # 4) optional crawl if missing auth/pricing coverage
    crawl = plan.get("crawl")
    need_crawl = crawl and (
        not _has_auth_like(sources) or not _has_pricing_like(sources)
    )
    if need_crawl and len(seen) < MAX_EXTRACT_URLS:
        cu = crawl["url"]
        if url_is_live(cu):
            crawled = tv.crawl(
                cu,
                select_paths=crawl.get("select_paths"),
                exclude_paths=crawl.get("exclude_paths"),
                limit=min(crawl.get("limit") or CRAWL_LIMIT_CAP, MAX_EXTRACT_URLS - len(seen)),
            )
            for item in crawled:
                if len(seen) >= MAX_EXTRACT_URLS:
                    break
                _add_page(
                    item.get("url") or "",
                    item.get("markdown") or "",
                    _guess_role(item.get("url") or ""),
                )
        else:
            if "dead_url_skipped" not in flags:
                flags.append("dead_url_skipped")
    elif not crawl:
        pass
    else:
        flags.append("crawl_skipped_coverage_ok")

    if not _has_auth_like(sources) and "no_auth_page_fetched" not in flags:
        flags.append("no_auth_page_fetched")
    if not _has_pricing_like(sources) and "no_pricing_page_fetched" not in flags:
        flags.append("no_pricing_page_fetched")

    # Expand first_party_domains from gathered hosts
    discovered = []
    for u in sources:
        h = host_of(u)
        if h:
            discovered.append(h)
    plan["first_party_domains"] = merge_discovered_domains(seeded, discovered)

    dbg.stage_end(
        "gather",
        sources=sources,
        page_count=len(pages),
        flags=flags,
    )
    # Also record as fetch-compatible
    dbg.stage_start("fetch")
    dbg.stage_end("fetch", sources=sources, page_count=len(pages), flags=flags)
    return {"pages": pages, "sources_fetched": sources, "flags": flags}


def node_fill(
    app: dict,
    plan: dict[str, Any],
    pages: list[dict],
    dbg: DebugRecorder,
    *,
    gemini_calls: list[int],
    repair_error: Optional[str] = None,
) -> dict[str, Any]:
    dbg.stage_start("fill" + ("_repair" if repair_error else ""))
    system = (PROMPTS / "fill.txt").read_text(encoding="utf-8")
    body = assemble_extract_input(pages, total_cap=EXTRACT_TOTAL_CAP)
    prior = plan.get("business_type", "unknown")
    user = (
        f"app_name: {app['app_name']}\n"
        f"category: {app.get('category')}\n"
        f"business_type PRIOR (do not overwrite): {prior}\n"
        f"first_party_domains: {json.dumps(plan.get('first_party_domains'))}\n"
    )
    if repair_error:
        user += f"VALIDATION ERROR from previous attempt: {repair_error}\nFix and return full JSON.\n"
    user += f"\nPAGES:\n{body}"

    cache_payload = {
        "prompts_version": PROMPTS_VERSION,
        "call": "fill",
        "hint_url": app.get("hint_url"),
        "seeded": plan.get("_seeded_domains"),
        "sources": [p["url"] for p in pages],
        "repair": repair_error,
        "body_hash": str(hash(body)),
    }
    raw = generate_json(
        app_name=app["app_name"],
        call_name="fill" + ("_repair" if repair_error else ""),
        system_prompt=system,
        user_prompt=user,
        cache_payload=cache_payload,
    )
    gemini_calls[0] += 1
    dbg.add_gemini("fill", user[:50000], raw)
    dbg.stage_end("fill", gemini_calls=gemini_calls[0])
    return raw
