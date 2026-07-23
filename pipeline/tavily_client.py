"""Tavily search + crawl + batched extract via Composio SDK, with direct API fallback.

Primary: composio.tools.execute(TAVILY_SEARCH / TAVILY_CRAWL / TAVILY_EXTRACT, version=...)
Fallback: https://api.tavily.com  (same interface; documented in README)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

TAVILY_API = "https://api.tavily.com"
WARN_CREDITS = 700
ABORT_CREDITS = 850
EXTRACT_BATCH_SIZE = 5
CRAWL_MAX_DEPTH = 1
CRAWL_MAX_BREADTH = 10
CRAWL_LIMIT_CAP = 6
DEFAULT_CRAWL_EXCLUDE = [
    "/blog/.*",
    "/changelog/.*",
    "/careers/.*",
    "/legal/.*",
    "/privacy.*",
    "/terms.*",
    "/about.*",
]
DEFAULT_CRAWL_SELECT = [
    "/docs/.*",
    "/api/.*",
    "/developers/.*",
    "/authentication.*",
    "/oauth.*",
    "/pricing.*",
    "/plans.*",
]


class CreditTracker:
    """Tavily credit budget: warn at 700, abort projection at 850."""

    def __init__(self, warn_at: int = WARN_CREDITS, abort_at: int = ABORT_CREDITS) -> None:
        self.warn_at = warn_at
        self.abort_at = abort_at
        self.total = 0
        self.per_app: dict[str, int] = {}
        self._current_app = ""
        self._warned = False

    def set_app(self, app_name: str) -> None:
        self._current_app = app_name
        self.per_app.setdefault(app_name, 0)

    def add(self, credits: int, reason: str = "") -> None:
        self.total += credits
        if self._current_app:
            self.per_app[self._current_app] = self.per_app.get(self._current_app, 0) + credits
        print(
            f"[tavily] +{credits} credits ({reason}) "
            f"app={self.per_app.get(self._current_app, 0)} total={self.total}/{self.abort_at}"
        )
        if not self._warned and self.total >= self.warn_at:
            self._warned = True
            print(f"[tavily] WARN credits {self.total} >= {self.warn_at}")

    def projected_ok(self, apps_done: int, apps_total: int, remaining: int) -> bool:
        if apps_done == 0:
            return self.total < self.abort_at
        avg = self.total / apps_done
        projected = self.total + avg * remaining
        if projected > self.abort_at:
            print(
                f"[tavily] ABORT projected {projected:.0f} > {self.abort_at} "
                f"(done={apps_done}/{apps_total}, avg={avg:.1f})"
            )
            return False
        return True


class TavilyClient:
    """
    search() and extract_batch() with disk cache.
    Prefer Composio toolkit; fall back to direct Tavily HTTP.
    """

    def __init__(
        self,
        tracker: Optional[CreditTracker] = None,
        *,
        verbose: bool = False,
    ) -> None:
        self.tracker = tracker or CreditTracker()
        self.verbose = verbose
        self.composio_api_key = os.getenv("COMPOSIO_API_KEY", "")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        self.user_id = os.getenv("COMPOSIO_USER_ID", "default")
        self.auth_config_id = os.getenv("COMPOSIO_AUTH_CONFIG_ID", "")
        self.connected_account_id = os.getenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "") or None
        self.toolkit_version = (os.getenv("COMPOSIO_TAVILY_VERSION") or "").strip()
        # mode = what actually executed successfully last; never stay "composio" after fallback
        self.mode = "direct"
        self.fallback_used = False
        self.composio_error: Optional[str] = None
        self.composio_executes = 0
        self.version_used: Optional[str] = None
        self._composio = None
        self._http = httpx.Client(timeout=90.0)
        self._init_provider()

    def provider_debug(self) -> dict[str, Any]:
        return {
            "tavily_provider": self.mode,
            "composio_error": self.composio_error,
            "fallback_used": self.fallback_used,
            "composio_executes": self.composio_executes,
            "toolkit_version_env": self.toolkit_version or None,
            "version_used": self.version_used,
        }

    def _log(self, msg: str) -> None:
        print(msg)

    def _init_provider(self) -> None:
        if self.composio_api_key:
            try:
                from composio import Composio

                self._composio = Composio(api_key=self.composio_api_key)
                self.mode = "composio"
                self._log(
                    f"[tavily] provider=composio user_id={self.user_id} "
                    f"auth_config={self.auth_config_id or 'n/a'} "
                    f"connected_account={self.connected_account_id or 'auto'} "
                    f"toolkit_version={self.toolkit_version or 'UNSET'}"
                )
                return
            except Exception as e:
                self.composio_error = str(e)
                self._log(
                    f"[tavily] WARN composio init failed: {e}; falling back to direct"
                )
                self.fallback_used = True
        if not self.tavily_api_key:
            self._log("[tavily] WARN: no COMPOSIO_API_KEY path and no TAVILY_API_KEY")
        self.mode = "direct"
        self._log("[tavily] provider=direct")

    def _version_candidates(self) -> list[Optional[str]]:
        v = self.toolkit_version
        if not v:
            return [None]
        cands: list[Optional[str]] = [v]
        if v.startswith("v") and v[1:] not in cands:
            cands.append(v[1:])
        elif not v.startswith("v"):
            alt = f"v{v}"
            if alt not in cands:
                cands.append(alt)
        return cands

    def _mark_composio_fallback(self, err: Exception) -> None:
        self.composio_error = str(err)
        self.fallback_used = True
        self.mode = "direct"
        self._log(
            f"[tavily] WARN composio execute failed: {err}; falling back to direct"
        )

    def _composio_execute(self, slug: str, arguments: dict[str, Any]) -> Any:
        assert self._composio is not None
        base_kwargs: dict[str, Any] = {"user_id": self.user_id}
        if self.connected_account_id:
            base_kwargs["connected_account_id"] = self.connected_account_id

        last_err: Optional[Exception] = None
        for ver in self._version_candidates():
            kwargs = dict(base_kwargs)
            if ver is not None:
                kwargs["version"] = ver
            try:
                raw = self._composio.tools.execute(slug, arguments, **kwargs)
                self.composio_executes += 1
                self.version_used = ver
                self.mode = "composio"
                return raw
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                # Retry alternate version form for version-shaped failures OR
                # "tool not found" (Composio returns 404 Tool_ToolNotFound for bad version tags).
                if ver is not None and (
                    "version" in msg
                    or "toolkit" in msg
                    or "not specified" in msg
                    or "not found" in msg
                    or "tool_toolnotfound" in msg
                ):
                    self._log(
                        f"[tavily] composio version={ver!r} rejected for {slug}; trying next"
                    )
                    continue
                raise
        assert last_err is not None
        raise last_err

    # ---- cache helpers ----

    def _search_cache_path(
        self, query: str, limit: int, include_domains: Optional[list[str]] = None
    ) -> Path:
        dom = ",".join(include_domains or [])
        digest = hashlib.sha256(
            f"search:{query}:{limit}:basic:{dom}".encode()
        ).hexdigest()
        return CACHE_DIR / f"search_{digest}.json"

    def _extract_cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.md"

    def _crawl_cache_path(self, params: dict[str, Any]) -> Path:
        blob = json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(f"crawl:{blob}".encode()).hexdigest()
        return CACHE_DIR / f"crawl_{digest}.json"

    # ---- search ----

    def search(
        self,
        query: str,
        limit: int = 5,
        include_domains: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        domains = [d for d in (include_domains or []) if d]
        path = self._search_cache_path(query, limit, domains)
        if path.exists():
            self._log(f"[tavily] search cache hit q={query!r}")
            return json.loads(path.read_text(encoding="utf-8"))

        self._log(f"[tavily] search q={query!r} domains={domains or 'any'}")
        results: list[dict[str, Any]] = []
        charged = False
        if self._composio is not None and not self.fallback_used:
            try:
                results = self._composio_search(query, limit, domains)
                charged = True
            except Exception as e:
                self._mark_composio_fallback(e)
                if self.tavily_api_key:
                    results = self._direct_search(query, limit, domains)
                    charged = True
        elif self.tavily_api_key:
            results = self._direct_search(query, limit, domains)
            charged = True
        else:
            self._log("[tavily] search skipped — no credentials")

        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        if charged:
            self.tracker.add(1, f"search {query!r}")
        return results

    def _composio_search(
        self, query: str, limit: int, include_domains: list[str]
    ) -> list[dict[str, Any]]:
        args: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
        }
        if include_domains:
            args["include_domains"] = include_domains
        raw = self._composio_execute("TAVILY_SEARCH", args)
        return _normalize_search_results(raw)

    def _composio_extract(self, urls: list[str]) -> list[dict[str, Any]]:
        raw = self._composio_execute("TAVILY_EXTRACT", {"urls": urls})
        return _normalize_extract_results(raw, urls)

    def _direct_search(
        self, query: str, limit: int, include_domains: list[str]
    ) -> list[dict[str, Any]]:
        if not self.tavily_api_key:
            return []
        body: dict[str, Any] = {
            "api_key": self.tavily_api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
        }
        if include_domains:
            body["include_domains"] = include_domains
        resp = self._http.post(f"{TAVILY_API}/search", json=body)
        if resp.status_code != 200:
            self._log(f"[tavily] direct search http {resp.status_code}")
            return []
        return _normalize_search_results(resp.json())

    # ---- crawl ----

    def crawl(
        self,
        url: str,
        *,
        select_paths: Optional[list[str]] = None,
        exclude_paths: Optional[list[str]] = None,
        limit: int = CRAWL_LIMIT_CAP,
    ) -> list[dict[str, Any]]:
        """
        Clamped crawl. Returns list of {url, markdown, error}.
        Hard caps: depth=1, breadth<=10, limit<=6, allow_external=false, basic extract.
        """
        if not url:
            return []
        lim = max(1, min(int(limit or CRAWL_LIMIT_CAP), CRAWL_LIMIT_CAP))
        select = list(select_paths or DEFAULT_CRAWL_SELECT)
        exclude = list(exclude_paths or DEFAULT_CRAWL_EXCLUDE)
        params = {
            "url": url,
            "max_depth": CRAWL_MAX_DEPTH,
            "max_breadth": CRAWL_MAX_BREADTH,
            "limit": lim,
            "allow_external": False,
            "extract_depth": "basic",
            "format": "markdown",
            "select_paths": select,
            "exclude_paths": exclude,
        }
        path = self._crawl_cache_path(params)
        if path.exists():
            self._log(f"[tavily] crawl cache hit {url}")
            return json.loads(path.read_text(encoding="utf-8"))

        self._log(f"[tavily] crawl {url} limit={lim}")
        results: list[dict[str, Any]] = []
        charged = False
        if self._composio is not None and not self.fallback_used:
            try:
                results = self._composio_crawl(params)
                charged = True
            except Exception as e:
                self._mark_composio_fallback(e)
                if self.tavily_api_key:
                    results = self._direct_crawl(params)
                    charged = True
        elif self.tavily_api_key:
            results = self._direct_crawl(params)
            charged = True
        else:
            self._log("[tavily] crawl skipped — no credentials")

        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        # Cache successful page bodies as extract cache too
        for item in results:
            md = item.get("markdown") or ""
            u = item.get("url") or ""
            if u and md and not item.get("error"):
                self._extract_cache_path(u).write_text(md, encoding="utf-8")
        if charged:
            n = max(1, len([r for r in results if r.get("markdown")]))
            # map ~1/10 pages + extract ~1/5 pages (basic); rough floor
            credits = max(1, (n + 9) // 10 + (n + 4) // 5)
            self.tracker.add(credits, f"crawl {url} x{n}")
        return results

    def _composio_crawl(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        raw = self._composio_execute("TAVILY_CRAWL", dict(params))
        return _normalize_crawl_results(raw)

    def _direct_crawl(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.tavily_api_key:
            return []
        body = {"api_key": self.tavily_api_key, **params}
        resp = self._http.post(f"{TAVILY_API}/crawl", json=body)
        if resp.status_code != 200:
            self._log(f"[tavily] direct crawl http {resp.status_code}")
            return []
        return _normalize_crawl_results(resp.json())

    # ---- extract (batched) ----

    def extract_batch(self, urls: list[str]) -> list[dict[str, Any]]:
        """
        Extract markdown for URLs in batches of 5.
        Returns list of {url, markdown, error}.
        Cache hits cost zero credits and are skipped from the API batch.
        """
        out: list[dict[str, Any]] = []
        pending: list[str] = []

        for url in urls:
            if not url:
                continue
            path = self._extract_cache_path(url)
            if path.exists():
                self._log(f"[tavily] extract cache hit {url}")
                out.append({"url": url, "markdown": path.read_text(encoding="utf-8"), "error": None})
            else:
                pending.append(url)

        for i in range(0, len(pending), EXTRACT_BATCH_SIZE):
            chunk = pending[i : i + EXTRACT_BATCH_SIZE]
            self._log(f"[tavily] extract batch n={len(chunk)} urls={chunk}")
            if self._composio is not None and not self.fallback_used:
                try:
                    batch_results = self._composio_extract(chunk)
                    charged = True
                except Exception as e:
                    self._mark_composio_fallback(e)
                    if not self.tavily_api_key:
                        batch_results = [
                            {"url": u, "markdown": "", "error": "no credentials"}
                            for u in chunk
                        ]
                        charged = False
                    else:
                        batch_results = self._direct_extract(chunk)
                        charged = True
            elif self.tavily_api_key:
                batch_results = self._direct_extract(chunk)
                charged = True
            else:
                batch_results = [
                    {"url": u, "markdown": "", "error": "no credentials"} for u in chunk
                ]
                charged = False
            if charged:
                credits = 1 if len(chunk) <= 2 else 2
                self.tracker.add(credits, f"extract x{len(chunk)}")
            for item in batch_results:
                url = item["url"]
                md = item.get("markdown") or ""
                err = item.get("error")
                if md and not err:
                    self._extract_cache_path(url).write_text(md, encoding="utf-8")
                out.append(item)

        by_url = {r["url"]: r for r in out}
        ordered = []
        for u in urls:
            if u in by_url:
                ordered.append(by_url[u])
        return ordered

    def _direct_extract(self, urls: list[str]) -> list[dict[str, Any]]:
        if not self.tavily_api_key:
            return [{"url": u, "markdown": "", "error": "TAVILY_API_KEY missing"} for u in urls]
        resp = self._http.post(
            f"{TAVILY_API}/extract",
            json={"api_key": self.tavily_api_key, "urls": urls},
        )
        if resp.status_code != 200:
            return [
                {"url": u, "markdown": "", "error": f"http {resp.status_code}"}
                for u in urls
            ]
        return _normalize_extract_results(resp.json(), urls)


def _normalize_search_results(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    data = raw
    if isinstance(raw, dict):
        data = (
            raw.get("results")
            or raw.get("data")
            or raw.get("response_data", {}).get("results")
            or (raw.get("data", {}).get("results") if isinstance(raw.get("data"), dict) else None)
            or raw
        )
        if isinstance(data, dict):
            data = data.get("results") or data.get("data") or []
    if not isinstance(data, list):
        return []
    out = []
    for r in data:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "url": r.get("url") or r.get("link") or "",
                "title": r.get("title") or "",
                "description": r.get("content") or r.get("description") or r.get("snippet") or "",
            }
        )
    return out


def _normalize_extract_results(raw: Any, urls: list[str]) -> list[dict[str, Any]]:
    """Map Tavily/Composio extract payload to {url, markdown, error}."""
    results_list: list = []
    if isinstance(raw, dict):
        if isinstance(raw.get("results"), list):
            results_list = raw["results"]
        elif isinstance(raw.get("data"), dict) and isinstance(raw["data"].get("results"), list):
            results_list = raw["data"]["results"]
        elif isinstance(raw.get("response_data"), dict) and isinstance(
            raw["response_data"].get("results"), list
        ):
            results_list = raw["response_data"]["results"]
        elif isinstance(raw.get("data"), list):
            results_list = raw["data"]
    elif isinstance(raw, list):
        results_list = raw

    by_url: dict[str, dict] = {}
    for r in results_list or []:
        if not isinstance(r, dict):
            continue
        url = r.get("url") or ""
        md = (
            r.get("raw_content")
            or r.get("markdown")
            or r.get("content")
            or r.get("text")
            or ""
        )
        if url:
            by_url[url] = {
                "url": url,
                "markdown": md,
                "error": None if str(md).strip() else "empty",
            }

    out = []
    for u in urls:
        if u in by_url:
            out.append(by_url[u])
        else:
            out.append({"url": u, "markdown": "", "error": "not in extract response"})

    if all(x.get("error") for x in out) and results_list and len(results_list) == len(urls):
        out = []
        for u, r in zip(urls, results_list):
            if not isinstance(r, dict):
                out.append({"url": u, "markdown": "", "error": "bad result"})
                continue
            md = r.get("raw_content") or r.get("markdown") or r.get("content") or ""
            out.append(
                {"url": u, "markdown": md, "error": None if str(md).strip() else "empty"}
            )
    return out


def _normalize_crawl_results(raw: Any) -> list[dict[str, Any]]:
    """Map crawl payload to list of {url, markdown, error}."""
    results_list: list = []
    if isinstance(raw, dict):
        if isinstance(raw.get("results"), list):
            results_list = raw["results"]
        elif isinstance(raw.get("data"), dict) and isinstance(raw["data"].get("results"), list):
            results_list = raw["data"]["results"]
        elif isinstance(raw.get("response_data"), dict) and isinstance(
            raw["response_data"].get("results"), list
        ):
            results_list = raw["response_data"]["results"]
        elif isinstance(raw.get("data"), list):
            results_list = raw["data"]
    elif isinstance(raw, list):
        results_list = raw

    out: list[dict[str, Any]] = []
    for r in results_list or []:
        if not isinstance(r, dict):
            continue
        url = r.get("url") or ""
        md = (
            r.get("raw_content")
            or r.get("markdown")
            or r.get("content")
            or r.get("text")
            or ""
        )
        if not url:
            continue
        out.append(
            {
                "url": url,
                "markdown": md,
                "error": None if str(md).strip() else "empty",
            }
        )
    return out
