"""
app/exporters.py — Deterministic report exporters (JSON / Markdown).

Pure Python, no LLM involvement: these render data that has already been
computed, so they can never hallucinate. Shared by the CLI (``--output``) and
the web download endpoint.
"""

from __future__ import annotations

import json
from typing import Any


def _score(report: dict[str, Any]) -> float:
    raw = report.get("risk_score")
    if raw is None:
        raw = report.get("overall_score", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def report_to_markdown(report: dict[str, Any]) -> str:
    """Render a single vendor report as a Markdown section."""
    vendor = report.get("vendor_name") or report.get("vendor") or "Unknown"
    level = str(report.get("risk_level", "UNKNOWN")).upper()
    score = _score(report)

    lines: list[str] = [f"## {vendor} — {level} ({score:.0f}/100)", ""]

    if report.get("error"):
        lines += [f"> **Error:** {report['error']}", ""]
        return "\n".join(lines)

    metrics = report.get("metrics") or {}
    if metrics:
        lines += [
            "**Metrics:** "
            + " · ".join(
                [
                    f"CVEs {metrics.get('total_cves', 0)}",
                    f"Critical {metrics.get('critical_count', 0)}",
                    f"High {metrics.get('high_count', 0)}",
                    f"Avg CVSS {metrics.get('avg_cvss', 0)}",
                    f"Breaches {metrics.get('breach_count', 0)}",
                ]
            ),
            "",
        ]

    summary = report.get("executive_summary") or report.get("summary")
    if summary:
        lines += ["**Executive Summary**", "", str(summary), ""]

    if report.get("cve_analysis"):
        lines += ["**CVE & Vulnerability Analysis**", "", str(report["cve_analysis"]), ""]

    if report.get("osint_analysis"):
        lines += ["**OSINT & Threat Intelligence**", "", str(report["osint_analysis"]), ""]

    recs = report.get("recommendations") or []
    if recs:
        lines += ["**Recommendations**", ""]
        for i, rec in enumerate(recs, 1):
            text = (
                rec
                if isinstance(rec, str)
                else (rec.get("text") or rec.get("recommendation") or str(rec))
            )
            lines.append(f"{i}. {text}")
        lines.append("")

    if report.get("assessed_at"):
        lines += [f"_Assessed at: {report['assessed_at']}_", ""]

    return "\n".join(lines)


def reports_to_markdown(reports: list[dict[str, Any]]) -> str:
    """Render a batch of reports as a single Markdown document."""
    parts = ["# Vendor Risk Assessment", ""]
    if reports:
        parts += ["| Vendor | Risk | Score | CVEs | Critical | Breaches |", "|---|---|---:|---:|---:|---:|"]
        for r in reports:
            m = r.get("metrics") or {}
            parts.append(
                f"| {r.get('vendor_name', 'Unknown')} "
                f"| {str(r.get('risk_level', 'UNKNOWN')).upper()} "
                f"| {_score(r):.0f} "
                f"| {m.get('total_cves', '—')} "
                f"| {m.get('critical_count', 0)} "
                f"| {m.get('breach_count', '—')} |"
            )
        parts.append("")
    for report in reports:
        parts.append(report_to_markdown(report))
    return "\n".join(parts)


def reports_to_json(reports: list[dict[str, Any]]) -> str:
    """Render a batch of reports as pretty JSON."""
    return json.dumps(reports, indent=2, default=str)
