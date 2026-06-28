"""
MCP Server package for the Automated Vendor Risk Assessor.

Provides tools for CVE lookups, web search, and vendor risk analysis
via the Model Context Protocol (MCP).
"""

from mcp_server.nvd_client import NVDClient
from mcp_server.web_search_client import WebSearchClient

__all__ = ["NVDClient", "WebSearchClient"]
__version__ = "0.1.0"
