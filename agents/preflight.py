"""
agents/preflight.py — Environment & service health checks.

Used by the CLI (``python cli.py doctor`` and a pre-flight warning before an
assessment) and the web ``/api/status`` endpoint to make the model's health
*visible* instead of letting a silent fallback masquerade as a real run.

The split matters:
    * CLI  → local **Ollama** (checked via ``AGENT_MODEL`` + ``OLLAMA_BASE_URL``)
    * Web  → **Gemini** (checked via ``GOOGLE_API_KEY`` + ``WEB_AGENT_MODEL``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from agents.model_factory import resolve_model_name


@dataclass
class Check:
    """Result of a single health check."""

    name: str
    ok: bool
    detail: str


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


async def _check_ollama_model(model: str, label: str, timeout: float = 4.0) -> Check:
    """Verify the local Ollama server is up and *model* is pulled."""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    tag = model.split("/", 1)[1]  # strip the ollama_chat/ prefix
    tag_base = tag.split(":")[0]

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - report any failure to the user
        return Check(
            label,
            False,
            f"unreachable at {base} ({exc.__class__.__name__}) — "
            f"is 'ollama serve' running?",
        )

    names = [m.get("name", "") for m in data.get("models", [])]
    pulled = any(n == tag or n.split(":")[0] == tag_base for n in names)
    if pulled:
        return Check(label, True, f"reachable · model '{tag}' pulled")
    return Check(
        label,
        False,
        f"reachable but '{tag}' not pulled — run: ollama pull {tag_base}",
    )


async def check_ollama(timeout: float = 4.0) -> Check:
    """Verify the CLI's local Ollama model (``AGENT_MODEL``) is available."""
    model = resolve_model_name()  # honours AGENT_MODEL (the CLI's model)
    if not model.startswith(("ollama_chat/", "ollama/")):
        return Check("Ollama (CLI)", True, f"not used — AGENT_MODEL={model}")
    return await _check_ollama_model(model, "Ollama (CLI)", timeout)


def check_gemini() -> Check:
    """Verify the web interface's Gemini credentials are present."""
    web_model = os.getenv("WEB_AGENT_MODEL", "gemini-2.0-flash-lite")
    if not web_model.startswith("gemini"):
        return Check("Gemini (web)", True, f"not used — WEB_AGENT_MODEL={web_model}")

    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if key:
        return Check("Gemini (web)", True, f"GOOGLE_API_KEY set · model {web_model}")
    return Check(
        "Gemini (web)",
        False,
        "GOOGLE_API_KEY missing — the web interface needs it",
    )


async def check_web() -> Check:
    """Check whichever provider the **web** interface is configured to use.

    Follows ``WEB_AGENT_MODEL``: a ``gemini-*`` model checks the Google key,
    an ``ollama*/`` model checks the local Ollama server + that the model is
    pulled. This keeps the dashboard status chip accurate no matter which
    back-end the web UI points at.
    """
    web_model = os.getenv("WEB_AGENT_MODEL", "gemini-2.0-flash-lite")
    if web_model.startswith(("ollama_chat/", "ollama/")):
        return await _check_ollama_model(web_model, "Ollama (web)")
    return check_gemini()


def check_nvd() -> Check:
    """Report NVD API key status (optional, but raises rate limits)."""
    if os.getenv("NVD_API_KEY"):
        return Check("NVD API", True, "API key set (higher rate limit)")
    return Check("NVD API", True, "no key — works, but lower rate limit")


def check_search() -> Check:
    """Report the web-search provider configuration."""
    provider = (
        os.getenv("SEARCH_PROVIDER") or os.getenv("SEARCH_BACKEND") or "duckduckgo"
    ).lower()
    has_key = bool(
        os.getenv("SEARCH_API_KEY")
        or os.getenv("TAVILY_API_KEY")
        or os.getenv("SERPAPI_API_KEY")
    )
    if provider in ("tavily", "serpapi") and not has_key:
        return Check(
            "Web Search",
            False,
            f"{provider} selected but no API key — will fall back to DuckDuckGo",
        )
    return Check("Web Search", True, f"provider: {provider}")


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------


async def run_checks(scope: str = "cli") -> list[Check]:
    """Run the checks relevant to *scope* (``"cli"``, ``"web"``, or ``"all"``)."""
    checks: list[Check] = []
    if scope in ("cli", "all"):
        checks.append(await check_ollama())
    if scope in ("web", "all"):
        checks.append(await check_web())
    checks.append(check_nvd())
    checks.append(check_search())
    return checks
