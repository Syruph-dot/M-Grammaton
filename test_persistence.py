"""持久化层 data/ 目录格式测试。"""
import json
import os

from mgraph import MGraph, Node, binResponse
from operators import Operator
from quest_board import QuestBoard
from questnode import QuestNode, AnswerTrace
from persistence import (
    save_graph, load_graph, save_node,
    _node_to_md, _md_to_node, _compress_stk,
)


def test_node_md_roundtrip(tmp_path):
    """Node → .md → Node 往返。"""
    g = MGraph()
    n = Node("test_node", kind="document", content="这是一段正文。", tags={"ai"}, mg=g)
    n.title = "测试标题"
    n.t_read = 42.0
    n.t_lp = 99.0
    n.metadata = {"author": "测试"}

    md = _node_to_md(n)
    assert "test_node" in md
    assert "测试标题" in md
    assert "这是一段正文" in md
    assert "author" in md

    g2 = MGraph()
    n2, parent, stk = _md_to_node(md, g2)
    assert n2.name == "test_node"
    assert n2.kind == "document"
    assert n2.content.strip() == "这是一段正文。"
    assert n2.title == "测试标题"
    assert n2.t_read == 42.0
    assert n2.t_lp == 99.0
    assert n2.tags == {"ai"}
    assert n2.metadata == {"author": "测试"}
    assert parent is None
    assert stk == []


def test_questnode_md_roundtrip(tmp_path):
    """QuestNode → .md → QuestNode 往返。"""
    g = MGraph()
    q = QuestNode("quest_x", quester_id="Alice", content="如何定义意识？")
    q.answers = ["答案是..."]
    q.scores = [(85, 70)]
    q.from_ids = ["Bob"]
    trace = AnswerTrace(
        quest_name="quest_x", answer_index=0, answerer_id="Bob",
        node_names=["A", "B"], edge_refs=[("A", "B")],
        score=80.0, feedback_applied=True,
    )
    q.answer_traces = [trace]
    g.add_node(q)

    md = _node_to_md(q)
    assert "quest_x" in md
    assert "quester_id" in md
    assert "Alice" in md

    g2 = MGraph()
    q2, parent, stk = _md_to_node(md, g2)
    assert isinstance(q2, QuestNode)
    assert q2.kind == "quest"
    assert q2.name == "quest_x"
    assert q2.quester_id == "Alice"
    assert q2.content.strip() == "如何定义意识？"
    assert q2.answers == ["答案是..."]
    assert q2.scores == [(85, 70)]
    assert q2.from_ids == ["Bob"]
    assert len(q2.answer_traces) == 1
    assert q2.answer_traces[0].quest_name == "quest_x"
    assert q2.answer_traces[0].node_names == ["A", "B"]
    assert q2.answer_traces[0].edge_refs == [("A", "B")]
    assert q2.answer_traces[0].feedback_applied is True


def test_roundtrip_preserves_all_state(tmp_path):
    """保存 → 加载 → 验证所有状态不丢。"""
    data_dir = os.path.join(tmp_path, "data")

    g = MGraph()
    anchor_a = g.add_node(Node("op_alice", mg=g))
    anchor_b = g.add_node(Node("op_bob", mg=g))

    alice = Operator("alice", anchor_a)
    bob = Operator("bob", anchor_b)
    operators = {"alice": alice, "bob": bob}

    board = QuestBoard()
    quest = board.post("alice", "test question", g)
    bob.answer_quest(quest, board, g)
    alice.score_answer(quest, "bob", 85, 90, g, board)

    metadata = {"round": 5, "llm_api_key": "sk-test"}
    save_graph(g, board, operators, data_dir, metadata=metadata)

    # 验证目录结构
    meta_dir = os.path.join(data_dir, "meta")
    assert os.path.isfile(os.path.join(meta_dir, "graph.json"))
    assert os.path.isfile(os.path.join(meta_dir, "edges.json"))
    assert os.path.isfile(os.path.join(meta_dir, "operators.json"))
    assert os.path.isfile(os.path.join(meta_dir, "quest_board.json"))
    assert os.path.isfile(os.path.join(data_dir, "op_alice.md"))
    assert os.path.isfile(os.path.join(data_dir, "op_bob.md"))

    # 加载
    g2, board2, ops2, meta2 = load_graph(data_dir)

    # ── 验证图 ──
    assert len(g2.V) == len(g.V)
    names2 = {n.name for n in g2.V}
    assert quest.name in names2

    # ── 验证边 ──
    assert len(g2.E) == len(g.E)
    for e in g.E:
        found = any(
            e2.source.name == e.source.name and e2.target.name == e.target.name
            for e2 in g2.E
        )
        assert found, f"edge {e.source.name}->{e.target.name} missing"

    # ── 验证问答板 ──
    loaded_quest = board2.active[0]
    assert loaded_quest.name == quest.name
    assert loaded_quest.quester_id == "alice"
    assert loaded_quest.content == "test question"
    assert loaded_quest.answers == quest.answers
    assert loaded_quest.scores[0] == (85, 90)

    # ── 验证 AnswerTrace ──
    assert loaded_quest.answer_traces[0] is not None
    assert loaded_quest.answer_traces[0].node_names == quest.answer_traces[0].node_names

    # ── 验证 Operator ──
    assert set(ops2.keys()) == {"alice", "bob"}
    assert ops2["alice"].current.get().name == "op_alice"

    # ── 验证边权重 ──
    for e_orig in g.E:
        for e_loaded in g2.E:
            if (e_orig.source.name == e_loaded.source.name
                    and e_orig.target.name == e_loaded.target.name):
                assert abs(e_orig.value - e_loaded.value) < 1e-9

    # ── 验证 metadata ──
    assert meta2 is not None
    assert meta2["round"] == 5
    assert meta2["llm_api_key"] == "sk-test"


