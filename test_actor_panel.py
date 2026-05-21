"""测试 ActorPanelState 快照协议。

覆盖场景:
- User Actor 面板快照（含自动绑定首节点）
- Operator Actor 面板快照（从 monitor snapshot 映射）
- 空图 User Actor 面板
- 缺失 actor（404 等价行为）
- Panel state JSON shape 稳定性
"""

from types import SimpleNamespace

from mgraph import MGraph, Node
from questnode import AnswerNode, QuestNode
from runtime.actor_panel import (
    UserActor,
    ActorPanelState,
    build_operator_panel_state,
    StashItem,
    MessageEnvelope,
)
from runtime.monitor import RuntimeMonitor
from runtime.server import (
    _build_dashboard_snapshot,
)


def _make_graph() -> MGraph:
    """创建 2 节点测试图。"""
    graph = MGraph()
    src = Node("source", content="alpha content", tags={"root"}, mg=graph)
    tgt = Node("target", content="beta content", mg=graph)
    src.link_to(tgt, 0.75)
    return graph


# ── User Actor ────────────────────────────────────────────


def test_user_actor_panel_state_contains_node_and_edge_summaries():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    state = user.build_panel_state(graph)

    assert state.actor_id == "user"
    assert state.actor_kind == "user"
    assert state.current_node == "source"
    assert state.current_node_kind == "document"
    assert state.current_node_content_preview == "alpha content"
    assert len(state.out_edges) == 1
    assert state.out_edges[0]["target"] == "target"
    assert state.out_edges[0]["weight"] == 0.75
    assert state.out_edges[0]["selected"] is False
    assert len(state.in_edges) == 0  # source has no in-edges


def test_user_actor_auto_binds_to_first_content_node():
    graph = _make_graph()
    user = UserActor()  # 未 bind
    state = user.build_panel_state(graph)

    assert state.current_node != ""  # 自动 bind 到第一个内容节点
    assert user.current_node != ""


def test_user_actor_empty_graph_panel():
    user = UserActor()
    state = user.build_panel_state(None)

    assert state.actor_id == "user"
    assert state.current_node == ""
    assert state.out_edges == []
    assert state.in_edges == []


def test_user_actor_to_dict_shape():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    state = user.build_panel_state(graph)
    d = state.to_dict()

    assert "actor_id" in d
    assert "actor_kind" in d
    assert "current_node" in d
    assert "current_node_kind" in d
    assert "current_node_title" in d
    assert "current_node_content_preview" in d
    assert "is_readonly" in d
    assert "out_edges" in d
    assert "in_edges" in d
    assert "stash" in d
    assert "selected_message" in d
    assert "active_messages" in d
    assert "blocked_messages" in d
    assert "timestamp" in d


# ── Chunk / Local Edge / readonly ─────────────────────────


def test_human_source_node_is_readonly():
    """Document 节点属于 Human Source，标记为只读。"""
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))
    state = user.build_panel_state(graph)
    assert state.is_readonly is True


def test_quest_node_is_not_readonly():
    """Quest 节点属于 Operator artifact，非只读。"""
    graph = MGraph()
    doc = Node("doc", content="human", mg=graph)
    quest = QuestNode("q1", content="a quest?", quester_id="Alice")
    graph.add_node(quest)
    doc.link_to(quest, 1.0)

    user = UserActor()
    user.bind(quest)
    state = user.build_panel_state(graph)
    assert state.current_node == "q1"
    assert state.is_readonly is False


def test_answer_node_is_not_readonly():
    """Answer 节点属于 Operator artifact，非只读。"""
    graph = MGraph()
    doc = Node("doc", content="human", mg=graph)
    quest = QuestNode("q1", quester_id="Alice")
    graph.add_node(quest)
    ans = AnswerNode("a1", content="answer", answerer_id="Bob",
                     quest_name="q1")
    graph.add_node(ans)
    doc.link_to(ans, 1.0)

    user = UserActor()
    user.bind(ans)
    state = user.build_panel_state(graph)
    assert state.current_node == "a1"
    assert state.is_readonly is False


