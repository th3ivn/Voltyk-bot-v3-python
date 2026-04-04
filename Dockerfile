FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    fonts-dejavu-core \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy runtime package files before install; editable install needs package sources present.
COPY pyproject.toml alembic.ini ./
COPY bot ./bot
COPY alembic ./alembic

RUN pip install --no-cache-dir -e .

COPY . .

CMD ["python", "-m", "bot"]
