"""Gemini call helpers with disk cache keyed by PROMPTS_VERSION + input hash."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from schema import PROMPTS_VERSION

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "gemini"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _input_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_key(app_name: str, call_name: str, payload: dict[str, Any]) -> Path:
    h = _input_hash(payload)
    safe = re.sub(r"[^\w\-]+", "_", app_name)[:60]
    return CACHE_DIR / f"{safe}_{call_name}_{PROMPTS_VERSION}_{h}.json"


def load_cached(path: Path) -> Optional[dict[str, Any]]:
    if path.exists():
        print(f"[gemini] cache hit {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_cached(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_gemini_client():
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing")
    return genai.Client(api_key=api_key)


# Logic freeze: Flash-Lite for all three calls. Stable GA id.
MODEL_ID = "gemini-3.5-flash-lite"


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or ("rate" in msg and "quota" in msg)


def generate_content_retry(
    client: Any, *, model: str, contents: Any, config: Any, retries: int = 6
):
    """Call Gemini with backoff on free-tier 429s."""
    delay = 25.0
    last: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:
            last = e
            if not _is_rate_limit_error(e) or attempt >= retries - 1:
                raise
            wait = delay
            m = re.search(r"retry in ([0-9.]+)s", str(e), re.I)
            if m:
                wait = max(delay, float(m.group(1)) + 2.0)
            print(
                f"[gemini] 429 rate limit — sleeping {wait:.0f}s "
                f"(attempt {attempt + 1}/{retries})"
            )
            time.sleep(wait)
            delay = min(delay * 1.5, 90.0)
    assert last is not None
    raise last


def generate_json(
    *,
    app_name: str,
    call_name: str,
    system_prompt: str,
    user_prompt: str,
    cache_payload: dict[str, Any],
    temperature: float = 0.0,
) -> dict[str, Any]:
    """
    Cached Gemini JSON generation (no tools).
    cache_payload must include hint fields, seeded domains, retry reason when present.
    """
    path = cache_key(app_name, call_name, cache_payload)
    hit = load_cached(path)
    if hit is not None:
        return hit

    client = get_gemini_client()
    full = f"{system_prompt}\n\n---\n\n{user_prompt}"
    resp = generate_content_retry(
        client,
        model=MODEL_ID,
        contents=full,
        config={
            "temperature": temperature,
            "response_mime_type": "application/json",
        },
    )
    text = resp.text or "{}"
    data = parse_json_loose(text)
    save_cached(path, data)
    return data


def is_deep_site_query(query: str) -> bool:
    """True for site:domain/path inventions — ban these."""
    q = (query or "").strip()
    # site:host/something  (path after domain)
    return bool(re.search(r"(?i)\bsite:[^\s/]+/.+", q))


def classify_search_target(query: str) -> Optional[str]:
    """Rough target class for hard zero-result retries: auth | pricing | other."""
    q = (query or "").lower()
    if any(
        k in q
        for k in (
            "pric",
            "plan",
            "billing",
            "subscription",
            "access tier",
            "access_tier",
        )
    ):
        return "pricing"
    if any(
        k in q
        for k in (
            "auth",
            "oauth",
            "api key",
            "apikey",
            "token",
            "credential",
            "login",
            "permission",
        )
    ):
        return "auth"
    return None


def urls_from_partial_json(text: str) -> dict[str, Optional[str]]:
    """Best-effort extract auth_url / pricing_url from model text."""
    out: dict[str, Optional[str]] = {"auth_url": None, "pricing_url": None}
    try:
        data = parse_json_loose(text)
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for k in ("auth_url", "pricing_url"):
        v = data.get(k)
        if isinstance(v, str) and v.strip().startswith("http"):
            out[k] = v.strip()
        elif v in (None, "", "null"):
            out[k] = None
    return out


def discover_with_search_agent(
    *,
    app_name: str,
    system_prompt: str,
    user_prompt: str,
    cache_payload: dict[str, Any],
    search_fn: Callable[[str, int], list[dict[str, Any]]],
    max_tool_calls: int = 6,
    on_search: Optional[Callable[[str, list[dict[str, Any]]], None]] = None,
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    """
    Call 1 agent: Gemini with Tavily search bound. Max `max_tool_calls` searches.
    Fail-closed on auth+pricing before MCP; ban deep site: paths; hard zero-result retries.
    """
    from google.genai import types

    path = cache_key(app_name, "discover_agent", cache_payload)
    hit = load_cached(path)
    if hit is not None and isinstance(hit, dict) and "result" in hit:
        return hit["result"], int(hit.get("tool_calls", 0)), list(hit.get("trace", []))

    client = get_gemini_client()

    search_decl = types.FunctionDeclaration(
        name="tavily_search",
        description=(
            "Search the live web via Tavily for vendor documentation, authentication, "
            "pricing/API access, app review, partner programmes, OpenAPI, webhooks, or MCP. "
            "Fill auth and pricing FIRST. Prefer site:{domain} + keywords only — never "
            "site:{domain}/invented/path. Do not invent URLs — only return what search finds."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="Search query. Be specific; vary queries across calls.",
                ),
                "max_results": types.Schema(
                    type=types.Type.INTEGER,
                    description="Number of results (1-8). Default 5.",
                ),
            },
            required=["query"],
        ),
    )
    tool = types.Tool(function_declarations=[search_decl])

    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_prompt)],
        )
    ]

    tool_calls = 0
    trace: list[dict[str, Any]] = []
    final_text = ""
    scored_nudge_sent = False
    secondary_nudge_sent = False
    forced_retries: set[str] = set()  # auth | pricing already hard-retried
    known_urls: dict[str, Optional[str]] = {"auth_url": None, "pricing_url": None}
    coverage_hits: dict[str, bool] = {"auth": False, "pricing": False}

    for _round in range(max_tool_calls + 6):
        use_tools = tool_calls < max_tool_calls
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": 0.2,
        }
        if use_tools:
            config_kwargs["tools"] = [tool]
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                disable=True
            )
        else:
            config_kwargs["response_mime_type"] = "application/json"
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "Tool budget exhausted. Return ONLY the final JSON object now "
                                "(business_type, URLs, first_party_domains, backup_links). "
                                "No markdown fences."
                            )
                        )
                    ],
                )
            )

        resp = generate_content_retry(
            client,
            model=MODEL_ID,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        fn_calls = []
        text_bits = []
        candidate = (resp.candidates or [None])[0]
        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                fc = getattr(part, "function_call", None)
                if fc:
                    fn_calls.append(fc)
                elif getattr(part, "text", None):
                    text_bits.append(part.text)

        if text_bits:
            partial = urls_from_partial_json("\n".join(text_bits))
            for k, v in partial.items():
                if v:
                    known_urls[k] = v

        if fn_calls and use_tools:
            contents.append(candidate.content)
            response_parts = []
            hard_retry_needed: Optional[str] = None
            for fc in fn_calls:
                if tool_calls >= max_tool_calls:
                    break
                args = dict(fc.args or {})
                query = str(args.get("query") or "")
                max_results = int(args.get("max_results") or 5)
                max_results = max(1, min(8, max_results))
                print(f"[agent] tavily_search #{tool_calls+1}: {query!r}")
                tool_calls += 1

                if is_deep_site_query(query):
                    print(f"[agent] REJECT deep site: path query {query!r}")
                    trace.append(
                        {
                            "query": query,
                            "max_results": max_results,
                            "results": [],
                            "zero_results": True,
                            "invalid_site_query": True,
                        }
                    )
                    response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name or "tavily_search",
                            response={
                                "results": [],
                                "result_json": "[]",
                                "zero_results": True,
                                "invalid_site_query": True,
                                "instruction": (
                                    "INVALID QUERY. Do not invent site:domain/path URLs. "
                                    "Retry as site:{domain} plus keywords only "
                                    "(e.g. 'site:shopify.dev authentication' or "
                                    "'site:shopify.dev pricing API')."
                                ),
                            },
                        )
                    )
                    continue

                results = search_fn(query, max_results)
                if on_search:
                    on_search(query, results)
                zero = not results
                target = classify_search_target(query)
                if not zero and target in ("auth", "pricing"):
                    coverage_hits[target] = True
                    # Seed known URL from first http result when still empty
                    key = "auth_url" if target == "auth" else "pricing_url"
                    if not known_urls.get(key):
                        for r in results:
                            u = (r.get("url") or "").strip()
                            if u.startswith("http"):
                                known_urls[key] = u
                                break
                if zero:
                    print(
                        f"[agent] ZERO RESULTS for {query!r} "
                        f"(target={target or 'other'})"
                    )
                    if (
                        target in ("auth", "pricing")
                        and target not in forced_retries
                        and tool_calls < max_tool_calls
                    ):
                        hard_retry_needed = target
                trace.append(
                    {
                        "query": query,
                        "max_results": max_results,
                        "results": results,
                        "zero_results": zero,
                        "target": target,
                    }
                )
                fn_response: dict[str, Any] = {
                    "results": results,
                    "result_json": json.dumps(results)[:5000],
                    "zero_results": zero,
                }
                if zero and target in ("auth", "pricing"):
                    fn_response["instruction"] = (
                        f"ZERO RESULTS for {target}. Rephrase with different wording NOW "
                        f"before leaving {target}_url null. Do not search MCP yet."
                    )
                response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name or "tavily_search",
                        response=fn_response,
                    )
                )

            contents.append(types.Content(role="user", parts=response_parts))
            if hard_retry_needed and hard_retry_needed not in forced_retries:
                forced_retries.add(hard_retry_needed)
                print(f"[agent] HARD RETRY nudge for {hard_retry_needed}")
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    f"HARD REQUIREMENT: your last {hard_retry_needed} search "
                                    f"returned zero results. Immediately call tavily_search "
                                    f"again with a REPHRASED {hard_retry_needed} query "
                                    f"(site:domain + keywords only). Do NOT search MCP, "
                                    f"OpenAPI, or webhooks until auth_url and pricing_url "
                                    f"are both found."
                                )
                            )
                        ],
                    )
                )
            continue

        # Early finalize without tools — gate on auth+pricing first
        if use_tools and tool_calls < max_tool_calls and tool_calls > 0:
            remaining = max_tool_calls - tool_calls
            auth_ok = bool(known_urls.get("auth_url")) or coverage_hits["auth"]
            price_ok = bool(known_urls.get("pricing_url")) or coverage_hits["pricing"]
            if not auth_ok or not price_ok:
                missing = []
                if not auth_ok:
                    missing.append("auth_url")
                if not price_ok:
                    missing.append("pricing_url")
                print(
                    f"[agent] early finalize blocked — need {missing} "
                    f"({remaining} calls left)"
                )
                scored_nudge_sent = True
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    f"You still have {remaining} search call(s). Do NOT finalize. "
                                    f"Search ONLY for missing scored coverage: {', '.join(missing)}. "
                                    "Use site:{domain} + keywords (no invented paths). "
                                    "Do not search MCP/OpenAPI/webhooks until both auth_url "
                                    "and pricing_url are non-null."
                                )
                            )
                        ],
                    )
                )
                continue
            if not secondary_nudge_sent:
                secondary_nudge_sent = True
                print(
                    f"[agent] scored coverage filled — nudging MCP/secondary "
                    f"({remaining} calls left)"
                )
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    f"auth_url and pricing_url coverage looks filled. You still have "
                                    f"{remaining} search call(s). Do NOT finalize yet if "
                                    "mcp_url / openapi_url / webhooks_url are null — search "
                                    "for MCP first, then OpenAPI or webhooks."
                                )
                            )
                        ],
                    )
                )
                continue

        final_text = "\n".join(text_bits) or (resp.text or "")
        break
    else:
        final_text = resp.text or "{}"

    try:
        data = parse_json_loose(final_text)
    except Exception:
        fmt = generate_content_retry(
            client,
            model=MODEL_ID,
            contents=(
                f"{system_prompt}\n\nConvert the following discovery notes into the required "
                f"JSON object only.\n\nNOTES:\n{final_text}"
            ),
            config={
                "temperature": 0.0,
                "response_mime_type": "application/json",
            },
        )
        data = parse_json_loose(fmt.text or "{}")

    save_cached(
        path,
        {"result": data, "tool_calls": tool_calls, "trace": trace},
    )
    return data, tool_calls, trace


def parse_json_loose(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def chunk_filter_call(chunk: str, app_name: str, chunk_idx: int) -> str:
    """Return relevant sentences or NONE. Uses Flash-Lite."""
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "chunk_filter.txt"
    system = prompt_path.read_text(encoding="utf-8")
    payload = {
        "prompts_version": PROMPTS_VERSION,
        "chunk_idx": chunk_idx,
        "chunk_hash": hashlib.sha256(chunk.encode()).hexdigest(),
    }
    path = cache_key(app_name, f"chunk_{chunk_idx}", payload)
    hit = load_cached(path)
    if hit is not None:
        return hit.get("text", "NONE")

    client = get_gemini_client()
    resp = generate_content_retry(
        client,
        model=MODEL_ID,
        contents=f"{system}\n\n---\n\nCHUNK:\n{chunk}",
        config={"temperature": 0.0},
    )
    text = (resp.text or "NONE").strip()
    save_cached(path, {"text": text})
    return text
