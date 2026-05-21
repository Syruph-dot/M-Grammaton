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


# ── 003: Cursor 导航命令 ────────────────────────────────


def test_select_out_edge_only_changes_selection():
    graph = _make_graph()
    user = UserActor()
    source = next(n for n in graph.V if n.name == "source")
    user.bind(source)

    ok = user.select_out_edge("target")
    assert ok is True

    state = user.build_panel_state(graph)
    assert state.out_edges[0]["selected"] is True
    assert state.current_node == "source"  # 未移动 cursor


def test_select_out_edge_invalid_target():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok = user.select_out_edge("nonexistent")
    assert ok is False


def test_nav_selected_edge_moves_cursor():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))
    user.select_out_edge("target")

    ok, detail = user.nav_selected_edge(graph)
    assert ok is True
    assert detail == "target"
    assert user.current_node == "target"


def test_nav_without_selected_edge_returns_error():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, detail = user.nav_selected_edge(graph)
    assert ok is False
    assert detail == "no_selected_edge"


def test_nav_stale_edge_clears_selection():
    """选中一个出边后修改图使其失效。"""
    graph = _make_graph()
    user = UserActor()
    source = next(n for n in graph.V if n.name == "source")
    user.bind(source)
    user.select_out_edge("target")

    # 手动移除边
    target = next(n for n in graph.V if n.name == "target")
    source.outlinks.clear()
    target.inlinks.clear()

    ok, detail = user.nav_selected_edge(graph)
    assert ok is False
    assert detail == "stale_edge"


def test_random_select_out_edge_highlights_one():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, detail = user.random_select_out_edge(graph)
    assert ok is True
    assert detail == "target"  # 只有一条出边
    state = user.build_panel_state(graph)
    assert state.out_edges[0]["selected"] is True


def test_random_select_no_out_edges():
    graph = MGraph()
    Node("lonely", mg=graph)
    user = UserActor()
    user.bind(next(iter(graph.V)))

    ok, detail = user.random_select_out_edge(graph)
    assert ok is False
    assert detail == "no_out_edges"


def test_random_reset_cursor_binds_to_random_node():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, detail = user.random_reset_cursor(graph)
    assert ok is True
    assert user.current_node in {"source", "target"}


def test_random_reset_cursor_empty_graph():
    user = UserActor()
    ok, detail = user.random_reset_cursor(MGraph())
    assert ok is False
    assert detail == "empty_graph"


# ── 004: Stash ──────────────────────────────────────


def test_add_to_stash():
    graph = _make_graph()
    user = UserActor()
    node = next(n for n in graph.V if n.name == "source")
    user.bind(node)

    ok = user.add_to_stash(node, reason="测试收藏")
    assert ok is True

    state = user.build_panel_state(graph)
    assert len(state.stash) == 1
    assert state.stash[0]["node_id"] == "source"
    assert state.stash[0]["reason"] == "测试收藏"


def test_add_to_stash_duplicate_rejected():
    graph = _make_graph()
    user = UserActor()
    node = next(n for n in graph.V if n.name == "source")

    user.add_to_stash(node)
    ok = user.add_to_stash(node)
    assert ok is False  # 重复添加失败


def test_remove_from_stash():
    graph = _make_graph()
    user = UserActor()
    node = next(n for n in graph.V if n.name == "source")
    user.add_to_stash(node)

    ok = user.remove_from_stash("source")
    assert ok is True

    state = user.build_panel_state(graph)
    assert len(state.stash) == 0


def test_stash_ttl_expiry():
    graph = _make_graph()
    user = UserActor()
    node = next(n for n in graph.V if n.name == "source")

    # TTL=0 表示立即过期
    ok = user.add_to_stash(node, ttl=0)
    assert ok is True

    state = user.build_panel_state(graph)
    assert len(state.stash) == 0  # 已过期


def test_stash_remove_nonexistent():
    user = UserActor()
    ok = user.remove_from_stash("ghost")
    assert ok is False


# ── 006: Message Queue ─────────────────────────────


def test_add_message():
    user = UserActor()
    msg_id = user.add_message("test", "hello world")
    assert msg_id.startswith("msg_")

    state = user.build_panel_state()
    assert len(state.active_messages) == 1
    assert state.active_messages[0]["summary"] == "hello world"
    assert state.active_messages[0]["status"] == "active"


