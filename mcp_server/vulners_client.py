"""
Vulners API async client.

Provides methods for searching CVEs and retrieving CVE details
using the Vulners API as a faster, more reliable alternative to NVD.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_VULNERS_SEARCH_URL = "https://vulners.com/api/v3/search/lucene/"
_VULNERS_ID_URL = "https://vulners.com/api/v3/search/id/"
_DEFAULT_CACHE_TTL = 600


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class VulnersClient:
    """Async wrapper around the Vulners API."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._timeout = timeout

        self._cache: dict[str, _CacheEntry] = {}
        self._http: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                headers={"Accept": "application/json"},
                timeout=httpx.Timeout(self._timeout),
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        self._cache.clear()

    def _cache_get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._cache[key]
            return None
        return entry.value

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = _CacheEntry(value, self._cache_ttl)

    async def _request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a POST request to Vulners."""
        if self._api_key:
            payload["apiKey"] = self._api_key
            
        # Serialize for cache key (excluding API key)
        cache_payload = {k: v for k, v in payload.items() if k != "apiKey"}
        cache_key = f"{url}|{cache_payload}"
        
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        client = await self._get_http_client()
        logger.info("Vulners request: %s (query: %s)", url, payload.get("query", payload.get("id")))

        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if data.get("result") == "error":
                logger.error("Vulners API error: %s", data.get("data", {}).get("error"))
                
            self._cache_set(cache_key, data)
            return data
        except httpx.HTTPStatusError as exc:
            logger.error("Vulners API HTTP error %s for %s", exc.response.status_code, url)
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_cves(
        self,
        keyword: str,
        limit: int = 20,
        days_back: int = 730,
    ) -> list[dict[str, Any]]:
        """Search Vulners for CVEs matching *keyword*."""
        
        # Build lucene query
        # We enforce type:cve to only get CVEs
        query = f'"{keyword}" AND type:cve'
        
        if days_back and days_back > 0:
            now = datetime.now(tz=timezone.utc)
            start = now - timedelta(days=days_back)
            # Vulners uses ISO dates in lucene queries: published:[2023-01-01 TO 2024-01-01]
            start_str = start.strftime("%Y-%m-%d")
            now_str = now.strftime("%Y-%m-%d")
            query += f" AND published:[{start_str} TO {now_str}]"
            
        payload = {
            "query": query,
            "size": limit,
            "sort": "published"
        }
        
        data = await self._request(_VULNERS_SEARCH_URL, payload)
        
        results = data.get("data", {}).get("search", [])
        return [self._parse_vulners_doc(doc) for doc in results]

    async def get_cve_details(self, cve_id: str) -> dict[str, Any]:
        """Retrieve detailed information for a single CVE."""
        payload = {"id": cve_id}
        data = await self._request(_VULNERS_ID_URL, payload)
        
        docs = data.get("data", {}).get("documents", {})
        if not docs or cve_id not in docs:
            return {"error": f"CVE {cve_id} not found"}
            
        return self._parse_vulners_doc(docs[cve_id])

    async def search_cpe(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        """Mock CPE search since Vulners doesn't expose a direct CPE dictionary search in the free API."""
        return [{"cpe_name": f"cpe:2.3:a:{keyword.lower().replace(' ', '_')}:product:*:*:*:*:*:*:*:*", "title": keyword, "deprecated": False}]

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _parse_vulners_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw Vulners document into the NVD-style flat dict expected by the agents."""
        source = doc.get("_source", {})
        
        cvss_data = source.get("cvss3", source.get("cvss2", {}))
        
        # Determine score
        cvss_score = source.get("cvss", {}).get("score")
        if cvss_score is None:
            # Fallback for some documents
            cvss_score = cvss_data.get("cvssV3", {}).get("baseScore", 0.0)
            
        # Determine severity based on NVD mapping
        severity = "UNKNOWN"
        if cvss_score:
            score = float(cvss_score)
            if score >= 9.0: severity = "CRITICAL"
            elif score >= 7.0: severity = "HIGH"
            elif score >= 4.0: severity = "MEDIUM"
            elif score > 0.0: severity = "LOW"
            
        return {
            "id": source.get("id", ""),
            "description": source.get("description", ""),
            "published": source.get("published", ""),
            "last_modified": source.get("modified", ""),
            "cvss_score": cvss_score,
            "severity": severity,
            "weaknesses": source.get("cwe", []),
            "references": [{"url": ref, "source": "vulners"} for ref in source.get("hrefs", [])],
        }
