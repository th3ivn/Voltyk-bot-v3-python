# Railway deploy troubleshooting (PR #309 and later)

## Why deployments started failing after PR #309

Starting from PR #309, the bot performs a startup guard in production:

- `ensure_production_endpoint_tokens()` is called from `bot.app.main()`.
- If `ENVIRONMENT=production` and either `HEALTHCHECK_TOKEN` or `METRICS_TOKEN` is empty, the process raises `ValueError` and exits.

This means Railway will restart the container and the deploy will look "broken" until both tokens are configured.

## Why this can also break Railway health checks

Railway is configured to probe `/health` with no auth (`railway.json`).

When `HEALTHCHECK_TOKEN` is set, `/health` requires either:

- `Authorization: Bearer <HEALTHCHECK_TOKEN>`, or
- `?token=<HEALTHCHECK_TOKEN>` query parameter.

An unauthenticated probe gets HTTP 401, which can trigger restarts depending on Railway health policy.

## What to set in Railway variables

Required for production boot:

- `HEALTHCHECK_TOKEN` (strong random value)
- `METRICS_TOKEN` (strong random value)
- `ENVIRONMENT=production`

Example token generation:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Recommended alignment for Railway checks

Use one of the following:

1. Configure Railway health check path to include token (if your Railway setup supports env interpolation), e.g. `/health?token=<HEALTHCHECK_TOKEN>`.
2. Keep protected `/health` and point Railway health checks to a dedicated unauthenticated readiness endpoint (requires code change).
3. As a temporary emergency measure only, set `ENVIRONMENT` to a non-production value to bypass startup token guard (not recommended long-term).