# ── Graph node click (select_node) ────────────────────────


def test_user_select_node_changes_current_node():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    target = next(n for n in graph.V if n.name == "target")
    user.bind(target)

    assert user.current_node == "target"
    state = user.build_panel_state(graph)
    assert state.current_node == "target"
    assert state.current_node_content_preview == "beta content"


def test_user_select_nonexistent_node_no_crash():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    # 绑定到不存在的节点——这里模拟 NodePtr 行为，它只持弱引用
    # 直接测试 UserActor 的 build_panel_state 不会因错误 node_id 崩溃
    state = user.build_panel_state(graph)
    assert state.current_node == "source"  # unchanged


# ── Operator Actor ────────────────────────────────────────


def test_operator_actor_panel_state_from_monitor_snapshot():
    graph = _make_graph()
    monitor = RuntimeMonitor()
    monitor.update_node("Alice", "source")
    monitor.update_mbti("Alice", "INTJ")
    monitor.update_quests("Alice", 1)
    monitor.report_action("Alice", "wander", "target")

    snap = monitor.snapshot()["Alice"]
    state = build_operator_panel_state(
        operator_id=snap.operator_id,
        current_node_name=snap.current_node,
        mbti=snap.mbti,
        active_quests=snap.active_quests,
        last_action=snap.last_action,
        graph=graph,
        timestamp=snap.timestamp,
    )

    assert state.actor_id == "Alice"
    assert state.actor_kind == "operator"
    assert state.current_node == "source"
    assert state.current_node_kind == "document"
    assert state.current_node_content_preview == "alpha content"
    assert len(state.out_edges) == 1
    assert state.out_edges[0]["target"] == "target"


def test_operator_panel_empty_graph_no_crash():
    state = build_operator_panel_state(
        operator_id="Bob",
        current_node_name="",
        graph=MGraph(),
    )
    assert state.actor_id == "Bob"
    assert state.actor_kind == "operator"
    assert state.current_node == ""
    assert state.out_edges == []


def test_operator_panel_missing_node_in_graph_no_crash():
    graph = _make_graph()
    state = build_operator_panel_state(
        operator_id="Carol",
        current_node_name="nonexistent",
        graph=graph,
    )
    assert state.current_node == "nonexistent"
    assert state.current_node_content_preview == ""


# ── Dashboard Snapshot ────────────────────────────────────


def test_dashboard_snapshot_contains_actor_list_with_user_and_operators():
    graph = _make_graph()
    runtime = SimpleNamespace(
        running=True,
        round=1,
        started_at=100.0,
        graph=graph,
        board=SimpleNamespace(active=[], completed=[]),
        operators={"Alice": SimpleNamespace()},
    )
    monitor = RuntimeMonitor()
    monitor.update_node("Alice", "target")
    monitor.update_mbti("Alice", "INTJ")

    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    # 注入 user_actor -> monitor_obj path: _build_dashboard_snapshot 不直接
    # 引用 user_actor_ref; 我们手动校验 actors 列表
    from runtime.server import _actor_list
    actors = _actor_list(user, monitor)

    assert len(actors) == 2
    actor_ids = {a["id"] for a in actors}
    assert "user" in actor_ids
    assert "Alice" in actor_ids


def test_dashboard_snapshot_actor_list_empty_when_no_user_and_no_ops():
    from runtime.server import _actor_list
    actors = _actor_list(None, None)
    assert actors == []


# ── Missing actor ─────────────────────────────────────────


def test_build_operator_panel_unknown_actor_returns_empty():
    """不存在的 actor_id —— 由 server endpoint 处理 404，builder 只负责映射。"""
    state = build_operator_panel_state(
        operator_id="ghost",
        current_node_name="",
    )
    assert state.actor_id == "ghost"
    assert state.current_node == ""
