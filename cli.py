#!/usr/bin/env python3
"""
cli.py — Rich terminal interface for the Automated Vendor Risk Assessor.

Assess one or more vendors from the command line with a live progress view,
per-vendor report panels, and a comparison table. The CLI uses the local
**Ollama** model (via ``AGENT_MODEL``); the web interface uses Gemini.

Usage:
    python cli.py assess "Acme Corp" "Globex" "Initech"
    python cli.py assess "Acme Corp" --json > report.json
    python cli.py assess "Acme Corp" --no-color
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import warnings
from contextlib import nullcontext
from typing import Any

from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")

# Ensure emoji / box-drawing glyphs render on legacy Windows consoles (cp1252)
# instead of raising UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# Keep the rich UI clean: suppress the INFO log flood from the agents, MCP
# server (subprocess, via MCP_LOG_LEVEL), httpx, google-adk, litellm, ddgs,
# etc. Set MCP_LOG_LEVEL / a lower level yourself if you need to debug.
os.environ.setdefault("MCP_LOG_LEVEL", "WARNING")
logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)
for _noisy in (
    "httpx", "httpcore", "primp", "google_genai", "google.adk", "google_adk",
    "LiteLLM", "litellm", "mcp", "asyncio", "urllib3", "ddgs", "duckduckgo_search",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# Agent warnings (e.g. "synthesis narrative incomplete") would disrupt the live
# progress panel; we surface that state as a tidy per-report footnote instead
# (see synthesis_method in _report_panel).
logging.getLogger("agents").setLevel(logging.ERROR)

load_dotenv()

# ---------------------------------------------------------------------------
# Rich — required for the polished UI (declared in requirements.txt)
# ---------------------------------------------------------------------------

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - graceful degradation
    _RICH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Risk styling
# ---------------------------------------------------------------------------

_RISK_STYLE: dict[str, str] = {
    "critical": "bold red",
    "high": "dark_orange3",
    "medium": "yellow3",
    "low": "green3",
    "unknown": "grey58",
}

_RISK_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "unknown": "⚪",
}


def _risk_key(report: dict[str, Any]) -> str:
    return str(
        report.get("risk_level") or report.get("overall_risk") or "unknown"
    ).lower()


def _score_of(report: dict[str, Any]) -> float:
    raw = report.get("risk_score")
    if raw is None:
        raw = report.get("overall_score", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Rich renderables
# ---------------------------------------------------------------------------


def _header() -> Panel:
    title = Text("🛡  Automated Vendor Risk Assessor", style="bold cyan")
    subtitle = Text(
        "AI-Powered Multi-Agent Cybersecurity Intelligence", style="dim italic"
    )
    return Panel(
        Align.center(Group(title, subtitle)),
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
    )


def _score_bar(score: float, level: str, width: int = 26) -> Text:
    filled = max(0, min(width, int(round(score / 100 * width))))
    style = _RISK_STYLE.get(level, "cyan")
    return Text.assemble(
        ("█" * filled, style),
        ("░" * (width - filled), "grey30"),
        (f"  {score:.0f}", "bold"),
        ("/100", "dim"),
    )


def _status_table(statuses: dict[str, tuple[str, float, str]]) -> Panel:
    """Live per-vendor progress view."""
    table = Table(box=box.SIMPLE_HEAD, expand=True, border_style="grey30")
    table.add_column("Vendor", style="bold cyan", no_wrap=True)
    table.add_column("Stage", style="white")
    table.add_column("Progress", justify="left", no_wrap=True)

    for vendor, (stage, prog, state) in statuses.items():
        pct = int(max(0.0, min(1.0, prog or 0.0)) * 100)
        width = 22
        filled = max(0, min(width, int(pct / 100 * width)))

        if state == "done":
            bar_style, icon = "green3", "[green3]✓[/]"
        elif state == "error":
            bar_style, icon = "red", "[red]✗[/]"
        else:
            bar_style, icon = "cyan", "[cyan]•[/]"

        bar = Text.assemble(
            ("█" * filled, bar_style),
            ("░" * (width - filled), "grey30"),
            (f" {pct:>3}%", "bold"),
        )
        table.add_row(f"{icon} {vendor}", stage or "…", bar)

    return Panel(
        table,
        title="[bold]Assessment Progress[/]",
        border_style="cyan",
        padding=(1, 2),
    )


def _metrics_row(metrics: dict[str, Any]) -> Table:
    grid = Table.grid(padding=(0, 3))
    grid.add_row(
        Text.assemble(("CVEs ", "dim"), (str(metrics.get("total_cves", 0)), "bold")),
        Text.assemble(
            ("Critical ", "dim"),
            (str(metrics.get("critical_count", 0)), "bold red"),
        ),
        Text.assemble(
            ("High ", "dim"),
            (str(metrics.get("high_count", 0)), "bold dark_orange3"),
        ),
        Text.assemble(
            ("Avg CVSS ", "dim"), (f"{metrics.get('avg_cvss', 0)}", "bold")
        ),
        Text.assemble(
            ("Breaches ", "dim"), (str(metrics.get("breach_count", 0)), "bold")
        ),
    )
    return grid


def _report_panel(report: dict[str, Any]) -> Panel:
    vendor = report.get("vendor_name") or report.get("vendor") or "Unknown"

    if report.get("error"):
        return Panel(
            Text(str(report["error"]), style="red"),
            title=f"[bold]{vendor}[/]",
            border_style="red",
            padding=(1, 2),
        )

    level = _risk_key(report)
    score = _score_of(report)
    style = _RISK_STYLE.get(level, "cyan")
    emoji = _RISK_EMOJI.get(level, "⚪")

    parts: list[Any] = []
    parts.append(
        Text.assemble(
            ("Risk Level   ", "dim"),
            (f"{emoji} {level.upper()}", style),
        )
    )
    risk_score_line = Text.assemble(("Risk Score   ", "dim"))
    risk_score_line.append_text(_score_bar(score, level))
    parts.append(risk_score_line)

    metrics = report.get("metrics") or {}
    if metrics:
        parts.append(Text(""))
        parts.append(_metrics_row(metrics))

    def _section(title: str, body: str) -> None:
        parts.append(Text(""))
        parts.append(Text(title, style="bold cyan"))
        parts.append(Text(str(body), style="white"))

    summary = report.get("executive_summary") or report.get("summary")
    if summary:
        _section("Executive Summary", summary)

    if report.get("cve_analysis"):
        _section("CVE & Vulnerability Analysis", report["cve_analysis"])

    if report.get("osint_analysis"):
        _section("OSINT & Threat Intelligence", report["osint_analysis"])

    recs = report.get("recommendations") or []
    if recs:
        parts.append(Text(""))
        parts.append(Text("Recommendations", style="bold cyan"))
        for i, rec in enumerate(recs, 1):
            text = (
                rec
                if isinstance(rec, str)
                else (rec.get("text") or rec.get("recommendation") or str(rec))
            )
            parts.append(Text.assemble((f"  {i}. ", "cyan"), (text, "white")))

    if report.get("synthesis_method") == "template":
        parts.append(Text(""))
        parts.append(
            Text(
                "· narrative generated from a template (local model synthesis "
                "unavailable) · score is deterministic either way",
                style="dim italic",
            )
        )

    return Panel(
        Group(*parts),
        title=f"[bold]{vendor}[/]",
        border_style=style,
        padding=(1, 2),
    )


def _summary_table(vendors: list[str], results: dict[str, Any]) -> Table:
    table = Table(
        title="Vendor Comparison",
        box=box.ROUNDED,
        border_style="cyan",
        title_style="bold cyan",
        expand=True,
    )
    table.add_column("Vendor", style="bold")
    table.add_column("Risk", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("CVEs", justify="right")
    table.add_column("Critical", justify="right")
    table.add_column("Breaches", justify="right")

    for vendor in vendors:
        report = results.get(vendor) or {}
        level = _risk_key(report)
        score = _score_of(report)
        style = _RISK_STYLE.get(level, "cyan")
        emoji = _RISK_EMOJI.get(level, "⚪")
        metrics = report.get("metrics") or {}
        crit = metrics.get("critical_count", 0)

        table.add_row(
            vendor,
            Text(f"{emoji} {level.upper()}", style=style),
            Text(f"{score:.0f}", style=style),
            str(metrics.get("total_cves", "—")),
            Text(str(crit), style="red" if crit else "white"),
            str(metrics.get("breach_count", "—")),
        )
    return table


# ---------------------------------------------------------------------------
# Health checks (doctor)
# ---------------------------------------------------------------------------


def _checks_panel(checks: list[Any]) -> Panel:
    table = Table(box=box.SIMPLE_HEAD, expand=True, border_style="grey30")
    table.add_column("", no_wrap=True)
    table.add_column("Component", style="bold", no_wrap=True)
    table.add_column("Detail", style="white")
    for check in checks:
        icon = "[green3]✓[/]" if check.ok else "[red]✗[/]"
        table.add_row(icon, check.name, check.detail)
    all_ok = all(c.ok for c in checks)
    return Panel(
        table,
        title="[bold]System Check[/]",
        subtitle="[green3]all systems go[/]" if all_ok else "[red]issues found[/]",
        border_style="green3" if all_ok else "red",
        padding=(1, 2),
    )


async def _run_doctor(*, use_color: bool) -> None:
    """Render environment & service health for both CLI (Ollama) and web (Gemini)."""
    console = Console(no_color=not use_color, highlight=False)
    from agents.preflight import run_checks

    console.print()
    console.print(_header())
    if console.is_terminal:
        with console.status("[cyan]Running checks…[/]", spinner="dots"):
            checks = await run_checks("all")
    else:
        checks = await run_checks("all")
    console.print(_checks_panel(checks))
    console.print()


# ---------------------------------------------------------------------------
# Core assessment routine
# ---------------------------------------------------------------------------


async def _run_assessment(
    vendors: list[str],
    *,
    use_color: bool,
    as_json: bool,
    output: str | None = None,
) -> None:
    """Import the orchestrator, run assessments, and render results."""
    console = Console(no_color=not use_color, highlight=False)

    if not as_json:
        console.print()
        console.print(_header())
        console.print(
            Text.assemble(
                ("  Vendors to assess:  ", "dim"),
                (", ".join(vendors), "bold cyan"),
            )
        )
        console.print()

        # Pre-flight: warn early if the local Ollama model isn't available, so
        # a silent deterministic fallback isn't mistaken for a real run.
        from agents.preflight import check_ollama

        ollama = await check_ollama()
        if not ollama.ok:
            console.print(
                Panel(
                    f"{ollama.detail}\n\n[dim]The assessment will continue but may "
                    f"fall back to deterministic scoring only.[/]",
                    title="[bold yellow]⚠ Ollama check[/]",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )
            console.print()

    # Lazy-import so CLI usage errors surface before heavy imports.
    try:
        from agents.orchestrator import VendorRiskOrchestrator  # type: ignore[import-untyped]
    except ImportError:
        console.print(
            Panel(
                "agents.orchestrator not found.\n"
                "Ensure the agents package is installed.",
                title="[bold red]Error[/]",
                border_style="red",
            )
        )
        sys.exit(1)

    import os

    mcp_transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    mcp_port = int(os.getenv("MCP_SERVER_PORT", "8081"))

    # CLI stays on the local Ollama model (AGENT_MODEL) — orchestrator resolves
    # model=None via the model factory, which reads AGENT_MODEL.
    if mcp_transport == "sse":
        orchestrator = VendorRiskOrchestrator(
            mcp_server_url=f"http://localhost:{mcp_port}/sse",
        )
    else:
        orchestrator = VendorRiskOrchestrator(
            mcp_server_command=[sys.executable, "-m", "mcp_server.server"],
        )

    await orchestrator.setup()

    # ── Live progress ───────────────────────────────────────────────────
    statuses: dict[str, tuple[str, float, str]] = {
        v: ("Queued…", 0.0, "run") for v in vendors
    }

    def _callback(vendor: str, status: str, progress: float | None) -> None:
        prev = statuses.get(vendor, ("", 0.0, "run"))
        prog = progress if progress is not None else prev[1]
        state = prev[2]
        if prog is not None and prog >= 1.0:
            state = "done"
        if status and "complete" in status.lower():
            state = "done"
        statuses[vendor] = (status or prev[0], prog, state)
        if _live is not None:
            _live.update(_status_table(statuses))

    use_live = console.is_terminal and not as_json
    _live: Live | None = None

    try:
        if use_live:
            with Live(
                _status_table(statuses),
                console=console,
                refresh_per_second=8,
            ) as live:
                _live = live
                results_list: list[dict[str, Any]] = (
                    await orchestrator.assess_vendors_batch(
                        vendors, progress_callback=_callback
                    )
                )
                _live = None
        else:
            if not as_json:
                console.print(
                    "[dim]Assessing… (local models can take a while)[/]"
                )
            results_list = await orchestrator.assess_vendors_batch(
                vendors, progress_callback=_callback
            )
    finally:
        if hasattr(orchestrator, "cleanup"):
            await orchestrator.cleanup()

    # ── Normalise results into a vendor-keyed dict ──────────────────────
    results: dict[str, Any] = {}
    if isinstance(results_list, list):
        for i, report in enumerate(results_list):
            if isinstance(report, dict):
                key = report.get(
                    "vendor_name", vendors[i] if i < len(vendors) else f"Vendor {i + 1}"
                )
            else:
                key = vendors[i] if i < len(vendors) else f"Vendor {i + 1}"
            results[key] = report
    elif isinstance(results_list, dict):
        results = results_list

    # ── Optional export to file (Markdown or JSON by extension) ─────────
    if output:
        report_list = results_list if isinstance(results_list, list) else list(results.values())
        from app.exporters import reports_to_json, reports_to_markdown

        if output.lower().endswith((".md", ".markdown")):
            text = reports_to_markdown(report_list)
        else:
            text = reports_to_json(report_list)
        try:
            with open(output, "w", encoding="utf-8") as fh:
                fh.write(text)
            if not as_json:
                console.print(f"[green3]✓[/] Report written to [bold]{output}[/]")
                console.print()
        except OSError as exc:
            console.print(f"[red]✗ Could not write {output}: {exc}[/]")

    # ── JSON output mode ────────────────────────────────────────────────
    if as_json:
        print(json.dumps(results_list, indent=2, default=str))
        return

    # ── Rendered output ─────────────────────────────────────────────────
    console.print()
    if not results:
        console.print(
            Panel("No results returned.", title="[bold red]Error[/]", border_style="red")
        )
        return

    for vendor in vendors:
        report = results.get(vendor)
        if report is None:
            console.print(
                Panel(
                    "No report generated.",
                    title=f"[bold]{vendor}[/]",
                    border_style="red",
                )
            )
            continue
        if isinstance(report, dict):
            console.print(_report_panel(report))
        else:
            console.print(Panel(str(report), title=f"[bold]{vendor}[/]"))
        console.print()

    console.print(_summary_table(vendors, results))
    console.print()


# ---------------------------------------------------------------------------
# Plain fallback (only if rich is unavailable)
# ---------------------------------------------------------------------------


async def _run_assessment_plain(vendors: list[str], *, as_json: bool) -> None:
    from agents.orchestrator import VendorRiskOrchestrator

    import os

    mcp_transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    mcp_port = int(os.getenv("MCP_SERVER_PORT", "8081"))
    if mcp_transport == "sse":
        orchestrator = VendorRiskOrchestrator(
            mcp_server_url=f"http://localhost:{mcp_port}/sse"
        )
    else:
        orchestrator = VendorRiskOrchestrator(
            mcp_server_command=[sys.executable, "-m", "mcp_server.server"]
        )
    await orchestrator.setup()
    print("Assessing vendors… (install 'rich' for the full UI)")
    try:
        results_list = await orchestrator.assess_vendors_batch(vendors)
    finally:
        if hasattr(orchestrator, "cleanup"):
            await orchestrator.cleanup()

    if as_json:
        print(json.dumps(results_list, indent=2, default=str))
        return

    for report in results_list:
        if not isinstance(report, dict):
            continue
        name = report.get("vendor_name", "Unknown")
        level = str(report.get("risk_level", "UNKNOWN"))
        score = _score_of(report)
        print(f"\n=== {name} ===")
        print(f"Risk: {level}  Score: {score:.0f}/100")
        if report.get("executive_summary"):
            print(report["executive_summary"])


# ---------------------------------------------------------------------------
# Argument parsing & main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vendor-risk-cli",
        description="Automated Vendor Risk Assessor — CLI (local Ollama model)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    assess = sub.add_parser("assess", help="Assess one or more vendors")
    assess.add_argument("vendors", nargs="+", help="Vendor name(s) to assess")
    assess.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable coloured output",
    )
    assess.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON to stdout (implies no UI)",
    )
    assess.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the report to a file (.md → Markdown, otherwise JSON)",
    )

    sub.add_parser(
        "doctor",
        help="Check Ollama / Gemini / NVD / search configuration & connectivity",
    )
    return parser


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate handler."""
    parser = _build_parser()
    args = parser.parse_args()

    use_color = sys.stdout.isatty()

    if args.command == "doctor":
        if not _RICH_AVAILABLE:
            print("The 'doctor' command requires the 'rich' package.", file=sys.stderr)
            sys.exit(1)
        try:
            asyncio.run(_run_doctor(use_color=use_color))
        except KeyboardInterrupt:
            sys.exit(130)
        return

    if args.command != "assess":
        parser.print_help()
        return

    use_color = use_color and not args.no_color

    try:
        if _RICH_AVAILABLE:
            asyncio.run(
                _run_assessment(
                    args.vendors,
                    use_color=use_color,
                    as_json=args.json,
                    output=args.output,
                )
            )
        else:
            asyncio.run(_run_assessment_plain(args.vendors, as_json=args.json))
    except KeyboardInterrupt:
        print("\n\n  Assessment cancelled by user.\n", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
