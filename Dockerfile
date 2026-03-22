FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Install Chromium browser + all system dependencies via Playwright's own installer.
# This is required because Incapsula blocks plain HTTP requests (aiohttp/requests),
# but a real Chromium browser (headless Playwright) passes bot-detection checks.
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "bot"]
