# Operations artifacts

Ready-to-use monitoring for the Voltyk bot.  These files are not consumed
at runtime — they are committed alongside the bot so ops teams have a
reproducible starting point and every change to metric names or thresholds
is reviewed together with the code change that introduced it.

## Prometheus alerts — `prometheus/alerts.yaml`

Load into Prometheus via `rule_files:` in your Prometheus config:

```yaml
rule_files:
  - /etc/prometheus/rules/voltyk.yaml
```

Grouped by concern:

| Group | Severity levels | What they catch |
|-------|-----------------|-----------------|
| `voltyk-bot.liveness` | page | Pod unreachable, background task stalled |
| `voltyk-bot.saturation` | warn / info | DB pool pressure, rate-limit queueing, Telegram breaker open |
| `voltyk-bot.correctness` | warn | Sustained send failures, breaker flap, safety-net trip |

Tune the `for:` durations to your on-call tolerance.  The values
committed here are the authors' starting recommendations for a
single-replica deployment on Railway.

## Grafana dashboard — `grafana/voltyk-dashboard.json`

Import via **Dashboards → New → Import → Upload JSON**, select the
Prometheus data source that scrapes the bot's `/metrics` endpoint.

Panels cover, top to bottom:

1. **Stat row** — DB pool utilisation, RSS, in-memory state counts.
2. **Background task heartbeat age** — the single most important signal
   for liveness; if any series climbs to its threshold, /health is
   already returning 503.
3. **Telegram sends per second** — volume by notification type.
4. **Rate-limit wait quantiles** — how much queueing the 25 msg/s global
   budget is causing.
5. **Circuit breaker trips** — upstream instability.
6. **Scheduler failures by region** — regional breakdown of non-Forbidden
   send failures.
7. **Power-check skipped** — per-reason counter for the safety-net
   handlers.
8. **DB session + schedule-fetch latency** — p50/p95/p99.
9. **User lifecycle** — registrations, deactivations, deletions.

## Scraping the bot

`/metrics` is protected by `METRICS_TOKEN`.  Configure your Prometheus
scrape job to send the bearer token:

```yaml
scrape_configs:
  - job_name: voltyk-bot
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/voltyk-metrics.token
    static_configs:
      - targets: ["voltyk-bot.internal:3000"]
```
