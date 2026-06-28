#!/usr/bin/env python3
"""
run.py — Main entry-point for the Automated Vendor Risk Assessor.

Boots the FastAPI application via Uvicorn, optionally launching the
MCP tool-server as a managed subprocess when MCP_TRANSPORT=stdio.

Usage:
    python run.py                     # defaults: 0.0.0.0:8080
    python run.py --host 127.0.0.1 --port 9000 --debug
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import signal
import subprocess
import sys
from typing import Optional

import uvicorn
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run")

# ---------------------------------------------------------------------------
# MCP subprocess management
# ---------------------------------------------------------------------------

_mcp_process: Optional[subprocess.Popen] = None  # noqa: UP007


def _start_mcp_server(port: int) -> subprocess.Popen:
    """Launch the MCP tool server as a child process.

    Args:
        port: TCP port for the MCP SSE transport.

    Returns:
        The :class:`subprocess.Popen` handle.
    """
    cmd = [
        sys.executable,
        "-m",
        "mcp_server.server",
        "--transport",
        "stdio",
        "--port",
        str(port),
    ]
    logger.info("Starting MCP server: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    logger.info("MCP server started (PID %d)", proc.pid)
    return proc


def _stop_mcp_server() -> None:
    """Terminate the MCP subprocess if it is still running."""
    global _mcp_process
    if _mcp_process is not None and _mcp_process.poll() is None:
        logger.info("Stopping MCP server (PID %d)…", _mcp_process.pid)
        _mcp_process.terminate()
        try:
            _mcp_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("MCP server did not exit gracefully — killing.")
            _mcp_process.kill()
        _mcp_process = None


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------


def _handle_signal(signum: int, _frame) -> None:  # noqa: ANN001
    """Graceful shutdown on SIGINT / SIGTERM."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — shutting down…", sig_name)
    _stop_mcp_server()
    sys.exit(0)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Vendor Risk Assessor server.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "0.0.0.0"),
        help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8080")),
        help="Listen port (default: 8080)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.getenv("DEBUG", "false").lower() == "true",
        help="Enable debug / hot-reload mode",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments, optionally start MCP, then run Uvicorn."""
    global _mcp_process

    args = _parse_args()

    # Register cleanup handlers
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    atexit.register(_stop_mcp_server)

    # Optionally start the MCP tool-server
    mcp_transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if mcp_transport == "stdio":
        mcp_port = int(os.getenv("MCP_SERVER_PORT", "8081"))
        try:
            _mcp_process = _start_mcp_server(mcp_port)
        except FileNotFoundError:
            logger.warning(
                "MCP server module not found — continuing without it. "
                "Install the mcp_server package or set MCP_TRANSPORT=sse "
                "to use an external MCP server."
            )

    # Run the ASGI server
    logger.info(
        "Starting Vendor Risk Assessor on http://%s:%d (debug=%s)",
        args.host,
        args.port,
        args.debug,
    )

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.debug,
        log_level="debug" if args.debug else "info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
