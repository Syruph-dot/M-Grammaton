import time

from runtime.monitor import RuntimeMonitor


def test_monitor_records_token_usage_totals_and_window():
    monitor = RuntimeMonitor()
    now = time.time()

    monitor.report_tokens(
        operator_id="Alice",
        action="answer",
        tokens=120,
        source="reported",
        timestamp=now - 30,
    )
    monitor.report_tokens(
        operator_id="Bob",
        action="score",
        tokens=80,
        source="estimated",
        timestamp=now - 90,
    )

    snap = monitor.token_snapshot(now=now)

    assert snap["total"] == 200
    assert snap["last_minute"] == 120
    assert snap["requests"] == 2
    assert snap["reported"] == 1
    assert snap["estimated"] == 1
    assert snap["series"][-1]["tokens"] == 80


def test_monitor_dashboard_event_subscription_gets_operator_and_token_events():
    monitor = RuntimeMonitor()
    q = monitor.subscribe_events()

    monitor.report_action("Alice", "wander", "node-a")
    monitor.report_tokens("Alice", "wander", 33, "reported")

    first = q.get_nowait()
    second = q.get_nowait()

    assert first["type"] == "operator_update"
    assert first["operator"]["id"] == "Alice"
    assert second["type"] == "token_usage"
    assert second["tokens"]["tokens"] == 33
