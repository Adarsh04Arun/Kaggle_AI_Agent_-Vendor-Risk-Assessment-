"""
agents/model_factory.py — Resolve a model name into a concrete model object
for Google ADK's :class:`~google.adk.agents.LlmAgent`.

Routing rules:
    * ``gemini-*``                         → returned as a plain string. ADK
      resolves these natively via ``GOOGLE_API_KEY``. Used by the **web** UI.
    * ``ollama_chat/*`` / ``ollama/*`` /
      ``openai/*``                         → wrapped in :class:`LiteLlm` so ADK
      can drive them through LiteLLM. **Ollama** is the CLI / primary local
      handler.

Per-entry-point selection is done by passing an explicit ``model_name`` (the
web app passes ``WEB_AGENT_MODEL``; the CLI relies on ``AGENT_MODEL``). When no
name is supplied we fall back to ``AGENT_MODEL`` and finally a local Ollama
default so the app never silently picks the wrong provider.
"""

from __future__ import annotations

import logging
import os

from google.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)

# Providers that must be routed through LiteLLM instead of ADK's native
# (Gemini) model registry.
_LITELLM_PREFIXES = ("ollama_chat/", "ollama/", "openai/", "huggingface/")

# Local-first default: keeps Ollama as the primary handler when nothing else
# is configured.
_DEFAULT_MODEL = "ollama_chat/llama3.1"


def resolve_model_name(model_name: str | None = None) -> str:
    """Return the effective model id (explicit arg → AGENT_MODEL → default)."""
    return (model_name or os.getenv("AGENT_MODEL") or _DEFAULT_MODEL).strip()


def _json_schema_response_format(response_schema) -> dict | None:
    """Translate a Pydantic model / JSON-schema dict into a LiteLLM
    ``response_format`` block that Ollama honours as structured output.

    Returns ``None`` if *response_schema* is falsy or can't be introspected.
    """
    if not response_schema:
        return None

    # Accept a Pydantic BaseModel subclass or a raw JSON-schema dict.
    schema = response_schema
    name = "response"
    if hasattr(response_schema, "model_json_schema"):
        schema = response_schema.model_json_schema()
        name = getattr(response_schema, "__name__", "response")

    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": schema, "strict": True},
    }


def build_model(model_name: str | None = None, response_schema=None):
    """Build a model suitable for ``LlmAgent(model=...)``.

    Args:
        model_name: Explicit model id. Falls back to the ``AGENT_MODEL``
            environment variable, then to a local Ollama default.
        response_schema: Optional Pydantic model (or JSON-schema dict) used to
            constrain output. For LiteLLM-routed models (Ollama/OpenAI) this is
            attached as ``response_format`` so the provider enforces valid JSON;
            Gemini models are constrained separately by ADK's ``output_schema``.

    Returns:
        A ``str`` for Gemini models (resolved natively by ADK), or a
        :class:`~google.adk.models.lite_llm.LiteLlm` instance for Ollama /
        OpenAI / other LiteLLM providers.
    """
    name = resolve_model_name(model_name)

    if name.startswith(_LITELLM_PREFIXES):
        kwargs: dict[str, object] = {
            "model": name,
            # Deterministic extraction — local models drift far less at temp 0,
            # which is exactly what we want for the strict-JSON agent tasks.
            "temperature": 0,
        }
        # Ollama needs its base URL; OpenAI uses its own default endpoint.
        if name.startswith(("ollama_chat/", "ollama/")):
            kwargs["api_base"] = os.getenv(
                "OLLAMA_BASE_URL", "http://localhost:11434"
            )
        elif name.startswith("huggingface/"):
            # HF's TGI backend rejects temperature=0 ("must be strictly
            # positive"); use a low positive value for near-deterministic
            # output. LiteLLM reads HUGGINGFACE_API_KEY / HF_TOKEN from env.
            kwargs["temperature"] = 0.1
        response_format = _json_schema_response_format(response_schema)
        if response_format is not None:
            kwargs["response_format"] = response_format
            logger.info("Applied structured-output response_format to %s", name)
        logger.info("Resolved LiteLLM-routed model: %s", name)
        return LiteLlm(**kwargs)

    # Gemini (and any other ADK-native) model — return the raw string.
    logger.info("Resolved ADK-native model: %s", name)
    return name