def test_roundtrip_preserves_stk(tmp_path):
    """stk 条目在保存/加载后保持。"""
    data_dir = os.path.join(tmp_path, "data")

    g = MGraph()
    n0 = g.add_node(Node("A", mg=g))
    n1 = g.add_node(Node("B", mg=g))
    n0.link_to(n1, 1.0)

    board = QuestBoard()
    quest = board.post("alice", "q", g)
    bob = Operator("bob", n0)
    bob.answer_quest(quest, board, g)
    op = Operator("alice", n1)
    op.score_answer(quest, "bob", 90, 90, g, board)

    from mgraph import insert_response
    edge = n0.outlinks[0]
    insert_response(True, edge)
    assert len(n0.stk) > 0

    save_graph(g, board, {"alice": op, "bob": bob}, data_dir)
    g2, _, _, _ = load_graph(data_dir)

    n0_loaded = next(n for n in g2.V if n.name == "A")
    assert len(n0_loaded.stk) == len(n0.stk)
    for br_orig, br_loaded in zip(n0.stk, n0_loaded.stk):
        assert br_orig.reaction == br_loaded.reaction
        assert br_orig.target.source.name == br_loaded.target.source.name
        assert br_orig.target.target.name == br_loaded.target.target.name


def test_save_node_atomic(tmp_path):
    """单节点增量保存。"""
    data_dir = os.path.join(tmp_path, "data")
    g = MGraph()
    n = Node("solo", kind="document", content="原始内容", mg=g)

    save_node(n, data_dir)
    assert os.path.isfile(os.path.join(data_dir, "solo.md"))

    n.content = "更新内容"
    save_node(n, data_dir)

    g2 = MGraph()
    n2, _, _ = _md_to_node(
        open(os.path.join(data_dir, "solo.md"), encoding="utf-8").read(), g2
    )
    assert n2.content.strip() == "更新内容"


def test_stk_compression():
    """stk 压缩：相邻同符号留最近 20，超 100 截断。"""
    # 同符号长跑 → 只保留最近 20
    long_run = [[True, f"n{i}"] for i in range(50)]
    result = _compress_stk(long_run)
    assert len(result) == 20
    assert result[-1][1] == "n49"

    # 交替：30 对 True/False → 每 run 长度 1，不触发压缩，全保留
    alternating = []
    for i in range(30):
        alternating.append([True, f"p{i}"])
        alternating.append([False, f"n{i}"])
    result = _compress_stk(alternating)
    assert len(result) == 60  # 60 个 run，每个 run 1 条，不压缩

    # 超 100 → 截断尾部 50：需要交替跑，每 run 不超 20 但总长超 100
    huge = []
    for sign in [True, False] * 60:
        huge.append([sign, "x"])
    assert len(huge) == 120
    result = _compress_stk(huge)
    assert len(result) == 50

    # 空列表
    assert _compress_stk([]) == []


def test_graph_meta(tmp_path):
    """graph.json 包含版本和统计信息。"""
    data_dir = os.path.join(tmp_path, "data")
    g = MGraph()
    nx = g.add_node(Node("x", mg=g))
    ny = g.add_node(Node("y", mg=g))
    nx.link_to(ny, 0.5)

    board = QuestBoard()
    operators = {"o": Operator("o", nx)}

    save_graph(g, board, operators, data_dir)

    with open(os.path.join(data_dir, "meta", "graph.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["version"] == "0.3"
    assert meta["node_count"] == 2


def test_data_dir_structure(tmp_path):
    """保存后 data/ 目录结构完整。"""
    data_dir = os.path.join(tmp_path, "data")
    g = MGraph()
    g.add_node(Node("hello", kind="document", content="world", mg=g))

    board = QuestBoard()
    operators = {"test": Operator("test", next(iter(g.V)))}

    save_graph(g, board, operators, data_dir)

    # 顶层 .md 文件
    assert os.path.isfile(os.path.join(data_dir, "hello.md"))

    # meta 文件
    meta_files = os.listdir(os.path.join(data_dir, "meta"))
    for fname in ["edges.json", "graph.json", "operators.json",
                   "quest_board.json", "tags.json"]:
        assert fname in meta_files, f"missing meta/{fname}"
