"""Gemini call helpers with disk cache keyed by PROMPTS_VERSION + input hash."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


MODEL_ID = "gemini-2.0-flash-lite"


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
    resp = client.models.generate_content(
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
    resp = client.models.generate_content(
        model=MODEL_ID,
        contents=f"{system}\n\n---\n\nCHUNK:\n{chunk}",
        config={"temperature": 0.0},
    )
    text = (resp.text or "NONE").strip()
    save_cached(path, {"text": text})
    return text
