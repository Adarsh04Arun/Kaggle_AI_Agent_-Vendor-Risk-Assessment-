"""
Vendor Risk Assessment Orchestrator.

Provides :class:`VendorRiskOrchestrator`, the top-level controller that wires
together the OSINT, CVE, and Synthesis agents into a multi-stage pipeline,
manages MCP tool connectivity, and exposes batch-assessment capabilities.

Pipeline Architecture::

    ┌─────────────────────────────┐
    │   ParallelAgent             │
    │  ┌──────────┐ ┌──────────┐  │
    │  │ OSINT    │ │  CVE     │  │
    │  │ Agent    │ │  Agent   │  │
    │  └──────────┘ └──────────┘  │
    └──────────────┬──────────────┘
                   │
    ┌──────────────▼──────────────┐
    │   Synthesis Agent           │
    │  (deterministic scoring +   │
    │   narrative generation)     │
    └─────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from google.adk.agents import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import MCPToolset, SseConnectionParams, StdioConnectionParams
from google.genai import types
from mcp.client.stdio import StdioServerParameters

from agents.cve_agent import create_cve_agent
from agents.osint_agent import create_osint_agent
from agents.synthesis_agent import create_synthesis_agent

logger = logging.getLogger(__name__)

# Type alias for optional progress callbacks
ProgressCallback = Callable[[str, str, float | None], Any] | None


class VendorRiskOrchestrator:
    """Top-level orchestrator for the Automated Vendor Risk Assessor.

    Connects to an MCP server (via SSE or stdio), creates the agent pipeline,
    and runs vendor risk assessments.

    Args:
        mcp_server_url: SSE endpoint URL for the MCP server (mutually
            exclusive with *mcp_server_command*).
        mcp_server_command: Command + args to start an MCP stdio server
            (mutually exclusive with *mcp_server_url*).

    Example:
        >>> orchestrator = VendorRiskOrchestrator(
        ...     mcp_server_url="http://localhost:8080/sse"
        ... )
        >>> await orchestrator.setup()
        >>> report = await orchestrator.assess_vendor("Acme Corp")
        >>> await orchestrator.cleanup()
    """

    # Maximum concurrent vendor assessments in batch mode
    _MAX_CONCURRENCY: int = 3

    def __init__(
        self,
        mcp_server_url: str | None = None,
        mcp_server_command: list[str] | None = None,
        model: str | None = None,
    ) -> None:
        if mcp_server_url and mcp_server_command:
            raise ValueError(
                "Specify either mcp_server_url (SSE) or "
                "mcp_server_command (stdio), not both."
            )

        self._mcp_server_url = mcp_server_url
        self._mcp_server_command = mcp_server_command
        # Model id for the agent pipeline. The web app passes a Gemini model;
        # the CLI relies on AGENT_MODEL (Ollama). None → resolved per-agent.
        self._model = model

        # Initialised during setup()
        self._mcp_toolset: MCPToolset | None = None
        self._pipeline: SequentialAgent | None = None
        self._session_service: InMemorySessionService | None = None
        self._runner: Runner | None = None
        self._is_setup: bool = False

    # ── Setup & Teardown ────────────────────────────────────────────────

    async def setup(self) -> None:
        """Connect to the MCP server and initialise all agents.

        Raises:
            RuntimeError: If setup has already been called.
        """
        if self._is_setup:
            logger.warning("Orchestrator.setup() called more than once — skipping")
            return

        logger.info("Setting up Vendor Risk Orchestrator…")

        # ── Create MCP toolset ─────────────────────────────────────────
        self._create_mcp_toolset()

        # ── Build agent pipeline ───────────────────────────────────────
        self._build_pipeline()

        # ── Session service & runner ───────────────────────────────────
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            agent=self._pipeline,
            app_name="vendor_risk_assessor",
            session_service=self._session_service,
        )

        self._is_setup = True
        logger.info("Orchestrator setup complete")

    async def cleanup(self) -> None:
        """Disconnect from the MCP server and release resources."""
        logger.info("Cleaning up Vendor Risk Orchestrator…")
        if self._mcp_toolset is not None:
            try:
                await self._mcp_toolset.close()
                logger.info("MCP toolset closed")
            except Exception:
                logger.exception("Error closing MCP toolset")
            finally:
                self._mcp_toolset = None

        self._is_setup = False
        logger.info("Orchestrator cleanup complete")

    # ── Public Assessment API ───────────────────────────────────────────

    async def assess_vendor(
        self,
        vendor_name: str,
        progress_callback: ProgressCallback = None,
    ) -> dict[str, Any]:
        """Run a full risk assessment for a single vendor.

        Args:
            vendor_name: Name of the vendor to assess.
            progress_callback: Optional ``(vendor, status, progress)``
                callback for UI updates.

        Returns:
            The final risk assessment report as a dict.

        Raises:
            RuntimeError: If :meth:`setup` has not been called.
        """
        if not self._is_setup:
            raise RuntimeError("Call setup() before assess_vendor()")

        logger.info("Starting assessment for vendor: %s", vendor_name)
        self._notify(progress_callback, vendor_name, "Starting assessment", 0.0)

        # ── Create a fresh session with the vendor name in state ───────
        session_id = str(uuid.uuid4())
        session = await self._session_service.create_session(
            app_name="vendor_risk_assessor",
            user_id="system",
            session_id=session_id,
            # Seed empty findings so the synthesis agent's instruction
            # templating ({cve_findings}/{osint_findings}) is always safe — the
            # parallel research agents overwrite these via their output_key.
            state={
                "vendor_name": vendor_name,
                "cve_findings": "{}",
                "osint_findings": "{}",
            },
        )

        self._notify(progress_callback, vendor_name, "Gathering intelligence", 0.1)

        # ── Run the pipeline ───────────────────────────────────────────
        user_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        f"Perform a comprehensive vendor risk assessment for: "
                        f"{vendor_name}"
                    )
                )
            ],
        )

        final_report: dict[str, Any] = {}
        try:
            async for event in self._runner.run_async(
                user_id="system",
                session_id=session_id,
                new_message=user_message,
            ):
                # Track progress via agent names
                if hasattr(event, "author"):
                    if event.author == "osint_agent":
                        self._notify(
                            progress_callback,
                            vendor_name,
                            "OSINT research in progress",
                            0.3,
                        )
                    elif event.author == "cve_agent":
                        self._notify(
                            progress_callback,
                            vendor_name,
                            "CVE analysis in progress",
                            0.3,
                        )
                    elif event.author == "synthesis_agent":
                        self._notify(
                            progress_callback,
                            vendor_name,
                            "Synthesising findings",
                            0.7,
                        )

            # ── Extract final report from session state ────────────────
            updated_session = await self._session_service.get_session(
                app_name="vendor_risk_assessor",
                user_id="system",
                session_id=session_id,
            )

            # ── Parse structured findings ──────────────────────────────
            # Written to session state by the CVE and OSINT agents. Reused for
            # deterministic scoring and the machine-readable metrics block.
            cve_data = self._loads_loose(
                updated_session.state.get("cve_findings") if updated_session else None
            )
            osint_data = self._loads_loose(
                updated_session.state.get("osint_findings") if updated_session else None
            )

            # ── Deterministic scoring (always) ─────────────────────────
            # The score is never produced by the LLM — it is computed in code
            # from the findings, so it is auditable and identical for identical
            # inputs. The synthesis agent only supplies narrative prose.
            self._notify(progress_callback, vendor_name, "Scoring findings", 0.9)

            from agents.scoring import RiskScorer, generate_recommendations

            scorer = RiskScorer()
            score_data = scorer.calculate_risk_score(cve_data, osint_data)
            recommendations = generate_recommendations(
                score_data, cve_data, osint_data
            )

            # ── Merge the structured narrative (§5.7) ──────────────────
            # The synthesis agent emits a schema-constrained
            # {executive_summary, cve_analysis, osint_analysis} object. If a
            # (usually small, local) model still fails to produce usable prose,
            # fall back to a deterministic template so the report is complete.
            narrative = self._loads_loose(
                updated_session.state.get("synthesis_narrative")
                if updated_session
                else None
            )
            exec_summary = str(narrative.get("executive_summary", "")).strip()
            cve_analysis = str(narrative.get("cve_analysis", "")).strip()
            osint_analysis = str(narrative.get("osint_analysis", "")).strip()

            if exec_summary and cve_analysis and osint_analysis:
                synthesis_method = "llm"
            else:
                synthesis_method = "template"
                logger.warning(
                    "Synthesis narrative incomplete for %s — using deterministic "
                    "narrative template",
                    vendor_name,
                )
                exec_summary = exec_summary or score_data["summary"]
                cve_analysis = cve_analysis or (
                    f"Found {cve_data.get('total_cves', 0)} CVEs: "
                    f"{cve_data.get('critical_count', 0)} critical, "
                    f"{cve_data.get('high_count', 0)} high, "
                    f"{cve_data.get('medium_count', 0)} medium, "
                    f"{cve_data.get('low_count', 0)} low. "
                    f"Average CVSS: {cve_data.get('avg_cvss_score', 0.0)}"
                )
                osint_analysis = osint_analysis or (
                    f"{osint_data.get('breach_count', 0)} breach(es) found. "
                    f"{len(osint_data.get('compliance_issues', []))} compliance issue(s). "
                    f"{len(osint_data.get('security_incidents', []))} security incident(s)."
                )

            final_report = {
                "vendor_name": vendor_name,
                "risk_score": score_data["overall_score"],
                "risk_level": score_data["risk_level"],
                "risk_color": score_data["risk_color"],
                "score_breakdown": score_data["breakdown"],
                "executive_summary": exec_summary,
                "cve_analysis": cve_analysis,
                "osint_analysis": osint_analysis,
                "recommendations": recommendations,
                "assessed_at": datetime.now(timezone.utc).isoformat(),
                # Score is always deterministic; narrative may be LLM or template.
                "scoring_method": "deterministic",
                "synthesis_method": synthesis_method,
                # Machine-readable numbers for the web matrix / CLI summary table.
                "metrics": self._build_metrics(cve_data, osint_data),
            }

            logger.info(
                "Assessment scored for %s: %.2f (%s) · narrative=%s",
                vendor_name,
                score_data["overall_score"],
                score_data["risk_level"],
                synthesis_method,
            )

        except Exception:
            logger.exception("Assessment failed for vendor: %s", vendor_name)
            final_report = {
                "vendor_name": vendor_name,
                "error": "Assessment pipeline failed. Check logs for details.",
                "risk_score": None,
                "risk_level": "UNKNOWN",
            }

        self._notify(progress_callback, vendor_name, "Assessment complete", 1.0)
        logger.info("Assessment complete for vendor: %s", vendor_name)
        return final_report

    async def assess_vendors_batch(
        self,
        vendor_names: list[str],
        progress_callback: ProgressCallback = None,
    ) -> list[dict[str, Any]]:
        """Run risk assessments for multiple vendors concurrently.

        Concurrency is bounded by a semaphore (default: 3 simultaneous
        assessments) to avoid overwhelming the MCP server and LLM API.

        Args:
            vendor_names: List of vendor names to assess.
            progress_callback: Optional ``(vendor, status, progress)``
                callback for UI updates.

        Returns:
            List of report dicts, one per vendor, in the same order as the
            input list.
        """
        if not self._is_setup:
            raise RuntimeError("Call setup() before assess_vendors_batch()")

        logger.info(
            "Starting batch assessment for %d vendor(s)", len(vendor_names)
        )

        semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)

        async def _bounded_assess(name: str) -> dict[str, Any]:
            async with semaphore:
                return await self.assess_vendor(name, progress_callback)

        tasks = [_bounded_assess(name) for name in vendor_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions into error dicts
        reports: list[dict[str, Any]] = []
        for vendor_name, result in zip(vendor_names, results):
            if isinstance(result, Exception):
                logger.error(
                    "Batch assessment failed for %s: %s", vendor_name, result
                )
                reports.append(
                    {
                        "vendor_name": vendor_name,
                        "error": str(result),
                        "risk_score": None,
                        "risk_level": "UNKNOWN",
                    }
                )
            else:
                reports.append(result)

        logger.info("Batch assessment complete: %d report(s)", len(reports))
        return reports

    # ── Internal Helpers ────────────────────────────────────────────────

    def _create_mcp_toolset(self) -> None:
        """Create the MCPToolset instance (connection is lazy/managed by ADK)."""
        if not self._mcp_server_url and not self._mcp_server_command:
            logger.warning(
                "No MCP server configured — agents will run without MCP tools"
            )
            self._mcp_toolset = None
            return

        try:
            if self._mcp_server_url:
                logger.info(
                    "Creating MCP toolset via SSE: %s", self._mcp_server_url
                )
                self._mcp_toolset = MCPToolset(
                    connection_params=SseConnectionParams(
                        url=self._mcp_server_url,
                    )
                )
            else:
                logger.info(
                    "Creating MCP toolset via stdio: %s",
                    self._mcp_server_command,
                )
                self._mcp_toolset = MCPToolset(
                    connection_params=StdioConnectionParams(
                        server_params=StdioServerParameters(
                            command=self._mcp_server_command[0],
                            args=self._mcp_server_command[1:]
                            if len(self._mcp_server_command) > 1
                            else [],
                            # Forward the parent environment (e.g. MCP_LOG_LEVEL)
                            # — the MCP SDK otherwise spawns with a minimal env.
                            env=dict(os.environ),
                        ),
                        timeout=120.0,
                    )
                )
            logger.info("MCP toolset created successfully")

        except Exception:
            logger.exception(
                "Failed to create MCP toolset — proceeding without MCP tools"
            )
            self._mcp_toolset = None

    def _build_pipeline(self) -> None:
        """Construct the multi-agent pipeline.

        Architecture:
            1. ``ParallelAgent`` runs OSINT and CVE agents concurrently.
            2. ``SequentialAgent`` feeds the parallel stage output into the
               Synthesis agent for scoring and report generation.
        """
        logger.info("Building agent pipeline…")

        # Build the tools list: include the MCP toolset if available
        mcp_tools = [self._mcp_toolset] if self._mcp_toolset else []

        osint_agent = create_osint_agent(mcp_tools, model=self._model)
        cve_agent = create_cve_agent(mcp_tools, model=self._model)
        synthesis_agent = create_synthesis_agent(model=self._model)

        # Stage 1: Parallel data gathering
        parallel_research = ParallelAgent(
            name="parallel_research",
            sub_agents=[osint_agent, cve_agent],
        )

        # Stage 2: Sequential pipeline — research then synthesis
        self._pipeline = SequentialAgent(
            name="vendor_risk_pipeline",
            sub_agents=[parallel_research, synthesis_agent],
        )

        logger.info("Agent pipeline built successfully")

    @staticmethod
    def _loads_loose(raw: Any) -> dict[str, Any]:
        """Best-effort parse of a possibly-messy JSON payload into a dict.

        Handles the three shapes local models routinely emit: a clean dict, a
        raw JSON string, JSON wrapped in ``` ```json ``` ``` fences, or JSON
        embedded in surrounding prose. Returns ``{}`` when nothing parses.
        """
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return {}

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

        import re

        # Fenced ```json ... ``` block first, then any {...} object.
        fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if fence:
            try:
                parsed = json.loads(fence.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace:
            try:
                parsed = json.loads(brace.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return {}

    @staticmethod
    def _build_metrics(
        cve_data: dict[str, Any],
        osint_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a flat, machine-readable metrics block for the UIs."""

        def _count(value: Any) -> int:
            if isinstance(value, list):
                return len(value)
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        try:
            avg_cvss = round(float(cve_data.get("avg_cvss_score", 0.0) or 0.0), 1)
        except (TypeError, ValueError):
            avg_cvss = 0.0

        return {
            "total_cves": _count(cve_data.get("total_cves", 0)),
            "critical_count": _count(cve_data.get("critical_count", 0)),
            "high_count": _count(cve_data.get("high_count", 0)),
            "medium_count": _count(cve_data.get("medium_count", 0)),
            "low_count": _count(cve_data.get("low_count", 0)),
            "avg_cvss": avg_cvss,
            "breach_count": _count(osint_data.get("breach_count", 0)),
            "compliance_issues": _count(osint_data.get("compliance_issues", [])),
            "security_incidents": _count(osint_data.get("security_incidents", [])),
        }

    @staticmethod
    def _notify(
        callback: ProgressCallback,
        vendor_name: str,
        status: str,
        progress: float | None,
    ) -> None:
        """Fire the progress callback if one is provided."""
        if callback is not None:
            try:
                callback(vendor_name, status, progress)
            except Exception:
                logger.exception("Progress callback raised an exception")


