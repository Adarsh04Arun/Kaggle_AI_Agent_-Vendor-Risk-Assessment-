"""
CVE (Common Vulnerabilities and Exposures) Agent for Vendor Risk Assessment.

Creates a Google ADK LlmAgent that searches the National Vulnerability Database
(NVD) for CVEs associated with a vendor's products, analyses severity
distribution, and stores structured findings in the ADK session state.

The agent stores its findings under session state key ``cve_findings``
as a JSON string conforming to a well-defined schema.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google.adk.agents import LlmAgent

logger = logging.getLogger(__name__)

# ── Agent Instruction Prompt ────────────────────────────────────────────────

_CVE_INSTRUCTION = """\
You are a vulnerability analyst specialising in CVE research and vendor \
product security assessment.

## Your Mission
Conduct a thorough CVE analysis for the vendor named in `{vendor_name}` \
(read from session state key `vendor_name`).

## Research Steps — execute ALL of them in order
1. **Product Discovery**: Use `get_vendor_products` to identify the vendor's \
   known products and their CPE (Common Platform Enumeration) identifiers.
2. **CVE Search**: Use `search_cves` to find all known CVEs associated with \
   the vendor and/or its products. Search by vendor name, product names, and \
   CPE strings.
3. **Severity Analysis**: For the most critical CVEs, use `get_cve_details` \
   to retrieve full details including CVSS scores, attack vectors, and \
   affected versions.
4. **Summary Statistics**: Use `get_vendor_cve_summary` to obtain aggregated \
   CVE statistics if available, and cross-reference with your own findings.

## Output Requirements
After completing ALL research steps, your final response MUST be a **single \
JSON object** (no extra text, no markdown fences) with exactly this structure:

```json
{
  "total_cves": <integer>,
  "critical_count": <integer>,
  "high_count": <integer>,
  "medium_count": <integer>,
  "low_count": <integer>,
  "avg_cvss_score": <float, rounded to 1 decimal>,
  "top_cves": [
    {
      "cve_id": "CVE-YYYY-NNNNN",
      "cvss_score": <float>,
      "severity": "CRITICAL / HIGH / MEDIUM / LOW",
      "description": "Short description of the vulnerability",
      "affected_product": "Product name and version(s)",
      "published_date": "YYYY-MM-DD",
      "attack_vector": "NETWORK / ADJACENT / LOCAL / PHYSICAL"
    }
  ],
  "most_recent_cve": {
    "cve_id": "CVE-YYYY-NNNNN",
    "published_date": "YYYY-MM-DD",
    "severity": "CRITICAL / HIGH / MEDIUM / LOW",
    "description": "..."
  },
  "affected_products": [
    {
      "product_name": "...",
      "cpe": "cpe:2.3:...",
      "cve_count": <integer>,
      "highest_cvss": <float>
    }
  ]
}
```

## Important Rules
- Severity thresholds follow CVSS v3.x: CRITICAL ≥ 9.0, HIGH ≥ 7.0, \
  MEDIUM ≥ 4.0, LOW < 4.0.
- `top_cves` should contain the 10 most severe CVEs, sorted by CVSS \
  descending. If fewer than 10 exist, include all.
- `most_recent_cve` is the CVE with the latest `published_date`. Set to \
  `null` if no CVEs were found.
- `avg_cvss_score` is the arithmetic mean of all CVSS scores found. Set to \
  `0.0` if no CVEs exist.
- If no CVEs are found for the vendor, set all counts to `0`, lists to `[]`, \
  and `most_recent_cve` to `null`.
- Do NOT fabricate CVE IDs or scores. Only report real, verified CVE data.
- Be thorough — search by vendor name AND individual product names.
"""


def create_cve_agent(mcp_tools: list[Any]) -> LlmAgent:
    """Create and return the CVE research LlmAgent.

    Args:
        mcp_tools: List of MCP tool instances to attach to the agent.
            Expected tools include ``search_cves``, ``get_cve_details``,
            ``get_vendor_products``, and ``get_vendor_cve_summary``.

    Returns:
        A configured :class:`google.adk.agents.LlmAgent` ready to be used
        inside the orchestrator pipeline.
    """
    logger.info(
        "Creating CVE agent with %d MCP tool(s)",
        len(mcp_tools) if mcp_tools else 0,
    )

    model = os.getenv("AGENT_MODEL", "gemini-2.0-flash-lite")
    logger.info("CVE agent using model: %s", model)

    agent = LlmAgent(
        name="cve_agent",
        model=model,
        instruction=_CVE_INSTRUCTION,
        tools=mcp_tools or [],
        output_key="cve_findings",
    )

    logger.info("CVE agent created successfully")
    return agent
