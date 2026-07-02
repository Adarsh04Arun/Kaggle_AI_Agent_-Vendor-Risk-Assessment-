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

## Research Steps
1. **Summary Statistics**: Use the `get_vendor_cve_summary` tool to obtain \
   aggregated CVE statistics for the vendor (total CVEs, severity breakdown, \
   and average CVSS score). This is the fastest and most reliable method.

## Output Requirements
After completing your research, your final response MUST be a **single \
JSON object** (no extra text, no markdown fences) with exactly this structure:

```json
{
  "total_cves": <integer>,
  "critical_count": <integer>,
  "high_count": <integer>,
  "medium_count": <integer>,
  "low_count": <integer>,
  "avg_cvss_score": <float, rounded to 1 decimal>
}
```

## Important Rules
- Do NOT fabricate CVE counts or scores. Only report the exact statistics \
  returned by the `get_vendor_cve_summary` tool.
- If no CVEs are found for the vendor, set all counts and scores to `0` or `0.0`.
- Do not include any other keys in the JSON output.
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
