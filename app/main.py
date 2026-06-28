"""
Automated Vendor Risk Assessor — FastAPI Backend Application.

Provides REST API and SSE streaming endpoints for assessing vendor
cybersecurity risk using AI agents orchestrated via Google ADK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vendor_risk_assessor")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

# Ensure directories exist so mounting never fails during development.
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Automated Vendor Risk Assessor",
    description="AI-powered vendor cybersecurity risk assessment platform",
    version="1.0.0",
)

# CORS — allow everything in dev; tighten in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

jobs: dict[str, dict[str, Any]] = {}
"""
Each job is a dict with the following shape:
{
    "id":              str,
    "status":          "pending" | "running" | "completed" | "error",
    "vendors":         list[str],
    "results":         dict | None,
    "progress_events": list[dict],
    "queue":           asyncio.Queue,      # for SSE streaming
}
"""

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AssessRequest(BaseModel):
    """Incoming assessment request."""

    vendors: list[str] = Field(
        ...,
        min_length=1,
        description="List of vendor names to assess.",
        examples=[["Acme Corp", "Globex", "Initech"]],
    )


class AssessResponse(BaseModel):
    """Acknowledge that an assessment job has been queued."""

    job_id: str
    status: str = "started"


class HealthResponse(BaseModel):
    """Health-check response."""

    status: str = "healthy"


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------


def _sse_event(
    event_type: str,
    *,
    vendor: str | None = None,
    message: str | None = None,
    data: Any = None,
) -> str:
    """Format a single Server-Sent Event payload."""
    payload: dict[str, Any] = {"type": event_type}
    if vendor is not None:
        payload["vendor"] = vendor
    if message is not None:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# Background assessment runner
# ---------------------------------------------------------------------------


async def run_assessment_job(job_id: str, vendors: list[str]) -> None:
    """Run the full vendor-risk assessment pipeline in the background.

    Events are pushed onto the job's :pyclass:`asyncio.Queue` so that the
    SSE endpoint can stream them to the client in real time.

    Args:
        job_id: Unique identifier for this assessment job.
        vendors: List of vendor names to assess.
    """
    job = jobs[job_id]
    queue: asyncio.Queue[str | None] = job["queue"]

    try:
        job["status"] = "running"

        # Push initial progress event ----------------------------------------
        evt = _sse_event(
            "progress",
            message="Initializing assessment orchestrator…",
        )
        job["progress_events"].append(evt)
        await queue.put(evt)

        # Import orchestrator lazily so the web layer stays functional even
        # when the agents package is not fully configured.
        try:
            from agents.orchestrator import VendorRiskOrchestrator  # type: ignore[import-untyped]
        except ImportError as exc:
            error_msg = (
                f"agents.orchestrator module not found: {exc}. "
                "Make sure the agents package is installed and configured."
            )
            logger.error(error_msg, exc_info=True)
            logger.error(error_msg)
            evt = _sse_event("error", message=error_msg)
            job["progress_events"].append(evt)
            await queue.put(evt)
            job["status"] = "error"
            await queue.put(None)  # sentinel
            return

        # Create & setup orchestrator ----------------------------------------
        mcp_transport = os.getenv("MCP_TRANSPORT", "stdio")
        mcp_port = int(os.getenv("MCP_SERVER_PORT", "8081"))

        if mcp_transport == "sse":
            orchestrator = VendorRiskOrchestrator(
                mcp_server_url=f"http://localhost:{mcp_port}/sse",
            )
        else:
            orchestrator = VendorRiskOrchestrator(
                mcp_server_command=["python", "-m", "mcp_server.server"],
            )
        await orchestrator.setup()

        evt = _sse_event(
            "progress",
            message=f"Orchestrator ready. Assessing {len(vendors)} vendor(s)…",
        )
        job["progress_events"].append(evt)
        await queue.put(evt)

        # Notify per-vendor start --------------------------------------------
        for vendor in vendors:
            evt = _sse_event(
                "agent_activity",
                vendor=vendor,
                message=f"Starting assessment for {vendor}",
            )
            job["progress_events"].append(evt)
            await queue.put(evt)

        # Progress callback for real-time SSE updates ------------------------
        def _progress_cb(vendor_name: str, status: str, progress: float | None) -> None:
            cb_evt = _sse_event(
                "agent_activity",
                vendor=vendor_name,
                message=status,
                data={"progress": progress},
            )
            job["progress_events"].append(cb_evt)
            # queue.put_nowait is safe here because the queue is unbounded
            queue.put_nowait(cb_evt)

        # Run the batch assessment -------------------------------------------
        results = await orchestrator.assess_vendors_batch(
            vendors, progress_callback=_progress_cb
        )

        # Push individual result events --------------------------------------
        # results is a list[dict], one per vendor in the same order
        for report in results:
            vendor_name = report.get("vendor_name", "Unknown")
            evt = _sse_event(
                "result",
                vendor=vendor_name,
                message=f"Assessment complete for {vendor_name}",
                data=report if isinstance(report, dict) else {"raw": str(report)},
            )
            job["progress_events"].append(evt)
            await queue.put(evt)

        job["results"] = results
        job["status"] = "completed"

        # Completion event ---------------------------------------------------
        evt = _sse_event(
            "complete",
            message="All vendor assessments completed successfully.",
            data={"total_vendors": len(vendors)},
        )
        job["progress_events"].append(evt)
        await queue.put(evt)

        # Cleanup orchestrator -----------------------------------------------
        if hasattr(orchestrator, "cleanup"):
            await orchestrator.cleanup()

    except Exception as exc:
        logger.exception("Assessment job %s failed", job_id)
        job["status"] = "error"
        evt = _sse_event("error", message=str(exc))
        job["progress_events"].append(evt)
        await queue.put(evt)

    finally:
        # Push sentinel so the SSE generator knows to stop.
        await queue.put(None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main SPA dashboard."""
    try:
        return templates.TemplateResponse(request=request, name="index.html")
    except Exception as exc:
        logger.error("Failed to serve index.html: %s", exc, exc_info=True)
        # Fallback when the template hasn't been created yet.
        return HTMLResponse(
            content=(
                "<html><body>"
                "<h1>Vendor Risk Assessor</h1>"
                "<p>Frontend template not found. Place <code>index.html</code> "
                "in <code>app/templates/</code>.</p>"
                f"<p>Error: {exc}</p>"
                "</body></html>"
            ),
            status_code=200,
        )


