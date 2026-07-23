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
            "searches": [],
            "extracts": [],
            "gemini": [],
            "guard_changes": [],
            "credits": 0,
            "errors": [],
        }
        self._stage_t0: dict[str, float] = {}

    def stage_start(self, name: str) -> None:
        self._stage_t0[name] = time.time()
        print(f"[stage] {self.app_name} -> {name}")

    def stage_end(self, name: str, **extra: Any) -> None:
        t0 = self._stage_t0.get(name, time.time())
        self.data["stages"][name] = {
            "duration_s": round(time.time() - t0, 3),
            **extra,
        }

    def add_search(self, query: str, results: list[dict]) -> None:
        self.data["searches"].append(
            {
                "query": query,
                "urls": [r.get("url") for r in results],
                "results": results,
            }
        )

    def add_extract(self, url: str, markdown: str, error: str | None) -> None:
        self.data["extracts"].append(
            {
                "url": url,
                "error": error,
                "markdown_chars": len(markdown or ""),
                "markdown_preview": (markdown or "")[:2000],
                "raw_markdown": markdown or "",
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
