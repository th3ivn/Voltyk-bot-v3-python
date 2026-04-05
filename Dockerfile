FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    fonts-dejavu-core \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependency layer (cached unless pyproject.toml changes) ───────────────
# Copy only the manifest so Docker can cache the pip install layer.
# A temporary stub package is not needed because we do a regular (non-editable)
# install from the wheel, which does not require the source tree at install time.
COPY pyproject.toml alembic.ini ./

# Create minimal stub so setuptools can build the package metadata without the
# full source tree.
RUN mkdir -p bot && touch bot/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf bot/__init__.py

# ── Application sources ────────────────────────────────────────────────────
COPY bot ./bot
COPY alembic ./alembic
COPY assets ./assets

# Re-install so the installed package points at the final source layout.
# This layer is only re-executed when pyproject.toml or sources change.
RUN pip install --no-cache-dir --no-deps .

# ── Health check (used by Docker and Railway) ──────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/health', timeout=4)" \
    || exit 1

CMD ["python", "-m", "bot"]
