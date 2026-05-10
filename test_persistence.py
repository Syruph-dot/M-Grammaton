"""Phase 7: 持久化保存/加载校验。"""
import json
import os

from mgraph import MGraph, Node
from operators import Operator
from quest_board import QuestBoard
from persistence import save_state, load_state


def test_roundtrip_preserves_all_state(tmp_path):
    """保存 → 加载 → 验证所有状态不丢。"""
    # ── 构造完整场景 ──
    g = MGraph()
    anchor_a = g.add_node(Node("op_alice", mg=g))
    anchor_b = g.add_node(Node("op_bob", mg=g))

    alice = Operator("alice", anchor_a)
    bob = Operator("bob", anchor_b)
    operators = {"alice": alice, "bob": bob}

    board = QuestBoard()
    quest = board.post("alice", "test question", g)

    # Bob 阅读、回答
    bob.answer_quest(quest, board, g)
    # Alice 评分（双维度）
    alice.score_answer(quest, "bob", 85, 90, g, board)

    # ── 保存 ──
    path = os.path.join(tmp_path, "state.json")
    save_state(path, g, board, operators)

    # ── 加载 ──
    g2, board2, ops2 = load_state(path)

    # ── 验证图结构 ──
    assert len(g2.V) == len(g.V)
    names2 = {n.name for n in g2.V}
    assert names2 == {"op_alice", "op_bob", quest.name}

    assert len(g2.E) == len(g.E)
    for e in g.E:
        key = (e.source.name, e.target.name)
        found = any(
            e2.source.name == key[0] and e2.target.name == key[1]
            for e2 in g2.E
        )
        assert found, f"edge {key} missing after load"

    # ── 验证问答板 ──
    loaded_quest = board2.active[0]
    assert loaded_quest.name == quest.name
    assert loaded_quest.quester_id == "alice"
    assert loaded_quest.content == "test question"

    # ── 验证答案 ──
    assert loaded_quest.answers == quest.answers
    assert loaded_quest.from_ids == quest.from_ids

    # ── 验证评分（保持 tuple 类型） ──
    assert loaded_quest.scores[0] == (85, 90)
    assert isinstance(loaded_quest.scores[0], tuple)

    # ── 验证 AnswerTrace ──
    orig_trace = quest.answer_traces[0]
    loaded_trace = loaded_quest.answer_traces[0]
    assert loaded_trace is not None
    assert loaded_trace.quest_name == orig_trace.quest_name
    assert loaded_trace.answer_index == orig_trace.answer_index
    assert loaded_trace.answerer_id == orig_trace.answerer_id
    assert loaded_trace.node_names == orig_trace.node_names
    assert loaded_trace.edge_refs == orig_trace.edge_refs
    assert loaded_trace.score == orig_trace.score
    assert loaded_trace.feedback_applied is True

    # ── 验证 Operator ──
    assert set(ops2.keys()) == {"alice", "bob"}
    assert ops2["alice"].id == "alice"
    assert ops2["bob"].id == "bob"
    assert ops2["bob"].current.get().name == operators["bob"].current.get().name
    assert ops2["alice"].current.get().name == operators["alice"].current.get().name
    assert len(ops2["bob"].submitted_quests) == 0  # bob answered, didn't ask

    # ── 验证边权重 ──
    for e_orig in g.E:
        for e_loaded in g2.E:
            if (e_orig.source.name == e_loaded.source.name
                    and e_orig.target.name == e_loaded.target.name):
                assert abs(e_orig.value - e_loaded.value) < 1e-9
                break


def test_roundtrip_preserves_stk(tmp_path):
    """stk 条目在保存/加载后保持内容。"""
    g = MGraph()
    n0 = g.add_node(Node("A", mg=g))
    n1 = g.add_node(Node("B", mg=g))
    n0.link_to(n1, 1.0)

    board = QuestBoard()
    quest = board.post("alice", "q", g)
    bob = Operator("bob", n0)
    bob.answer_quest(quest, board, g)  # bob answers first
    op = Operator("alice", n1)
    op.score_answer(quest, "bob", 90, 90, g, board)

    # 手动触发 insert_response 产生 stk 条目
    from mgraph import insert_response
    edge = n0.outlinks[0]
    insert_response(True, edge)

    assert len(n0.stk) > 0
    path = os.path.join(tmp_path, "stk_state.json")
    save_state(path, g, board, {"alice": op, "bob": bob})

    g2, _, _ = load_state(path)
    n0_loaded = next(n for n in g2.V if n.name == "A")
    assert len(n0_loaded.stk) == len(n0.stk)
    for br_orig, br_loaded in zip(n0.stk, n0_loaded.stk):
        assert br_orig.reaction == br_loaded.reaction
        assert br_orig.weight == br_loaded.weight
        assert br_orig.target.source.name == br_loaded.target.source.name
        assert br_orig.target.target.name == br_loaded.target.target.name


def test_load_cleans_temporary_attr(tmp_path):
    """加载后节点不应残留 quest_data 临时属性。"""
    g = MGraph()
    n = g.add_node(Node("standalone", mg=g))
    board = QuestBoard()
    operators = {"dummy": Operator("dummy", n)}
    path = os.path.join(tmp_path, "clean.json")
    save_state(path, g, board, operators)
    g2, _, _ = load_state(path)
    for node in g2.V:
        assert not hasattr(node, "quest_data"), (
            f"{node.name} 残留 quest_data"
        )


def test_save_file_is_readable_json(tmp_path):
    """保存的文件应当是合法 JSON 且包含版本号。"""
    g = MGraph()
    g.add_node(Node("x", mg=g))
    board = QuestBoard()
    operators = {"o": Operator("o", next(iter(g.V)))}
    path = os.path.join(tmp_path, "readable.json")
    save_state(path, g, board, operators)

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert "version" in raw
    assert "nodes" in raw
    assert "edges" in raw
    assert "quest_board" in raw
    assert "operators" in raw
