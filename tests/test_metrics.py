"""Tests for bot/utils/metrics.py — covers both the prometheus_client and Noop paths."""
from __future__ import annotations

import sys
from types import ModuleType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_metrics_without_prometheus() -> ModuleType:
    """Reload bot.utils.metrics with prometheus_client hidden from sys.modules."""
    import bot.utils.metrics as _real  # ensure original is imported and cached

    # Remove cached module so we get a fresh import without prometheus_client.
    sys.modules.pop("bot.utils.metrics", None)

    # Temporarily block prometheus_client import
    sys.modules["prometheus_client"] = None  # type: ignore[assignment]
    try:
        import bot.utils.metrics as m
        return m
    finally:
        del sys.modules["prometheus_client"]
        # Restore the original (real) module so subsequent imports don't
        # trigger re-registration and a Prometheus CollectorRegistry ValueError.
        sys.modules["bot.utils.metrics"] = _real


# ---------------------------------------------------------------------------
# PROMETHEUS_AVAILABLE flag
# ---------------------------------------------------------------------------


class TestPrometheusAvailableFlag:
    def test_prometheus_available_flag_is_bool(self):
        import bot.utils.metrics as m
        assert isinstance(m.PROMETHEUS_AVAILABLE, bool)

    def test_prometheus_available_true_when_installed(self):
        import bot.utils.metrics as m
        # prometheus_client IS installed in this environment
        assert m.PROMETHEUS_AVAILABLE is True


# ---------------------------------------------------------------------------
# metrics_response()
# ---------------------------------------------------------------------------


class TestMetricsResponse:
    def test_metrics_response_returns_bytes_and_str_when_prometheus_available(self):
        import bot.utils.metrics as m
        body, content_type = m.metrics_response()
        assert isinstance(body, bytes)
        assert isinstance(content_type, str)

    def test_metrics_response_noop_returns_bytes_and_str(self):
        mod = _reload_metrics_without_prometheus()
        body, content_type = mod.metrics_response()
        assert isinstance(body, bytes)
        assert isinstance(content_type, str)

    def test_metrics_response_noop_body_has_content(self):
        mod = _reload_metrics_without_prometheus()
        body, _ = mod.metrics_response()
        assert len(body) > 0


# ---------------------------------------------------------------------------
# Counter labels — region / state
# ---------------------------------------------------------------------------


class TestCounterLabels:
    def test_schedule_notifications_counter_has_region_label(self):
        from bot.utils.metrics import SCHEDULE_NOTIFICATIONS_SENT
        # Should not raise
        labeled = SCHEDULE_NOTIFICATIONS_SENT.labels(region="kyiv")
        assert labeled is not None

    def test_power_notifications_counter_has_state_label(self):
        from bot.utils.metrics import POWER_NOTIFICATIONS_SENT
        labeled = POWER_NOTIFICATIONS_SENT.labels(state="off")
        assert labeled is not None

    def test_schedule_fetch_errors_counter_has_region_label(self):
        from bot.utils.metrics import SCHEDULE_FETCH_ERRORS
        labeled = SCHEDULE_FETCH_ERRORS.labels(region="lviv")
        assert labeled is not None

    def test_circuit_breaker_trips_counter_has_name_label(self):
        from bot.utils.metrics import CIRCUIT_BREAKER_TRIPS
        labeled = CIRCUIT_BREAKER_TRIPS.labels(name="upstream")
        assert labeled is not None


# ---------------------------------------------------------------------------
# Gauge .set()
# ---------------------------------------------------------------------------


class TestGaugeSet:
    def test_db_pool_size_set_does_not_raise(self):
        from bot.utils.metrics import DB_POOL_SIZE
        DB_POOL_SIZE.set(5)  # must not raise

    def test_db_pool_checked_out_set_does_not_raise(self):
        from bot.utils.metrics import DB_POOL_CHECKED_OUT
        DB_POOL_CHECKED_OUT.set(2)

    def test_user_states_in_memory_set_does_not_raise(self):
        from bot.utils.metrics import USER_STATES_IN_MEMORY
        USER_STATES_IN_MEMORY.set(100)

    def test_dirty_states_count_set_does_not_raise(self):
        from bot.utils.metrics import DIRTY_STATES_COUNT
        DIRTY_STATES_COUNT.set(0)


# ---------------------------------------------------------------------------
# Histogram .observe()
# ---------------------------------------------------------------------------


class TestHistogramObserve:
    def test_schedule_fetch_duration_observe_does_not_raise(self):
        from bot.utils.metrics import SCHEDULE_FETCH_DURATION
        SCHEDULE_FETCH_DURATION.observe(0.42)

    def test_notification_blast_duration_observe_does_not_raise(self):
        from bot.utils.metrics import NOTIFICATION_BLAST_DURATION
        NOTIFICATION_BLAST_DURATION.observe(12.5)


