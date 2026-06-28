"""
Synthesis Agent for Vendor Risk Assessment.

Creates a Google ADK LlmAgent that merges OSINT and CVE findings, invokes the
deterministic :class:`~agents.scoring.RiskScorer` via a custom tool, and
produces a comprehensive risk report with executive summary, detailed analysis,
and actionable recommendations.

The agent stores the final report in session state key ``final_report``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import LlmAgent

from agents.scoring import RiskScorer, generate_recommendations

logger = logging.getLogger(__name__)

# ── Instantiate scorer once at module level (stateless, thread-safe) ────────
_scorer = RiskScorer()


# ── Custom Tool Function ───────────────────────────────────────────────────

def calculate_risk_score_tool(
    cve_data_json: str,
    osint_data_json: str,
) -> str:
    """Calculate a deterministic vendor risk score.

    This function is exposed as a tool to the Synthesis LlmAgent. It parses
    the JSON strings produced by the CVE and OSINT agents, runs them through
    the :class:`~agents.scoring.RiskScorer`, generates recommendations, and
    returns a consolidated JSON result.

    Args:
        cve_data_json: JSON string of CVE findings (from session state
            key ``cve_findings``).
        osint_data_json: JSON string of OSINT findings (from session state
            key ``osint_findings``).

    Returns:
        A JSON string containing the risk score, breakdown, and
        recommendations.
    """
    try:
        cve_data: dict[str, Any] = json.loads(cve_data_json) if cve_data_json else {}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse cve_data_json: %s", exc)
        cve_data = {}

    try:
        osint_data: dict[str, Any] = json.loads(osint_data_json) if osint_data_json else {}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse osint_data_json: %s", exc)
        osint_data = {}

    score_data = _scorer.calculate_risk_score(cve_data, osint_data)
    recommendations = generate_recommendations(score_data, cve_data, osint_data)

    result = {
        **score_data,
        "recommendations": recommendations,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Risk score tool returned: %.2f (%s)",
        score_data["overall_score"],
        score_data["risk_level"],
    )
    return json.dumps(result, indent=2)


# ── Agent Instruction Prompt ────────────────────────────────────────────────

_SYNTHESIS_INSTRUCTION = """\
You are a senior cybersecurity risk analyst responsible for synthesising \
research findings into a comprehensive vendor risk assessment report.

## Your Mission
Combine the OSINT and CVE research findings, compute a deterministic risk \
score, and produce a polished executive-level report for the vendor named in \
`{vendor_name}`.

## Steps — execute ALL of them in order

### Step 1 — Review Findings
The previous agents have already gathered data. You have access to:
- `osint_findings` — JSON from the OSINT agent (breaches, compliance, incidents)
- `cve_findings` — JSON from the CVE agent (vulnerabilities, severity counts)

Review all available findings from the conversation context.

### Step 2 — Compute Risk Score
Call the `calculate_risk_score_tool` with:
- `cve_data_json`: the CVE findings as a JSON string
- `osint_data_json`: the OSINT findings as a JSON string

If findings are not available, pass empty JSON objects "{}".

This tool returns the deterministic risk score, breakdown, and \
recommendations.

### Step 3 — Write Executive Summary
Write a concise 3-5 sentence executive summary suitable for C-level \
stakeholders. Include the overall risk score, risk level, and the most \
significant findings.

### Step 4 — Write Detailed Analysis
Write two detailed analysis sections:
- **CVE Analysis**: Summarise vulnerability findings, highlight the most \
  critical CVEs, affected products, and severity distribution.
- **OSINT Analysis**: Summarise breach history, compliance issues, security \
  incidents, and news sentiment.

### Step 5 — Compile Final Report
Your final response MUST be a **single JSON object** (no extra text before \
or after, no markdown code fences) with exactly this structure:

```json
{
  "vendor_name": "<vendor name>",
  "risk_score": <float 0-100>,
  "risk_level": "LOW / MEDIUM / HIGH / CRITICAL",
  "risk_color": "<hex color>",
  "score_breakdown": {
    "<factor>": {
      "score": <float>,
      "weight": <float>,
      "weighted_score": <float>,
      "description": "..."
    }
  },
  "executive_summary": "<3-5 sentence summary>",
  "cve_analysis": "<detailed CVE analysis narrative>",
  "osint_analysis": "<detailed OSINT analysis narrative>",
  "recommendations": ["<recommendation 1>", "..."],
  "assessed_at": "<ISO 8601 timestamp>"
}
```

## Important Rules
- The `risk_score`, `risk_level`, `risk_color`, `score_breakdown`, and \
  `recommendations` MUST come directly from the `calculate_risk_score_tool` \
  output. Do NOT override or modify the deterministic score.
- The `executive_summary`, `cve_analysis`, and `osint_analysis` are your \
  own written narratives — make them insightful and actionable.
- `assessed_at` comes from the tool output.
- If either `cve_findings` or `osint_findings` is missing or empty, note \
  that in the report but still produce a score with the available data.
- Do NOT call any tool named `save_session_state` — it does not exist. \
  Simply output the JSON directly as your response.
"""


def create_synthesis_agent() -> LlmAgent:
    """Create and return the Synthesis LlmAgent.

    The agent is equipped with the ``calculate_risk_score_tool`` which wraps
    the deterministic :class:`~agents.scoring.RiskScorer` engine.

    Returns:
        A configured :class:`google.adk.agents.LlmAgent` ready to be used
        as the final stage of the orchestrator pipeline.
    """
    logger.info("Creating Synthesis agent")

    model = os.getenv("AGENT_MODEL", "gemini-2.0-flash-lite")
    logger.info("Synthesis agent using model: %s", model)

    agent = LlmAgent(
        name="synthesis_agent",
        model=model,
        instruction=_SYNTHESIS_INSTRUCTION,
        tools=[calculate_risk_score_tool],
        output_key="final_report",
    )

    logger.info("Synthesis agent created successfully")
    return agent
