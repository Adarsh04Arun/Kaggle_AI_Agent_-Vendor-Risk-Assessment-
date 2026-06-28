#!/usr/bin/env python3
"""
cli.py — Terminal interface for the Automated Vendor Risk Assessor.

Assess one or more vendors from the command line with coloured output
and a live progress indicator.

Usage:
    python cli.py assess "Acme Corp" "Globex" "Initech"
    python cli.py assess vendor1 vendor2 --no-color
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_COLORS: dict[str, str] = {
    "critical": "\033[91m",   # bright red
    "high":     "\033[31m",   # red
    "medium":   "\033[33m",   # yellow
    "low":      "\033[32m",   # green
    "info":     "\033[36m",   # cyan
    "header":   "\033[94m",   # bright blue
    "success":  "\033[92m",   # bright green
    "error":    "\033[91m",   # bright red
}


def _c(text: str, style: str, *, use_color: bool = True) -> str:
    """Wrap *text* in ANSI colour codes if colour is enabled."""
    if not use_color:
        return text
    code = _COLORS.get(style, "")
    return f"{code}{text}{_RESET}" if code else text


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

_RISK_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "unknown": "⚪",
}


def _risk_bar(score: float, width: int = 20) -> str:
    """Render a simple text progress-bar for a 0-100 risk score."""
    filled = min(int(score / 100 * width), width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {score:.1f}/100"


def _print_divider(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _print_report(vendor: str, report: dict[str, Any], *, use_color: bool) -> None:
    """Pretty-print a single vendor assessment report."""
    _print_divider("═")
    print(f"  {_c(vendor, 'header', use_color=use_color)}")
    _print_divider("─")

    risk_level: str = str(report.get("risk_level", report.get("overall_risk", "unknown"))).lower()
    risk_score: float = float(report.get("risk_score", report.get("overall_score", 0)))
    emoji = _RISK_EMOJI.get(risk_level, "⚪")

    print(f"  Risk Level : {emoji}  {_c(risk_level.upper(), risk_level, use_color=use_color)}")
    print(f"  Risk Score : {_risk_bar(risk_score)}")

    # Summary
    summary = report.get("summary", report.get("executive_summary", ""))
    if summary:
        print(f"\n  {_BOLD}Summary{_RESET}")
        # Wrap long summaries to ~68 chars.
        for line in _wrap(str(summary), 68):
            print(f"    {line}")

    # Key findings / vulnerabilities
    findings = report.get("findings", report.get("vulnerabilities", []))
    if findings:
        print(f"\n  {_BOLD}Key Findings{_RESET}")
        for i, finding in enumerate(findings[:10], 1):
            if isinstance(finding, dict):
                label = finding.get("title", finding.get("id", f"Finding {i}"))
                severity = str(finding.get("severity", "info")).lower()
                print(f"    {i}. {_c(label, severity, use_color=use_color)}")
            else:
                print(f"    {i}. {finding}")

    # Recommendations
    recs = report.get("recommendations", [])
    if recs:
        print(f"\n  {_BOLD}Recommendations{_RESET}")
        for i, rec in enumerate(recs[:5], 1):
            print(f"    {i}. {rec}")

    print()


def _wrap(text: str, width: int) -> list[str]:
    """Naïve word-wrap."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if length + len(word) + 1 > width and current:
            lines.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += len(word) + 1
    if current:
        lines.append(" ".join(current))
    return lines


# ---------------------------------------------------------------------------
# Progress dots
# ---------------------------------------------------------------------------


