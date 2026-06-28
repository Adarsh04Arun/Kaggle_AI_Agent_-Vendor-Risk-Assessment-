"""
Web search abstraction layer with multi-backend support.

Supports Tavily, SerpAPI, and DuckDuckGo as search backends with
automatic fallback and specialised vendor-focused search helpers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for backend names
# ---------------------------------------------------------------------------
SearchBackend = Literal["tavily", "serpapi", "duckduckgo"]


class WebSearchClient:
    """Async web search client with pluggable backends.

    Parameters
    ----------
    backend:
        Primary search backend to use (``"tavily"``, ``"serpapi"``, or
        ``"duckduckgo"``).
    tavily_api_key:
        API key for the Tavily search API.
    serpapi_api_key:
        API key for SerpAPI.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        backend: SearchBackend = "duckduckgo",
        tavily_api_key: str | None = None,
        serpapi_api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._backend = backend
        self._tavily_api_key = tavily_api_key
        self._serpapi_api_key = serpapi_api_key
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Return (and lazily create) the shared ``httpx.AsyncClient``."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
            )
        return self._http

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Public search methods
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        num_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Run a general web search using the configured backend.

        Falls back to DuckDuckGo if the primary backend fails.

        Returns
        -------
        list[dict]
            Each result contains ``title``, ``snippet``, ``url``, and
            ``date`` keys.
        """
        try:
            results = await self._dispatch_search(
                self._backend, query, num_results
            )
            if results:
                return results
            logger.warning(
                "Primary backend '%s' returned no results for '%s'",
                self._backend,
                query,
            )
        except Exception:
            logger.exception(
                "Primary backend '%s' failed for query '%s'",
                self._backend,
                query,
            )

        # Fallback to DuckDuckGo (unless it was already the primary)
        if self._backend != "duckduckgo":
            logger.info("Falling back to DuckDuckGo for '%s'", query)
            try:
                return await self._search_duckduckgo(query, num_results)
            except Exception:
                logger.exception("DuckDuckGo fallback also failed for '%s'", query)

        return []

    async def search_vendor_breaches(
        self,
        vendor: str,
        years_back: int = 3,
    ) -> list[dict[str, Any]]:
        """Search for data-breach reports related to *vendor*.

        Generates queries like ``"{vendor} data breach {year}"`` for each
        of the past *years_back* years and aggregates results.
        """
        current_year = datetime.now(tz=timezone.utc).year
        all_results: list[dict[str, Any]] = []

        for year in range(current_year, current_year - years_back, -1):
            query = f"{vendor} data breach {year}"
            results = await self.search(query, num_results=5)
            all_results.extend(results)

        # Deduplicate by URL
        return _deduplicate(all_results)

    async def search_vendor_compliance(
        self,
        vendor: str,
    ) -> list[dict[str, Any]]:
        """Search for compliance and regulatory information about *vendor*."""
        queries = [
            f"{vendor} SOC 2 compliance",
            f"{vendor} ISO 27001 certification",
            f"{vendor} GDPR compliance",
            f"{vendor} regulatory action fine",
            f"{vendor} security audit report",
        ]
        all_results: list[dict[str, Any]] = []
        for query in queries:
            results = await self.search(query, num_results=5)
            all_results.extend(results)

        return _deduplicate(all_results)

    async def search_vendor_news(
        self,
        vendor: str,
    ) -> list[dict[str, Any]]:
        """Search for recent security-related news about *vendor*."""
        queries = [
            f"{vendor} security vulnerability recent",
            f"{vendor} cybersecurity incident",
            f"{vendor} security update patch",
        ]
        all_results: list[dict[str, Any]] = []
        for query in queries:
            results = await self.search(query, num_results=5)
            all_results.extend(results)

        return _deduplicate(all_results)

    # ------------------------------------------------------------------
    # Backend dispatching
    # ------------------------------------------------------------------

    async def _dispatch_search(
        self,
        backend: SearchBackend,
        query: str,
        num_results: int,
    ) -> list[dict[str, Any]]:
        """Route a search request to the appropriate backend."""
        if backend == "tavily":
            return await self._search_tavily(query, num_results)
        if backend == "serpapi":
            return await self._search_serpapi(query, num_results)
        return await self._search_duckduckgo(query, num_results)

    # ------------------------------------------------------------------
    # Tavily
    # ------------------------------------------------------------------

    async def _search_tavily(
        self,
        query: str,
        num_results: int,
    ) -> list[dict[str, Any]]:
        """Search via the Tavily search API."""
        if not self._tavily_api_key:
            raise ValueError("Tavily API key is not configured")

        client = await self._get_http_client()
        payload = {
            "api_key": self._tavily_api_key,
            "query": query,
            "max_results": num_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        logger.info("Tavily search: %s", query)
        response = await client.post(
            "https://api.tavily.com/search",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        results: list[dict[str, Any]] = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "snippet": item.get("content", ""),
                    "url": item.get("url", ""),
                    "date": item.get("published_date", ""),
                }
            )
        return results

    # ------------------------------------------------------------------
    # SerpAPI
    # ------------------------------------------------------------------

    async def _search_serpapi(
        self,
        query: str,
        num_results: int,
    ) -> list[dict[str, Any]]:
        """Search via the SerpAPI."""
        if not self._serpapi_api_key:
            raise ValueError("SerpAPI key is not configured")

        client = await self._get_http_client()
        params = {
            "api_key": self._serpapi_api_key,
            "q": query,
            "num": num_results,
            "engine": "google",
        }
        logger.info("SerpAPI search: %s", query)
        response = await client.get(
            "https://serpapi.com/search",
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        results: list[dict[str, Any]] = []
        for item in data.get("organic_results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "url": item.get("link", ""),
                    "date": item.get("date", ""),
                }
            )
        return results

    # ------------------------------------------------------------------
    # DuckDuckGo
    # ------------------------------------------------------------------

    async def _search_duckduckgo(
        self,
        query: str,
        num_results: int,
    ) -> list[dict[str, Any]]:
        """Search via the ``ddgs`` package (formerly ``duckduckgo_search``).

        Because ``DDGS`` is synchronous, the call is wrapped in
        ``asyncio.to_thread()`` to avoid blocking the event loop.
        """
        logger.info("DuckDuckGo search: %s", query)

        def _sync_search() -> list[dict[str, Any]]:
            try:
                from ddgs import DDGS
            except ImportError:
                # Fallback to old package name
                from duckduckgo_search import DDGS

            ddgs = DDGS()
            try:
                raw = list(ddgs.text(query, max_results=num_results))
            except Exception as exc:
                logger.warning("DDGS.text() failed: %s", exc)
                raw = []
            return [
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", r.get("link", "")),
                    "date": r.get("date", ""),
                }
                for r in raw
            ]

        return await asyncio.to_thread(_sync_search)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _deduplicate(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate results based on URL."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    return unique
