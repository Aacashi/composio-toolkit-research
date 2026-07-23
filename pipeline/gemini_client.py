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


class RateLimitExhausted(RuntimeError):
    """Raised when Gemini 429/quota persists after all retries."""


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "resource_exhausted" in msg
        or "quota" in msg
        or ("rate" in msg and "limit" in msg)
    )


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
            if not _is_rate_limit_error(e):
                raise
            if attempt >= retries - 1:
                raise RateLimitExhausted(
                    f"Gemini rate limit/quota exhausted after {retries} retries: {e}"
                ) from e
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
    raise RateLimitExhausted(f"Gemini rate limit exhausted: {last}") from last


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
    Gemini decides every query. Returns (final_json, tool_call_count, tool_trace).

    Caches only the final JSON (not mid-tool state), keyed by input hints —
    not by search results (those are non-deterministic across days).
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
            "Choose queries using the business-type prior: e.g. enterprise_sales → contact sales / "
            "partner docs; ad_platform → developer app review; data_vendor → API pricing tiers; "
            "commerce_platform → merchant API / shop credentials. Prefer site: filters on known "
            "vendor domains. Do not invent URLs — only return what search finds."
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
    secondary_nudge_sent = False

    # Iterative tool loop. Cap at max_tool_calls searches.
    for _round in range(max_tool_calls + 4):
        # After tool budget exhausted, force a plain JSON answer (no tools).
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
            # Nudge finalization
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

        # Collect function calls from response
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

        if fn_calls and use_tools:
            # Append model turn
            contents.append(candidate.content)
            response_parts = []
            for fc in fn_calls:
                if tool_calls >= max_tool_calls:
                    break
                name = fc.name or ""
                args = dict(fc.args or {})
                query = str(args.get("query") or "")
                max_results = int(args.get("max_results") or 5)
                max_results = max(1, min(8, max_results))
                print(f"[agent] tavily_search #{tool_calls+1}: {query!r}")
                results = search_fn(query, max_results)
                tool_calls += 1
                if on_search:
                    on_search(query, results)
                zero = not results
                if zero:
                    print(
                        f"[agent] ZERO RESULTS for {query!r} — "
                        "rephrase if scored target and budget remains"
                    )
                trace.append(
                    {
                        "query": query,
                        "max_results": max_results,
                        "results": results,
                        "zero_results": zero,
                    }
                )
                payload = json.dumps(results)[:5000]
                fn_response: dict[str, Any] = {
                    "results": results,
                    "result_json": payload,
                    "zero_results": zero,
                }
                if zero:
                    fn_response["instruction"] = (
                        "ZERO RESULTS. If this was for a scored target (auth or "
                        "pricing/access_tier), retry once with different wording before "
                        "leaving that URL null. Secondary targets (MCP, OpenAPI, webhooks) "
                        "retry only if budget remains after scored coverage. MCP is "
                        "deprioritised under budget pressure only."
                    )
                response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response=fn_response,
                    )
                )
            contents.append(types.Content(role="user", parts=response_parts))
            continue

        # No tool call — if budget remains and we have not nudged for secondary
        # coverage yet, push one more search round (MCP / OpenAPI / webhooks).
        if (
            use_tools
            and tool_calls < max_tool_calls
            and tool_calls > 0
            and not secondary_nudge_sent
        ):
            secondary_nudge_sent = True
            remaining = max_tool_calls - tool_calls
            print(
                f"[agent] early finalize with {remaining} calls left — "
                "nudging MCP-first secondary search"
            )
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=(
                                f"You still have {remaining} search call(s). Do NOT finalize. "
                                "First remaining call MUST search for the vendor MCP server "
                                "(Model Context Protocol), e.g. "
                                "'site:{vendor} MCP Model Context Protocol' or "
                                "'{name} MCP server docs'. Then use any leftover calls for "
                                "OpenAPI/Swagger or webhooks if those URLs are still null."
                            )
                        )
                    ],
                )
            )
            continue

        # No tool call — treat as final answer
        final_text = "\n".join(text_bits) or (resp.text or "")
        break
    else:
        final_text = resp.text or "{}"

    # If still not JSON, one formatting pass
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
