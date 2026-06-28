"""
Deterministic Risk Scoring Engine for Vendor Risk Assessment.

Provides a weighted multi-factor scoring algorithm that converts raw CVE and OSINT
data into a normalized 0-100 risk score with categorical risk levels, color coding,
detailed breakdowns, and actionable recommendations.

Scoring Factors & Weights:
    - CVE Count Critical (30%): Measures volume of critical-severity vulnerabilities
    - CVE Count High (20%): Measures volume of high-severity vulnerabilities
    - Average CVSS Score (15%): Linear scale of mean CVSS across all CVEs
    - Recent Breaches (20%): Count of known data breaches
    - Breach Recency (10%): How recently the most recent breach occurred
    - Compliance Issues (5%): Presence of regulatory/compliance failures
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class RiskScorer:
    """Deterministic risk scoring engine for vendor security assessments.

    Converts raw CVE and OSINT intelligence into a normalized risk score
    using a weighted multi-factor algorithm. The scoring is fully deterministic—
    identical inputs always produce identical outputs.

    Example:
        >>> scorer = RiskScorer()
        >>> result = scorer.calculate_risk_score(cve_data, osint_data)
        >>> print(f"{result['risk_level']}: {result['overall_score']:.1f}")
        HIGH: 67.5
    """

    # ── Weight Configuration ────────────────────────────────────────────
    WEIGHTS: dict[str, float] = {
        "cve_critical": 0.30,
        "cve_high": 0.20,
        "avg_cvss": 0.15,
        "recent_breaches": 0.20,
        "breach_recency": 0.10,
        "compliance_issues": 0.05,
    }

    # ── Risk Level Thresholds ───────────────────────────────────────────
    RISK_LEVELS: list[tuple[float, str, str]] = [
        (25.0, "LOW", "#22c55e"),
        (50.0, "MEDIUM", "#eab308"),
        (75.0, "HIGH", "#f97316"),
        (100.0, "CRITICAL", "#ef4444"),
    ]

    def calculate_risk_score(
        self,
        cve_data: dict[str, Any],
        osint_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate a deterministic risk score from CVE and OSINT data.

        Args:
            cve_data: CVE findings dict. Expected keys include
                ``critical_count``, ``high_count``, ``avg_cvss_score``.
            osint_data: OSINT findings dict. Expected keys include
                ``breach_count``, ``most_recent_breach_year``,
                ``compliance_issues``.

        Returns:
            A dict containing:
                - ``overall_score`` (float): Composite score 0–100.
                - ``risk_level`` (str): One of LOW / MEDIUM / HIGH / CRITICAL.
                - ``risk_color`` (str): Hex colour string for the risk level.
                - ``breakdown`` (dict): Per-factor score and weight.
                - ``summary`` (str): Human-readable summary string.
        """
        cve_data = cve_data or {}
        osint_data = osint_data or {}

        # ── Individual factor scores ────────────────────────────────────
        critical_score = self._score_cve_critical(
            int(cve_data.get("critical_count", 0))
        )
        high_score = self._score_cve_high(
            int(cve_data.get("high_count", 0))
        )
        cvss_score = self._score_avg_cvss(
            float(cve_data.get("avg_cvss_score", 0.0))
        )
        breach_score = self._score_recent_breaches(
            int(osint_data.get("breach_count", 0))
        )
        recency_score = self._score_breach_recency(
            osint_data.get("most_recent_breach_year")
        )
        compliance_score = self._score_compliance_issues(
            osint_data.get("compliance_issues", [])
        )

        # ── Weighted composite ──────────────────────────────────────────
        overall = (
            critical_score * self.WEIGHTS["cve_critical"]
            + high_score * self.WEIGHTS["cve_high"]
            + cvss_score * self.WEIGHTS["avg_cvss"]
            + breach_score * self.WEIGHTS["recent_breaches"]
            + recency_score * self.WEIGHTS["breach_recency"]
            + compliance_score * self.WEIGHTS["compliance_issues"]
        )
        overall = round(min(max(overall, 0.0), 100.0), 2)

        risk_level, risk_color = self._classify_risk(overall)

        breakdown = {
            "cve_critical": {
                "score": critical_score,
                "weight": self.WEIGHTS["cve_critical"],
                "weighted_score": round(
                    critical_score * self.WEIGHTS["cve_critical"], 2
                ),
                "description": "Critical-severity CVE count",
            },
            "cve_high": {
                "score": high_score,
                "weight": self.WEIGHTS["cve_high"],
                "weighted_score": round(
                    high_score * self.WEIGHTS["cve_high"], 2
                ),
                "description": "High-severity CVE count",
            },
            "avg_cvss": {
                "score": cvss_score,
                "weight": self.WEIGHTS["avg_cvss"],
                "weighted_score": round(
                    cvss_score * self.WEIGHTS["avg_cvss"], 2
                ),
                "description": "Average CVSS score",
            },
            "recent_breaches": {
                "score": breach_score,
                "weight": self.WEIGHTS["recent_breaches"],
                "weighted_score": round(
                    breach_score * self.WEIGHTS["recent_breaches"], 2
                ),
                "description": "Recent data breach count",
            },
            "breach_recency": {
                "score": recency_score,
                "weight": self.WEIGHTS["breach_recency"],
                "weighted_score": round(
                    recency_score * self.WEIGHTS["breach_recency"], 2
                ),
                "description": "Breach recency",
            },
            "compliance_issues": {
                "score": compliance_score,
                "weight": self.WEIGHTS["compliance_issues"],
                "weighted_score": round(
                    compliance_score * self.WEIGHTS["compliance_issues"], 2
                ),
                "description": "Compliance / regulatory issues",
            },
        }

        summary = (
            f"Vendor risk score: {overall}/100 ({risk_level}). "
            f"Found {cve_data.get('critical_count', 0)} critical and "
            f"{cve_data.get('high_count', 0)} high CVEs "
            f"(avg CVSS {cve_data.get('avg_cvss_score', 0.0):.1f}). "
            f"{osint_data.get('breach_count', 0)} breach(es) on record. "
            f"{'Compliance issues detected.' if compliance_score > 0 else 'No compliance issues found.'}"
        )

        logger.info("Risk score calculated: %.2f (%s)", overall, risk_level)

        return {
            "overall_score": overall,
            "risk_level": risk_level,
            "risk_color": risk_color,
            "breakdown": breakdown,
            "summary": summary,
        }

    # ── Factor scoring helpers ──────────────────────────────────────────

    @staticmethod
    def _score_cve_critical(count: int) -> float:
        """Score critical-severity CVE count (0-100).

        Thresholds: 0→0, 1-2→40, 3-5→70, 6+→100.
        """
        if count <= 0:
            return 0.0
        if count <= 2:
            return 40.0
        if count <= 5:
            return 70.0
        return 100.0

    @staticmethod
    def _score_cve_high(count: int) -> float:
        """Score high-severity CVE count (0-100).

        Thresholds: 0→0, 1-3→40, 4-7→70, 8+→100.
        """
        if count <= 0:
            return 0.0
        if count <= 3:
            return 40.0
        if count <= 7:
            return 70.0
        return 100.0

    @staticmethod
    def _score_avg_cvss(avg_cvss: float) -> float:
        """Score average CVSS on a linear 0-100 scale.

        Formula: (avg_cvss / 10) * 100, clamped to [0, 100].
        """
        return round(min(max((avg_cvss / 10.0) * 100.0, 0.0), 100.0), 2)

    @staticmethod
    def _score_recent_breaches(count: int) -> float:
        """Score breach count (0-100).

        Thresholds: 0→0, 1→50, 2→75, 3+→100.
        """
        if count <= 0:
            return 0.0
        if count == 1:
            return 50.0
        if count == 2:
            return 75.0
        return 100.0

    @staticmethod
    def _score_breach_recency(
        most_recent_breach_year: int | str | None,
    ) -> float:
        """Score breach recency (0-100).

        Thresholds based on years since breach:
            none → 0, 3+ years → 25, 1-3 years → 60, <1 year → 100.
        """
        if most_recent_breach_year is None:
            return 0.0

        try:
            breach_year = int(most_recent_breach_year)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid breach year value: %s", most_recent_breach_year
            )
            return 0.0

        current_year = datetime.now(timezone.utc).year
        years_ago = current_year - breach_year

        if years_ago < 0:
            # Future year — treat as very recent
            return 100.0
        if years_ago < 1:
            return 100.0
        if years_ago <= 3:
            return 60.0
        return 25.0

    @staticmethod
    def _score_compliance_issues(
        issues: list[Any] | int | None,
    ) -> float:
        """Score compliance issues (0-100).

        Binary: 0 issues → 0, 1+ issues → 100.
        """
        if issues is None:
            return 0.0
        if isinstance(issues, int):
            return 100.0 if issues > 0 else 0.0
        if isinstance(issues, list):
            return 100.0 if len(issues) > 0 else 0.0
        return 0.0

    # ── Classification ──────────────────────────────────────────────────

    @classmethod
    def _classify_risk(cls, score: float) -> tuple[str, str]:
        """Map a 0-100 score to a risk level label and colour.

        Returns:
            Tuple of (risk_level, risk_color).
        """
        for threshold, level, color in cls.RISK_LEVELS:
            if score <= threshold:
                return level, color
        # Fallback (score > 100, shouldn't happen after clamping)
        return "CRITICAL", "#ef4444"


