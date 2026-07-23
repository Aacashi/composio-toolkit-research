"""Per-app debug writer — AMENDMENT_3 §9."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"
DEBUG_DIR.mkdir(exist_ok=True)


def safe_name(app_name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", app_name)[:80]


class DebugRecorder:
    def __init__(self, app_name: str) -> None:
        self.app_name = app_name
        self.started = time.time()
        self.data: dict[str, Any] = {
            "app_name": app_name,
            "stages": {},
            "fetches": [],
            "fetch_all_sources": [],
            "searches": [],
            "extracts": [],
            "gemini": [],
            "guard_changes": [],
            "credits": 0,
            "errors": [],
        }
        self._stage_t0: dict[str, float] = {}
        self._fetch_all_sources: list[str] = []

    def stage_start(self, name: str) -> None:
        self._stage_t0[name] = time.time()
        print(f"[stage] {self.app_name} -> {name}")

    def stage_end(self, name: str, **extra: Any) -> None:
        t0 = self._stage_t0.get(name, time.time())
        entry = {
            "duration_s": round(time.time() - t0, 3),
            **extra,
        }
        if name == "fetch":
            # Accumulate; do not overwrite first-round with second-round.
            self.data.setdefault("fetches", []).append(entry)
            for u in extra.get("sources") or []:
                if u and u not in self._fetch_all_sources:
                    self._fetch_all_sources.append(u)
            self.data["fetch_all_sources"] = list(self._fetch_all_sources)
            # Keep a summary view of the latest fetch for backwards compatibility,
            # but also expose the union.
            self.data["stages"]["fetch"] = {
                **entry,
                "note": "latest fetch only; see fetches[] and fetch_all_sources",
                "fetch_all_sources": list(self._fetch_all_sources),
                "fetch_rounds": len(self.data["fetches"]),
            }
        else:
            self.data["stages"][name] = entry

    def add_search(self, query: str, results: list[dict]) -> None:
        self.data["searches"].append(
            {
                "query": query,
                "urls": [r.get("url") for r in results],
                "results": results,
            }
        )

    def add_extract(
        self,
        url: str,
        markdown: str,
        error: str | None,
        *,
        kept: bool | None = None,
    ) -> None:
        md = markdown or ""
        auto_kept = bool(md) and not error
        self.data["extracts"].append(
            {
                "url": url,
                "error": error,
                "markdown_chars": len(md),
                "kept": auto_kept if kept is None else kept,
                "markdown_preview": md[:2000],
                "raw_markdown": md,
            }
        )

    def add_gemini(
        self,
        call_name: str,
        prompt: str,
        raw_response: Any,
    ) -> None:
        self.data["gemini"].append(
            {
                "call": call_name,
                "prompt": prompt,
                "raw_response": raw_response,
            }
        )

    def add_guard_change(self, field: str, before: Any, after: Any, reason: str) -> None:
        self.data["guard_changes"].append(
            {"field": field, "before": before, "after": after, "reason": reason}
        )

    def set_credits(self, n: int) -> None:
        self.data["credits"] = n

    def set_tavily_provider(self, info: dict[str, Any]) -> None:
        self.data.update(info)

    def add_error(self, msg: str) -> None:
        self.data["errors"].append(msg)

    def write(self) -> Path:
        self.data["wall_clock_s"] = round(time.time() - self.started, 3)
        path = DEBUG_DIR / f"{safe_name(self.app_name)}.json"
        # Truncate huge raw markdown in stored file for readability but keep preview
        payload = json.loads(json.dumps(self.data, default=str))
        for ex in payload.get("extracts", []):
            # keep raw_markdown — amendment requires it; cap at 100k per URL
            raw = ex.get("raw_markdown") or ""
            if len(raw) > 100_000:
                ex["raw_markdown"] = raw[:100_000] + "\n...[truncated]"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[debug] wrote {path}")
        return path
