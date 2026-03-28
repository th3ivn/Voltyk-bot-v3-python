# Test Coverage Analysis

**Date**: 2026-03-28
**Overall Coverage**: 19.58% (5,598 statements, 4,502 missed)
**Tests**: 191 passing in ~5s
**Threshold**: 15% (currently met)

---

## Current Coverage by Module

| Module | Stmts | Cover | Notes |
|--------|-------|-------|-------|
| `formatter/messages.py` | 41 | **100%** | Fully tested |
| `formatter/timer.py` | 76 | **99%** | Near-complete |
| `formatter/schedule.py` | 135 | **93%** | Well tested |
| `utils/helpers.py` | 39 | **97%** | Excellent boundary tests |
| `config.py` | 72 | **82%** | Good |
| `constants/regions.py` | 26 | **65%** | Partial |
| `db/models.py` | 275 | **100%** | Model definitions only |
| `db/queries.py` | 288 | **40%** | ~30 queries untested |
| `services/api.py` | 277 | **40%** | HTTP/fetch logic untested |
| `services/power_monitor.py` | 677 | **10%** | Core logic largely untested |
| `services/scheduler.py` | 632 | **0%** | No tests at all |
| `handlers/*` (all) | ~2,100 | **0%** | No handler tests |
| `middlewares/*` (all) | 78 | **0%** | No middleware tests |
| `keyboards/inline.py` | 361 | **34%** | Partial (constants only) |
| `utils/html_to_entities.py` | 78 | **0%** | No tests |
| `services/branding.py` | 37 | **0%** | No tests |
| `formatter/template.py` | 15 | **33%** | Minimal |

---

## Recommended Improvements (Priority Order)

### 1. `services/scheduler.py` — 632 statements, 0% coverage (HIGH PRIORITY)

This is the largest completely untested module and contains critical business logic:
- **Schedule change detection** (`schedule_checker_loop`)
- **User notification dispatch** (`notify_users_about_schedule_change`)
- **Pre-event reminders** (`reminder_checker_loop`)
- **Daily snapshot generation** (`daily_flush_loop`)

**What to test**:
- Schedule hash comparison triggers notifications correctly
- Reminder timing logic (15m/30m/1h before events)
- Batch notification sending with pagination
- Deduplication of pending notifications
- Error handling when Telegram API is unavailable

**Approach**: Mock the database session and bot instance; test the core decision logic (should we notify? which users? what message?) without running the actual loops.

---

### 2. `services/power_monitor.py` — 677 statements, 10% coverage (HIGH PRIORITY)

Only state management and HTTP checks are tested. The core monitoring logic is not:
- **`_process_user()`** — The state machine that decides power on/off transitions
- **Debounce logic** — 5-minute stabilization window before triggering notifications
- **`power_monitor_loop()`** — Batch processing of all users with IPs
- **Notification sending** — Power on/off messages to users and channels
- **`update_power_notifications_on_schedule_change()`** — State reset on schedule updates

**What to test**:
- State transitions: unknown -> online -> offline -> online
- Debounce: rapid flaps should not trigger notifications
- Channel notification forwarding
- Graceful handling of unreachable routers
- Concurrent user processing behavior

---

### 3. `db/queries.py` — 288 statements, 40% coverage (MEDIUM PRIORITY)

~30 query functions are untested, including:
- `upsert_user_power_state()` (PostgreSQL-specific `ON CONFLICT`)
- `change_power_state_and_get_duration()` — Power duration calculation
- `save_pending_notification()` / `mark_pending_notifications_sent()`
- `get_active_reminder_anchors()` / `mark_reminder_sent()`
- `get_active_users_paginated()` — Batch pagination
- All admin/ticket/setting queries
- `get_daily_growth_stats()`, `get_weekly_retention()`

**What to test**:
- Pagination logic returns correct batches
- Upsert creates vs updates correctly
- Duration calculation across state changes
- Null/empty result handling for all untested functions

**Note**: PostgreSQL-specific features (`ON CONFLICT`) need either real DB fixtures (testcontainers) or careful mocking.

---

### 4. `handlers/*` — ~2,100 statements, 0% coverage (MEDIUM PRIORITY)

No handler is tested. Priority handlers to add tests for:

- **`handlers/start.py`** (188 stmts) — Onboarding wizard flow: new user vs returning user, region/queue selection, FSM state transitions
- **`handlers/menu.py`** (328 stmts) — Main menu: schedule viewing, settings navigation, status display
- **`handlers/settings/ip.py`** (230 stmts) — IP setup & validation, monitoring toggle, the most complex settings handler
- **`handlers/settings/alerts.py`** (181 stmts) — Notification toggle logic

**Approach**: Use aiogram's test utilities or mock `CallbackQuery`/`Message` objects. Focus on testing:
- FSM state transitions (wizard steps progress correctly)
- Input validation (invalid IPs, missing data)
- Permission checks (admin-only handlers reject regular users)
- Callback data routing (correct handler triggers for each button)

---

### 5. `middlewares/` — 78 statements, 0% coverage (MEDIUM PRIORITY)

Small but critical:
- **`db.py`** — Session injection, commit-on-success, rollback-on-error
- **`maintenance.py`** — Blocks users during maintenance, allows admins through
- **`throttle.py`** — Rate limiting per user (0.3 req/sec)

**What to test**:
- Session is committed after successful handler execution
- Session is rolled back on handler exception
- Maintenance mode blocks non-admin users with correct message
- Throttle rejects requests exceeding rate limit
- Throttle allows requests within rate limit

---

### 6. `utils/html_to_entities.py` — 78 statements, 0% coverage (LOW PRIORITY)

HTML-to-Telegram entity converter with no tests:
- Bold, italic, code, link tag parsing
- Nested tag handling
- Animated emoji conversion
- Malformed HTML resilience

---

### 7. `services/api.py` — HTTP layer, 277 statements, 40% coverage (LOW PRIORITY)

The parsing logic is well-tested but the HTTP/fetch layer is not:
- `fetch_schedule_data()` — HTTP GET + response parsing
- `check_source_repo_updated()` — GitHub API polling with ETag caching
- `fetch_schedule_image()` — Image fetching & caching
- `init_http_client()` / `close_http_client()` — Client lifecycle

**Approach**: Use `aioresponses` (already a dev dependency) to mock HTTP responses and test error handling (timeouts, 4xx/5xx, malformed JSON).

---

### 8. `keyboards/inline.py` — 361 statements, 34% coverage (LOW PRIORITY)

Keyboard builders are mostly mechanical but some contain conditional logic:
- Notification toggle keyboards (checkmark state depends on settings)
- Admin-only keyboard visibility
- Dynamic button text based on current state

---

## Quick Wins

These changes would improve coverage with minimal effort:

1. **Increase coverage threshold** in `pyproject.toml` from 15% to 25% — the codebase already meets this
2. **Add middleware tests** — ~30 lines of test code per middleware, high value for critical infrastructure
3. **Add `html_to_entities` tests** — Pure function, no mocking needed, easy to write
4. **Test `branding.py` validators** — Pure functions, simple input/output testing
5. **Enforce mypy in CI** — Currently runs with `|| true`, meaning type errors are silently ignored

## Suggested Coverage Target

A realistic near-term goal: **35-40%** coverage (roughly doubling current coverage) by adding tests for the scheduler, power monitor core logic, untested queries, and middlewares. Longer-term target: **55-60%** by adding handler tests for the most critical user flows.
