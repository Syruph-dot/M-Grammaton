from types import SimpleNamespace

from mgraph import MGraph, Node
from quest_board import QuestBoard
from runtime.monitor import RuntimeMonitor
from runtime.server import _build_dashboard_snapshot


def test_dashboard_snapshot_contains_runtime_graph_tokens_and_quests():
    graph = MGraph()
    source = Node("source", content="alpha", tags={"root"}, mg=graph)
    target = Node("target", content="beta", mg=graph)
    source.link_to(target, 0.75)

    board = QuestBoard()
    runtime = SimpleNamespace(
        running=True,
        round=7,
        started_at=100.0,
        graph=graph,
        board=board,
        operators={},
    )
    monitor = RuntimeMonitor()
    monitor.update_node("Alice", "source")
    monitor.update_mbti("Alice", "INTJ")
    monitor.update_quests("Alice", 1)
    monitor.report_action("Alice", "wander", "target")
    monitor.report_tokens("Alice", "answer", 55, "reported", timestamp=125.0)

    snapshot = _build_dashboard_snapshot(runtime, monitor, now=140.0)

    assert snapshot["ready"] is True
    assert snapshot["runtime"]["running"] is True
    assert snapshot["runtime"]["round"] == 7
    assert snapshot["runtime"]["uptime_seconds"] == 40.0
    assert snapshot["stats"]["nodes"] == 2
    assert snapshot["stats"]["edges"] == 1
    assert snapshot["tokens"]["total"] == 55
    assert snapshot["operators"][0]["id"] == "Alice"
    assert snapshot["graph"]["nodes"][0]["id"] in {"source", "target"}
    assert snapshot["graph"]["links"] == [
        {
            "id": "source->target",
            "source": "source",
            "target": "target",
            "weight": 0.75,
        }
    ]
    assert "source" in {
        node["id"]
        for node in snapshot["graph"]["nodes"]
        if node["activeOperators"] == ["Alice"]
    }
    assert snapshot["quests"]["active"] == []
    assert snapshot["quests"]["completed"] == []

    # token throughput fields
    assert snapshot["tokens"]["tokens_per_sec"] == 0.9  # 55 / 60
    assert len(snapshot["tokens"]["tps_series"]) == 24   # 120s / 5s
    # event at ts=125, now=140 → age=15 → bucket index = 23 - (15/5) = 20
    assert snapshot["tokens"]["tps_series"][20] == 11.0  # 55 / 5
    assert all(v == 0.0 for i, v in enumerate(snapshot["tokens"]["tps_series"]) if i != 20)
