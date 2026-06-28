"""
FastMCP server for the Automated Vendor Risk Assessor.

Exposes tools for CVE lookups, web searches, and vendor risk analysis
over the Model Context Protocol (MCP) via stdio or SSE transport.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mcp_server.nvd_client import NVDClient
from mcp_server.web_search_client import WebSearchClient

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan – initialise / tear-down shared resources
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Initialise NVD and web-search clients for the server lifetime."""
    nvd_api_key = os.getenv("NVD_API_KEY")
    nvd_client = NVDClient(api_key=nvd_api_key)

    # Determine web-search backend
    search_backend = os.getenv("SEARCH_BACKEND", "duckduckgo").lower()
    web_client = WebSearchClient(
        backend=search_backend,  # type: ignore[arg-type]
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        serpapi_api_key=os.getenv("SERPAPI_API_KEY"),
    )

    logger.info(
        "Lifespan: NVD key=%s, search_backend=%s",
        "set" if nvd_api_key else "unset",
        search_backend,
    )

    try:
        yield {"nvd_client": nvd_client, "web_client": web_client}
    finally:
        await nvd_client.close()
        await web_client.close()
        logger.info("Lifespan: clients closed")


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP("vendor-risk-assessor", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _json(obj: Any) -> str:
    """Serialise *obj* to a compact JSON string."""
    return json.dumps(obj, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_cves(
    vendor: str,
    limit: int = 20,
    days_back: int = 730,
) -> str:
    """Search the NVD for CVEs related to a vendor or product.

    Args:
        vendor: Vendor or product name to search for.
        limit: Maximum number of CVE results to return.
        days_back: Only include CVEs published within this many days.

    Returns:
        JSON string with a list of matching CVE records.
    """
    ctx = mcp.get_context()
    nvd: NVDClient = ctx.request_context.lifespan_context["nvd_client"]
    results = await nvd.search_cves(vendor, limit=limit, days_back=days_back)
    return _json({"vendor": vendor, "total": len(results), "cves": results})


@mcp.tool()
async def get_cve_details(cve_id: str) -> str:
    """Retrieve detailed information for a specific CVE identifier.

    Args:
        cve_id: The CVE identifier, e.g. 'CVE-2023-12345'.

    Returns:
        JSON string with the full CVE record.
    """
    ctx = mcp.get_context()
    nvd: NVDClient = ctx.request_context.lifespan_context["nvd_client"]
    details = await nvd.get_cve_details(cve_id)
    return _json(details)


@mcp.tool()
async def get_vendor_products(vendor: str) -> str:
    """List known products for a vendor from the NVD CPE dictionary.

    Args:
        vendor: Vendor name to search for in the CPE dictionary.

    Returns:
        JSON string with matching CPE entries.
    """
    ctx = mcp.get_context()
    nvd: NVDClient = ctx.request_context.lifespan_context["nvd_client"]
    products = await nvd.search_cpe(vendor)
    return _json({"vendor": vendor, "products": products})


@mcp.tool()
async def search_web(query: str, num_results: int = 10) -> str:
    """Run a general web search.

    Args:
        query: The search query string.
        num_results: Maximum number of results to return.

    Returns:
        JSON string with a list of search results.
    """
    ctx = mcp.get_context()
    web: WebSearchClient = ctx.request_context.lifespan_context["web_client"]
    results = await web.search(query, num_results=num_results)
    return _json({"query": query, "total": len(results), "results": results})


@mcp.tool()
async def search_vendor_breaches(vendor: str, years_back: int = 3) -> str:
    """Search for data-breach reports involving a specific vendor.

    Args:
        vendor: Vendor name to search for.
        years_back: How many years back to search.

    Returns:
        JSON string with breach-related search results.
    """
    ctx = mcp.get_context()
    web: WebSearchClient = ctx.request_context.lifespan_context["web_client"]
    results = await web.search_vendor_breaches(vendor, years_back=years_back)
    return _json({"vendor": vendor, "total": len(results), "results": results})


@mcp.tool()
async def search_vendor_compliance(vendor: str) -> str:
    """Search for compliance and regulatory information about a vendor.

    Looks for SOC 2, ISO 27001, GDPR, regulatory actions, and audit reports.

    Args:
        vendor: Vendor name to search for.

    Returns:
        JSON string with compliance-related search results.
    """
    ctx = mcp.get_context()
    web: WebSearchClient = ctx.request_context.lifespan_context["web_client"]
    results = await web.search_vendor_compliance(vendor)
    return _json({"vendor": vendor, "total": len(results), "results": results})


@mcp.tool()
async def search_vendor_news(vendor: str) -> str:
    """Search for recent cybersecurity news about a vendor.

    Args:
        vendor: Vendor name to search for.

    Returns:
        JSON string with recent security news results.
    """
    ctx = mcp.get_context()
    web: WebSearchClient = ctx.request_context.lifespan_context["web_client"]
    results = await web.search_vendor_news(vendor)
    return _json({"vendor": vendor, "total": len(results), "results": results})


@mcp.tool()
async def get_vendor_cve_summary(vendor: str) -> str:
    """Get a high-level CVE severity summary for a vendor.

    Returns total CVE count, severity breakdown, average CVSS score,
    and the date of the most recent CVE.

    Args:
        vendor: Vendor name to summarise.

    Returns:
        JSON string with the vendor CVE summary.
    """
    ctx = mcp.get_context()
    nvd: NVDClient = ctx.request_context.lifespan_context["nvd_client"]
    summary = await nvd.get_vendor_cve_summary(vendor)
    return _json(summary)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    transport = "stdio"
    port = 8080

    # Simple CLI argument parsing for transport selection
    args = sys.argv[1:]
    if "--transport" in args:
        idx = args.index("--transport")
        if idx + 1 < len(args):
            transport = args[idx + 1]
    if "--port" in args:
        idx = args.index("--port")
        if idx + 1 < len(args):
            port = int(args[idx + 1])

    logger.info("Starting MCP server with transport=%s", transport)

    if transport == "sse":
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
