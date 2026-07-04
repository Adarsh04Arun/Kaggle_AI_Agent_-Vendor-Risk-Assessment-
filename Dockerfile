# ── Builder ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# This image serves the web dashboard. The LLM back-end is chosen at runtime
# via WEB_AGENT_MODEL (Hugging Face / Gemini / Ollama) — set it plus the matching
# key as environment variables on your host (Render, Cloud Run, etc.).
# The CLI's local-Ollama path is a host-side workflow and is not containerised.
LABEL maintainer="vendor-risk-assessor" \
      description="Automated Vendor Risk Assessor — AI-powered cybersecurity assessment"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Install curl for the health-check probe.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user for security.
RUN groupadd --gid 1000 appuser && \
    useradd  --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy pre-built Python packages from the builder stage.
COPY --from=builder /install /usr/local

# Copy application source.
COPY . .

# Ensure static / template dirs exist (needed at import time).
RUN mkdir -p app/static app/templates

# Drop privileges.
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f "http://localhost:${PORT}/api/health" || exit 1

CMD ["python", "run.py"]
