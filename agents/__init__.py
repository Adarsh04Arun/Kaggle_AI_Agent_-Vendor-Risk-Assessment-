"""
Automated Vendor Risk Assessor — Multi-Agent System.

This package provides the core agent components for automated vendor risk
assessment, built on the Google ADK (Agent Development Kit).

Architecture:
    - **OSINT Agent** — gathers open-source intelligence (breaches, compliance,
      incidents, news) via MCP tools.
    - **CVE Agent** — searches the NVD for vendor-related vulnerabilities via
      MCP tools.
    - **Synthesis Agent** — merges OSINT + CVE findings, computes a
      deterministic risk score, and generates a narrative report.
    - **Orchestrator** — wires the agents into a parallel → sequential pipeline
      and manages MCP connectivity, sessions, and batch execution.

Quick Start:
    >>> import asyncio
    >>> from agents import run_assessment
    >>> reports = asyncio.run(run_assessment(["Acme Corp"]))
"""

from __future__ import annotations

from agents.scoring import RiskScorer, generate_recommendations
from agents.osint_agent import create_osint_agent
from agents.cve_agent import create_cve_agent
from agents.synthesis_agent import create_synthesis_agent
from agents.orchestrator import VendorRiskOrchestrator, run_assessment

__all__ = [
    # Orchestrator
    "VendorRiskOrchestrator",
    "run_assessment",
    # Agent factories
    "create_osint_agent",
    "create_cve_agent",
    "create_synthesis_agent",
    # Scoring
    "RiskScorer",
    "generate_recommendations",
]