def generate_recommendations(
    score_data: dict[str, Any],
    cve_data: dict[str, Any],
    osint_data: dict[str, Any],
) -> list[str]:
    """Generate actionable security recommendations based on assessment findings.

    Examines the risk score breakdown, CVE data, and OSINT data to produce a
    prioritised list of human-readable recommendations.

    Args:
        score_data: Output of ``RiskScorer.calculate_risk_score()``.
        cve_data: CVE findings dict.
        osint_data: OSINT findings dict.

    Returns:
        A list of recommendation strings, ordered by priority (most urgent first).
    """
    cve_data = cve_data or {}
    osint_data = osint_data or {}
    score_data = score_data or {}

    recommendations: list[str] = []
    risk_level = score_data.get("risk_level", "LOW")

    # ── Critical-level overall posture ──────────────────────────────────
    if risk_level == "CRITICAL":
        recommendations.append(
            "URGENT: Initiate immediate vendor risk review and consider "
            "suspending data sharing until vulnerabilities are remediated."
        )
    elif risk_level == "HIGH":
        recommendations.append(
            "Schedule a priority vendor security review within 30 days and "
            "request a formal remediation plan."
        )

    # ── CVE-driven recommendations ──────────────────────────────────────
    critical_count = int(cve_data.get("critical_count", 0))
    high_count = int(cve_data.get("high_count", 0))
    avg_cvss = float(cve_data.get("avg_cvss_score", 0.0))

    if critical_count > 0:
        recommendations.append(
            f"Request immediate patching status for {critical_count} critical "
            f"CVE(s). Verify the vendor has an active patch management programme."
        )

    if high_count > 5:
        recommendations.append(
            f"The vendor has {high_count} high-severity CVEs. Request a "
            f"vulnerability management report and evidence of remediation timelines."
        )
    elif high_count > 0:
        recommendations.append(
            f"Monitor remediation progress for {high_count} high-severity CVE(s). "
            f"Request patch ETAs."
        )

    if avg_cvss >= 7.0:
        recommendations.append(
            f"Average CVSS score is {avg_cvss:.1f}/10. Implement additional "
            f"compensating controls (network segmentation, enhanced monitoring) "
            f"until the vendor remediates."
        )

    # ── Breach-driven recommendations ───────────────────────────────────
    breach_count = int(osint_data.get("breach_count", 0))
    most_recent = osint_data.get("most_recent_breach_year")

    if breach_count >= 3:
        recommendations.append(
            f"The vendor has experienced {breach_count} known breaches. "
            f"Require a third-party security audit (e.g. SOC 2 Type II) before "
            f"renewing contracts."
        )
    elif breach_count > 0:
        recommendations.append(
            f"The vendor has {breach_count} breach(es) on record. Request "
            f"their incident response report and post-breach remediation evidence."
        )

    if most_recent is not None:
        try:
            years_ago = datetime.now(timezone.utc).year - int(most_recent)
            if years_ago < 1:
                recommendations.append(
                    "A breach occurred within the past year. Require evidence "
                    "of completed remediation and enhanced security controls."
                )
            elif years_ago <= 2:
                recommendations.append(
                    "A breach occurred in the past 2 years. Verify that all "
                    "post-breach corrective actions have been fully implemented."
                )
        except (ValueError, TypeError):
            pass

    # ── Compliance-driven recommendations ───────────────────────────────
    compliance_issues = osint_data.get("compliance_issues", [])
    has_compliance_issues = (
        (isinstance(compliance_issues, list) and len(compliance_issues) > 0)
        or (isinstance(compliance_issues, int) and compliance_issues > 0)
    )

    if has_compliance_issues:
        recommendations.append(
            "Compliance issues detected. Request copies of current compliance "
            "certifications (SOC 2, ISO 27001, GDPR DPA) and any corrective "
            "action plans."
        )

    # ── Security-incident-driven recommendations ────────────────────────
    security_incidents = osint_data.get("security_incidents", [])
    if isinstance(security_incidents, list) and len(security_incidents) > 0:
        recommendations.append(
            f"{len(security_incidents)} security incident(s) found in OSINT. "
            f"Review each incident for potential impact on your data and services."
        )

    # ── Generic best-practice recommendations ──────────────────────────
    if risk_level in ("LOW", "MEDIUM"):
        recommendations.append(
            "Continue routine monitoring. Schedule the next vendor risk "
            "assessment in 12 months."
        )
    else:
        recommendations.append(
            "Increase monitoring frequency and schedule a follow-up assessment "
            "in 90 days."
        )

    recommendations.append(
        "Ensure contractual provisions include security SLAs, breach "
        "notification requirements, and right-to-audit clauses."
    )

    logger.info("Generated %d recommendations", len(recommendations))
    return recommendations