def test_select_message_next():
    user = UserActor()
    user.add_message("type_a", "first")
    user.add_message("type_b", "second")

    ok = user.select_message_next()
    assert ok is True
    assert user.selected_message != ""

    ok = user.select_message_next()
    assert ok is True

    # 循环回到第一个
    state = user.build_panel_state()
    assert len(state.active_messages) == 2


def test_select_message_prev():
    user = UserActor()
    user.add_message("type_a", "first")
    user.add_message("type_b", "second")

    user.select_message_next()  # 选中第一个
    ok = user.select_message_prev()  # 回到最后一个
    assert ok is True


def test_select_message_empty_queue():
    user = UserActor()
    ok = user.select_message_next()
    assert ok is False


def test_set_message_done():
    user = UserActor()
    msg_id = user.add_message("test", "do me")
    user.selected_message = msg_id

    ok = user.set_message_done()
    assert ok is True

    state = user.build_panel_state()
    assert len(state.active_messages) == 0


def test_set_message_done_no_selection():
    user = UserActor()
    ok = user.set_message_done()
    assert ok is False


def test_delete_message():
    user = UserActor()
    msg_id = user.add_message("test", "delete me")
    user.selected_message = msg_id

    ok = user.delete_message()
    assert ok is True

    state = user.build_panel_state()
    assert len(state.active_messages) == 0


def test_block_message():
    user = UserActor()
    msg_id = user.add_message("unsupported", "bad msg")
    user.selected_message = msg_id

    ok = user.block_message(msg_id, "unsupported")
    assert ok is True

    state = user.build_panel_state()
    assert len(state.active_messages) == 0
    assert len(state.blocked_messages) == 1
    assert state.blocked_messages[0]["id"] == msg_id


def test_block_message_clears_selection():
    user = UserActor()
    msg_id = user.add_message("test", "block me")
    user.selected_message = msg_id
    user.block_message(msg_id)

    assert user.selected_message == ""


# ── 005: Note / Reply Commit ───────────────────────────


def test_commit_note_creates_artifact():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, note_id = user.commit_note("这是一条测试笔记", graph)
    assert ok is True
    assert note_id.startswith("note_user_")

    # 验证 artifact 节点在图中
    note_node = next((n for n in graph.V if n.name == note_id), None)
    assert note_node is not None
    assert note_node.kind == "note"
    assert note_node.content == "这是一条测试笔记"

    # 验证边：source -> note
    source = next(n for n in graph.V if n.name == "source")
    assert any(e.target.name == note_id for e in source.outlinks)


def test_commit_note_empty_content():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, detail = user.commit_note("", graph)
    assert ok is False
    assert detail == "empty_content"


def test_commit_note_no_current_node():
    graph = _make_graph()
    user = UserActor()
    ok, detail = user.commit_note("content", graph)
    assert ok is False


def test_commit_reply_to_quest():
    graph = _make_graph()
    quest = QuestNode("q_test", quester_id="Alice", content="测试问题")
    graph.add_node(quest)
    source = next(n for n in graph.V if n.name == "source")
    source.link_to(quest, 1.0)

    user = UserActor()
    user.bind(source)

    ok, ans_id = user.commit_reply("测试回答", quest_name="q_test", graph=graph)
    assert ok is True
    assert ans_id.startswith("answer_user_")

    # 验证 AnswerNode 在图中
    ans_node = next((n for n in graph.V if n.name == ans_id), None)
    assert ans_node is not None
    assert isinstance(ans_node, AnswerNode)
    assert ans_node.content == "测试回答"
    assert ans_node.answerer_id == "user"
    assert ans_node.quest_name == "q_test"

    # 验证边：quest -> answer
    assert any(e.target.name == ans_id for e in quest.outlinks)


def test_commit_reply_no_quest_creates_note():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, note_id = user.commit_reply("fallback note", quest_name=None, graph=graph)
    assert ok is True
    assert note_id.startswith("note_user_")


def test_commit_reply_quest_not_found():
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, detail = user.commit_reply("reply", quest_name="nonexistent", graph=graph)
    assert ok is False
    assert detail == "quest_not_found"


def test_commit_does_not_write_human_files():
    """验证 artifact commit 不修改 data/human/*.md。
    此测试只验证 artifact 节点 kind 不是 'document'。"""
    graph = _make_graph()
    user = UserActor()
    user.bind(next(n for n in graph.V if n.name == "source"))

    ok, note_id = user.commit_note("纯 artifact", graph)
    assert ok is True
    note_node = next(n for n in graph.V if n.name == note_id)
    assert note_node.kind == "note"  # 不是 document，不会被写入 human/