@app.post("/api/assess", response_model=AssessResponse, status_code=202)
async def start_assessment(payload: AssessRequest) -> AssessResponse:
    """Accept a list of vendors and kick off a background assessment job.

    Returns the ``job_id`` so the client can poll or stream results.
    """
    job_id = uuid4().hex
    logger.info("Creating assessment job %s for vendors: %s", job_id, payload.vendors)

    job: dict[str, Any] = {
        "id": job_id,
        "status": "pending",
        "vendors": payload.vendors,
        "results": None,
        "progress_events": [],
        "queue": asyncio.Queue(),
    }
    jobs[job_id] = job

    # Fire-and-forget background task
    asyncio.create_task(run_assessment_job(job_id, payload.vendors))

    return AssessResponse(job_id=job_id, status="started")


@app.get("/api/assess/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Return the current status (and results if available) for a job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    response: dict[str, Any] = {
        "id": job["id"],
        "status": job["status"],
        "vendors": job["vendors"],
    }
    if job["results"] is not None:
        response["results"] = job["results"]
    return response


@app.get("/api/assess/{job_id}/stream")
async def stream_job_events(job_id: str) -> StreamingResponse:
    """Stream assessment progress via Server-Sent Events (SSE).

    The connection stays open until the job finishes or the client
    disconnects.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    queue: asyncio.Queue[str | None] = job["queue"]

    async def _event_generator():
        """Yield SSE events from the job queue."""
        # First replay any events that were already emitted before the
        # client connected.
        for past_event in list(job["progress_events"]):
            yield past_event

        # Then stream live events until sentinel (None).
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                # Send a keep-alive comment to prevent proxy timeouts.
                yield ": keep-alive\n\n"
                continue

            if event is None:
                # Sentinel — job is done.
                break
            yield event

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx compatibility
        },
    )


@app.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Lightweight health-check endpoint for load balancers & Docker."""
    return HealthResponse(status="healthy")


# ---------------------------------------------------------------------------
# Startup / Shutdown hooks
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def on_startup() -> None:
    """Run once when the ASGI server starts."""
    logger.info("Vendor Risk Assessor API is starting up…")
    logger.info("Static dir : %s (exists=%s)", STATIC_DIR, STATIC_DIR.exists())
    logger.info("Template dir: %s (exists=%s)", TEMPLATE_DIR, TEMPLATE_DIR.exists())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Cleanup resources when the server shuts down."""
    logger.info("Vendor Risk Assessor API is shutting down…")
    # Cancel any pending jobs (best-effort).
    for job_id, job in list(jobs.items()):
        if job["status"] == "running":
            logger.warning("Job %s still running during shutdown", job_id)