async def _show_progress(stop_event: asyncio.Event) -> None:
    """Print dots while the assessment is running."""
    sys.stdout.write("  Assessing vendors ")
    sys.stdout.flush()
    while not stop_event.is_set():
        sys.stdout.write(".")
        sys.stdout.flush()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
    sys.stdout.write(" done!\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Core assessment routine
# ---------------------------------------------------------------------------


async def _run_assessment(vendors: list[str], *, use_color: bool) -> None:
    """Import the orchestrator, run assessments, and display results."""

    print()
    print(
        _c("  ╔══════════════════════════════════════════════════════╗", "header", use_color=use_color)
    )
    print(
        _c("  ║       Automated Vendor Risk Assessor — CLI          ║", "header", use_color=use_color)
    )
    print(
        _c("  ╚══════════════════════════════════════════════════════╝", "header", use_color=use_color)
    )
    print()
    print(f"  Vendors to assess: {', '.join(vendors)}")
    print()

    # Lazy-import the orchestrator so CLI usage errors are surfaced before
    # heavy imports.
    try:
        from agents.orchestrator import VendorRiskOrchestrator  # type: ignore[import-untyped]
    except ImportError:
        print(
            _c(
                "  ERROR: agents.orchestrator not found.\n"
                "  Ensure the agents package is installed.\n",
                "error",
                use_color=use_color,
            )
        )
        sys.exit(1)

    import os

    mcp_transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    mcp_port = int(os.getenv("MCP_SERVER_PORT", "8081"))

    if mcp_transport == "sse":
        orchestrator = VendorRiskOrchestrator(
            mcp_server_url=f"http://localhost:{mcp_port}/sse",
        )
    else:
        orchestrator = VendorRiskOrchestrator(
            mcp_server_command=[sys.executable, "-m", "mcp_server.server"],
        )

    await orchestrator.setup()

    # Start progress indicator
    stop = asyncio.Event()
    progress_task = asyncio.create_task(_show_progress(stop))

    try:
        results_list: list[dict[str, Any]] = await orchestrator.assess_vendors_batch(vendors)
    finally:
        stop.set()
        await progress_task

    # Cleanup
    if hasattr(orchestrator, "cleanup"):
        await orchestrator.cleanup()

    # Convert list of reports to a dict keyed by vendor name
    results: dict[str, Any] = {}
    if isinstance(results_list, list):
        for i, report in enumerate(results_list):
            if isinstance(report, dict):
                key = report.get("vendor_name", vendors[i] if i < len(vendors) else f"Vendor {i+1}")
            else:
                key = vendors[i] if i < len(vendors) else f"Vendor {i+1}"
            results[key] = report
    elif isinstance(results_list, dict):
        results = results_list

    # Display results
    print()
    print(_c("  Assessment Results", "header", use_color=use_color))
    _print_divider()

    if not results:
        print(_c("  No results returned.", "error", use_color=use_color))
        return

    for vendor in vendors:
        report = results.get(vendor)
        if report is None:
            print(f"\n  {_c(vendor, 'error', use_color=use_color)}: No report generated.\n")
            continue
        if isinstance(report, dict):
            _print_report(vendor, report, use_color=use_color)
        else:
            print(f"\n  {vendor}: {report}\n")

    # Summary table
    _print_divider("═")
    print(f"  {'VENDOR':<30} {'RISK LEVEL':<15} {'SCORE':<10}")
    _print_divider("─")
    for vendor in vendors:
        report = results.get(vendor, {})
        if isinstance(report, dict):
            level = str(report.get("risk_level", report.get("overall_risk", "unknown"))).lower()
            score = float(report.get("risk_score", report.get("overall_score", 0)))
            emoji = _RISK_EMOJI.get(level, "⚪")
            level_str = _c(f"{emoji} {level.upper()}", level, use_color=use_color)
            print(f"  {vendor:<30} {level_str:<25} {score:.1f}/100")
        else:
            print(f"  {vendor:<30} {'N/A':<15} {'N/A':<10}")
    _print_divider("═")
    print()


# ---------------------------------------------------------------------------
# Argument parsing & main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vendor-risk-cli",
        description="Automated Vendor Risk Assessor — CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    assess = sub.add_parser("assess", help="Assess one or more vendors")
    assess.add_argument(
        "vendors",
        nargs="+",
        help="Vendor name(s) to assess",
    )
    assess.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable coloured output",
    )
    return parser


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate handler."""
    parser = _build_parser()
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()

    if args.command == "assess":
        try:
            asyncio.run(_run_assessment(args.vendors, use_color=use_color))
        except KeyboardInterrupt:
            print(
                _c("\n\n  Assessment cancelled by user.\n", "error", use_color=use_color)
            )
            sys.exit(130)


if __name__ == "__main__":
    main()