# ---------------------------------------------------------------------------
# Counter .inc()
# ---------------------------------------------------------------------------


class TestCounterInc:
    def test_telegram_retry_after_inc_does_not_raise(self):
        from bot.utils.metrics import TELEGRAM_RETRY_AFTER_TOTAL
        TELEGRAM_RETRY_AFTER_TOTAL.inc()

    def test_schedule_notifications_sent_inc_via_label(self):
        from bot.utils.metrics import SCHEDULE_NOTIFICATIONS_SENT
        SCHEDULE_NOTIFICATIONS_SENT.labels(region="odesa").inc()

    def test_power_notifications_sent_inc_via_label(self):
        from bot.utils.metrics import POWER_NOTIFICATIONS_SENT
        POWER_NOTIFICATIONS_SENT.labels(state="on").inc()


# ---------------------------------------------------------------------------
# Noop objects — all methods callable without raising
# ---------------------------------------------------------------------------


class TestNoopObjects:
    """Test the _Noop stub class that is used when prometheus_client is absent."""

    def _get_noop_module(self):
        return _reload_metrics_without_prometheus()

    def test_noop_prometheus_available_is_false(self):
        mod = self._get_noop_module()
        assert mod.PROMETHEUS_AVAILABLE is False

    def test_noop_inc_does_not_raise(self):
        mod = self._get_noop_module()
        mod.SCHEDULE_NOTIFICATIONS_SENT.inc()

    def test_noop_set_does_not_raise(self):
        mod = self._get_noop_module()
        mod.DB_POOL_SIZE.set(99)

    def test_noop_observe_does_not_raise(self):
        mod = self._get_noop_module()
        mod.SCHEDULE_FETCH_DURATION.observe(1.0)

    def test_noop_labels_returns_self(self):
        mod = self._get_noop_module()
        result = mod.POWER_NOTIFICATIONS_SENT.labels(state="off")
        assert result is mod.POWER_NOTIFICATIONS_SENT

    def test_noop_dec_does_not_raise(self):
        mod = self._get_noop_module()
        mod.USER_STATES_IN_MEMORY.dec()

    def test_noop_time_returns_self(self):
        mod = self._get_noop_module()
        result = mod.SCHEDULE_FETCH_DURATION.time()
        assert result is mod.SCHEDULE_FETCH_DURATION

    def test_noop_context_manager_does_not_raise(self):
        mod = self._get_noop_module()
        with mod.NOTIFICATION_BLAST_DURATION:
            pass

    def test_noop_all_metric_objects_callable(self):
        """Every stub object must have inc/set/observe without raising."""
        mod = self._get_noop_module()
        metric_names = [
            "SCHEDULE_NOTIFICATIONS_SENT",
            "POWER_NOTIFICATIONS_SENT",
            "SCHEDULE_FETCH_ERRORS",
            "CIRCUIT_BREAKER_TRIPS",
            "TELEGRAM_RETRY_AFTER_TOTAL",
            "USER_STATES_IN_MEMORY",
            "DIRTY_STATES_COUNT",
            "DB_POOL_SIZE",
            "DB_POOL_CHECKED_OUT",
            "SCHEDULE_FETCH_DURATION",
            "NOTIFICATION_BLAST_DURATION",
        ]
        for name in metric_names:
            obj = getattr(mod, name)
            obj.inc()
            obj.set(1)
            obj.observe(0.1)
            obj.dec()
            obj.labels()


# ---------------------------------------------------------------------------
# Real prometheus objects have required methods
# ---------------------------------------------------------------------------


class TestRealPrometheusObjects:
    """When prometheus_client IS available, objects expose standard methods."""

    def test_schedule_notifications_sent_has_labels(self):
        from bot.utils.metrics import SCHEDULE_NOTIFICATIONS_SENT
        assert hasattr(SCHEDULE_NOTIFICATIONS_SENT, "labels")

    def test_db_pool_size_has_set(self):
        from bot.utils.metrics import DB_POOL_SIZE
        assert hasattr(DB_POOL_SIZE, "set")

    def test_schedule_fetch_duration_has_observe(self):
        from bot.utils.metrics import SCHEDULE_FETCH_DURATION
        assert hasattr(SCHEDULE_FETCH_DURATION, "observe")

    def test_telegram_retry_after_total_has_inc(self):
        from bot.utils.metrics import TELEGRAM_RETRY_AFTER_TOTAL
        assert hasattr(TELEGRAM_RETRY_AFTER_TOTAL, "inc")
