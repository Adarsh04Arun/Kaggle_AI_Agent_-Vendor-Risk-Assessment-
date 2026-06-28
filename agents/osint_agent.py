"""
OSINT (Open Source Intelligence) Agent for Vendor Risk Assessment.

Creates a Google ADK LlmAgent that gathers open-source intelligence about a
vendor's security posture, including data breaches, regulatory actions,
compliance failures, security incidents, and relevant news coverage.

The agent stores its findings in the ADK session state under the key
``osint_findings`` as a JSON string conforming to a well-defined schema.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google.adk.agents import LlmAgent

logger = logging.getLogger(__name__)

# ── Agent Instruction Prompt ────────────────────────────────────────────────

_OSINT_INSTRUCTION = """\
You are an OSINT (Open Source Intelligence) analyst specialising in vendor \
cybersecurity risk assessment.

## Your Mission
Gather comprehensive open-source intelligence about the vendor named in \
`{vendor_name}` (read from session state key `vendor_name`).

## Research Steps — execute ALL of them
1. **Data Breaches**: Use `search_vendor_breaches` and `search_web` to find \
   every known data breach involving the vendor. Record breach dates, scope, \
   data types affected, and root cause if available.
2. **Regulatory & Compliance**: Use `search_vendor_compliance` to find \
   regulatory actions, fines, consent decrees, GDPR violations, or other \
   compliance failures.
3. **Security Incidents**: Use `search_web` to find reports of security \
   incidents such as ransomware attacks, DDoS, supply-chain compromises, or \
   insider threats.
4. **Security News**: Use `search_vendor_news` and `search_web` to find \
   recent news articles discussing the vendor's security posture, security \
   investments, or security leadership changes.

## Output Requirements
After completing ALL research steps, your final response MUST be a **single \
JSON object** (no extra text, no markdown fences) with exactly this structure:

```json
{
  "breaches": [
    {
      "date": "YYYY-MM-DD or YYYY",
      "description": "...",
      "records_affected": "number or 'unknown'",
      "data_types": ["PII", "financial", "..."],
      "source": "URL or source name"
    }
  ],
  "compliance_issues": [
    {
      "type": "GDPR fine / FTC action / ...",
      "date": "YYYY-MM-DD or YYYY",
      "description": "...",
      "penalty": "amount or 'N/A'",
      "source": "URL or source name"
    }
  ],
  "security_incidents": [
    {
      "date": "YYYY-MM-DD or YYYY",
      "type": "ransomware / DDoS / supply-chain / ...",
      "description": "...",
      "source": "URL or source name"
    }
  ],
  "news_items": [
    {
      "date": "YYYY-MM-DD",
      "headline": "...",
      "summary": "...",
      "sentiment": "positive / negative / neutral",
      "source": "URL or source name"
    }
  ],
  "breach_count": <integer>,
  "most_recent_breach_year": <integer or null>
}
```

## Important Rules
- If you cannot find information for a category, use an **empty list** `[]` \
  for that key — never omit a key.
- `breach_count` must equal the length of the `breaches` list.
- `most_recent_breach_year` is the 4-digit year of the most recent breach, \
  or `null` if no breaches were found.
- Be thorough — check multiple sources before concluding no results exist.
- Cite sources wherever possible.
- Do NOT fabricate or hallucinate findings. If uncertain, note the uncertainty.
"""


def create_osint_agent(mcp_tools: list[Any]) -> LlmAgent:
    """Create and return the OSINT LlmAgent.

    Args:
        mcp_tools: List of MCP tool instances to attach to the agent.
            Expected tools include ``search_web``, ``search_vendor_breaches``,
            ``search_vendor_compliance``, and ``search_vendor_news``.

    Returns:
        A configured :class:`google.adk.agents.LlmAgent` ready to be used
        inside the orchestrator pipeline.
    """
    logger.info(
        "Creating OSINT agent with %d MCP tool(s)",
        len(mcp_tools) if mcp_tools else 0,
    )

    model = os.getenv("AGENT_MODEL", "gemini-2.0-flash-lite")
    logger.info("OSINT agent using model: %s", model)

    agent = LlmAgent(
        name="osint_agent",
        model=model,
        instruction=_OSINT_INSTRUCTION,
        tools=mcp_tools or [],
        output_key="osint_findings",
    )

    logger.info("OSINT agent created successfully")
    return agent
