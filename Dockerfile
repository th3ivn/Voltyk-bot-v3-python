# ──── Stage 1: Builder ────
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ──── Stage 2: Runtime ────
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN adduser --disabled-password --no-create-home botuser

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

USER botuser

EXPOSE 8080

CMD ["python", "-m", "src"]
