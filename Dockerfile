# ────────────────────────────────────────────────────────────────────────────
# Stage 1 — deps
# Install only production dependencies into an isolated layer.
# This layer is cached by Docker as long as pyproject.toml and poetry.lock
# don't change — a code-only edit skips this entire stage on rebuild.
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS deps

# System packages needed to compile cryptography (libffi, openssl headers).
# --no-install-recommends keeps the layer lean.
# Clean apt cache in the same RUN to avoid bloating the layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Pin Poetry version — never use "latest" in production.
# POETRY_HOME puts Poetry in its own isolated directory, not site-packages.
# Adding it to PATH makes `poetry` available in subsequent RUN steps.
ENV POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PATH="/opt/poetry/bin:$PATH"

RUN pip install --no-cache-dir "poetry"

WORKDIR /app

# Copy lockfile and pyproject first — before source code.
# Docker layer cache: if only .py files change, this COPY and the
# `poetry install` below are served from cache. Critical for fast rebuilds.
COPY pyproject.toml poetry.lock ./

# --only main          → skip dev dependencies (pytest, black, ruff, etc.)
# --no-root            → don't install the project package itself yet
#                        (source code is copied in the next stage)
# --no-ansi --no-interaction → clean CI/Docker output
RUN poetry install --only main --no-root --no-ansi --no-interaction


# ────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime
# Minimal final image. Only the venv and source code land here.
# No Poetry, no compilers, no build tools — attack surface is minimal.
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime system deps only — no gcc, no headers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl3 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — never run application code as root in production.
# Group and user IDs are explicit so volume mounts match expected ownership.
RUN groupadd --gid 1001 pychain \
    && useradd --uid 1001 --gid pychain --no-create-home pychain

WORKDIR /app

# Copy the entire venv from the deps stage — not just site-packages.
# This brings in the correct Python binary symlinks and activation scripts.
COPY --from=deps /app/.venv /app/.venv

# Put the venv's bin directory first in PATH.
# All `python` and `uvicorn` calls resolve here without activation.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    # Prevent Python from writing .pyc files to disk
    PYTHONDONTWRITEBYTECODE=1 \
    # Disable output buffering — logs appear immediately in docker logs
    PYTHONUNBUFFERED=1 \
    # Tell the app it's running in production
    ENV=development

# Copy source code last — most frequently changing layer goes at the bottom.
# Changing any .py file only invalidates this layer and below.
COPY --chown=pychain:pychain pychain/ ./pychain/

# Data directory for SQLite — owned by the app user so it can write.
# In docker-compose this directory is bind-mounted as a named volume.
RUN mkdir -p /app/data && chown pychain:pychain /app/data

# Drop privileges
USER pychain

# Expose the port uvicorn will listen on.
# docker-compose maps this to the host; this line is documentation + metadata.
EXPOSE 8000

# Health check — Docker and compose use this to know when the container
# is ready to serve traffic. --fail makes curl return non-zero on 4xx/5xx.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Production uvicorn settings:
#   --host 0.0.0.0        → listen on all interfaces (required inside Docker)
#   --workers 2           → 2 × (CPU cores) is the standard starting point;
#                           tune via WORKERS env var in docker-compose
#   --no-access-log       → access logging handled by the reverse proxy (nginx)
#   --proxy-headers       → trust X-Forwarded-For from nginx
#   --no-server-header    → don't leak uvicorn version in response headers
CMD ["uvicorn", "pychain.main:app", \
     "--host", "0.0.0.0",\
     "--port", "8000", \
     "--workers", "2", \
     "--no-access-log", \
     "--proxy-headers", \
     "--no-server-header"]