# ── Convenience Function ────────────────────────────────────────────────────


async def run_assessment(
    vendor_names: list[str],
    mcp_transport: str = "stdio",
    mcp_server_url: str | None = None,
    mcp_server_command: list[str] | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Run vendor risk assessments with minimal boilerplate.

    This is a standalone convenience function that creates an orchestrator,
    runs assessments, and cleans up — suitable for scripts and notebooks.

    Args:
        vendor_names: List of vendor names to assess.
        mcp_transport: Transport type — ``'sse'`` or ``'stdio'`` (default).
        mcp_server_url: SSE endpoint URL (required if *mcp_transport* is
            ``'sse'``).
        mcp_server_command: Stdio command + args (used when *mcp_transport*
            is ``'stdio'``). Defaults to
            ``["python", "-m", "mcp_server.server"]``.

    Returns:
        List of assessment report dicts, one per vendor.

    Example:
        >>> import asyncio
        >>> reports = asyncio.run(run_assessment(["Acme Corp", "Globex"]))
    """
    if mcp_transport == "sse":
        orchestrator = VendorRiskOrchestrator(
            mcp_server_url=mcp_server_url or "http://localhost:8080/sse",
            model=model,
        )
    else:
        orchestrator = VendorRiskOrchestrator(
            mcp_server_command=mcp_server_command
            or ["python", "-m", "mcp_server.server"],
            model=model,
        )

    try:
        await orchestrator.setup()
        reports = await orchestrator.assess_vendors_batch(vendor_names)
    finally:
        await orchestrator.cleanup()

    return reports
