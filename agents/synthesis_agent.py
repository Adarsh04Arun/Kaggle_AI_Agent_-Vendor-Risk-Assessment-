"""
Synthesis Agent for Vendor Risk Assessment.

Creates a Google ADK ``LlmAgent`` that writes the **narrative** sections of the
risk report — executive summary plus CVE and OSINT analysis prose — under a
strict output schema.

Design (§5.7 — structured output):
    The numeric risk score is *never* produced by the LLM. It is computed
    deterministically in :mod:`agents.scoring` and merged by the orchestrator.
    This agent is therefore constrained to a tiny three-field JSON schema via
    ADK's ``output_schema``, which drives Ollama's structured-output ``format``
    and Gemini's controlled generation. A small, schema-constrained output is
    what a local model can emit reliably — eliminating the truncated /
    unparseable JSON that previously forced a narrative-less fallback.

The agent writes the structured narrative to session state key
``synthesis_narrative``.
"""

from __future__ import annotations

import logging

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from agents.model_factory import build_model

logger = logging.getLogger(__name__)


# ── Structured output schema ────────────────────────────────────────────────


class SynthesisNarrative(BaseModel):
    """The narrative sections of a vendor risk report.

    Deliberately small: three free-text fields and nothing numeric, so a local
    model can satisfy the schema in one short generation.
    """

    executive_summary: str = Field(
        description=(
            "A 3-5 sentence executive summary for C-level stakeholders "
            "describing the vendor's overall security posture and the most "
            "significant findings."
        )
    )
    cve_analysis: str = Field(
        description=(
            "A paragraph analysing the vulnerability findings: total CVE "
            "count, average CVSS, and the split of critical vs high severity."
        )
    )
    osint_analysis: str = Field(
        description=(
            "A paragraph analysing breach history, compliance issues, and "
            "security incidents surfaced by OSINT research."
        )
    )


# ── Agent Instruction Prompt ────────────────────────────────────────────────

_SYNTHESIS_INSTRUCTION = """\
You are a senior cybersecurity risk analyst. Write the narrative sections of a \
vendor risk assessment report for the vendor named `{vendor_name}`.

Two research agents have already gathered the findings below.

CVE findings (JSON — fields such as `total_cves`, `critical_count`, \
`high_count`, `medium_count`, `low_count`, `avg_cvss_score`):
{cve_findings}

OSINT findings (JSON — breaches, compliance issues, security incidents):
{osint_findings}

Cite the exact numbers from the CVE findings above; treat a missing field as 0 \
and never claim a count is "unknown" when the field is present.

A separate deterministic engine computes the numeric 0-100 risk score and risk \
level. Do NOT invent, state, or guess a specific numeric score or risk level — \
focus entirely on describing the qualitative findings.

Produce a JSON object with exactly these three string fields:
- `executive_summary`: 3-5 sentences summarising the vendor's overall security \
posture and the most significant findings, suitable for C-level stakeholders.
- `cve_analysis`: a concise paragraph on the vulnerability findings — total CVE \
count, average CVSS, and the distribution of critical vs high-severity issues.
- `osint_analysis`: a concise paragraph on breach history, compliance issues, \
and security incidents.

Ground every statement in the findings above. If a category has no findings, \
say so plainly rather than speculating. Output only the JSON object.
"""


def create_synthesis_agent(model: str | None = None) -> LlmAgent:
    """Create and return the narrative Synthesis ``LlmAgent``.

    The agent is constrained to :class:`SynthesisNarrative` via ``output_schema``
    (no tools), so its entire output is a small, schema-valid JSON object. The
    deterministic score is applied separately by the orchestrator.

    Args:
        model: Optional model id override. Falls back to ``AGENT_MODEL`` /
            a local Ollama default via :func:`agents.model_factory.build_model`.

    Returns:
        A configured :class:`google.adk.agents.LlmAgent` for the final stage of
        the pipeline.
    """
    logger.info("Creating Synthesis agent")

    # Pass the schema to the factory so Ollama models get an explicit
    # response_format (belt-and-suspenders alongside ADK's output_schema).
    resolved = build_model(model, response_schema=SynthesisNarrative)
    logger.info(
        "Synthesis agent using model: %s", getattr(resolved, "model", resolved)
    )

    agent = LlmAgent(
        name="synthesis_agent",
        model=resolved,
        instruction=_SYNTHESIS_INSTRUCTION,
        output_schema=SynthesisNarrative,
        output_key="synthesis_narrative",
        # output_schema is incompatible with agent transfer; keep synthesis
        # self-contained (it has no sub-agents / peers to hand off to anyway).
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )

    logger.info("Synthesis agent created successfully")
    return agent
