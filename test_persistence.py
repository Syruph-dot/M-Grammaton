"""持久化层 data/ 目录格式测试。"""
import json
import os
from pathlib import Path

from mgraph import MGraph, Node, binResponse, compress_stk
from operators import Operator
from quest_board import QuestBoard
from questnode import AnswerNode, QuestNode, AnswerTrace
from persistence import (
    save_graph, load_graph, save_node,
    _node_to_md, _md_to_node,
)


def test_node_md_roundtrip(tmp_path):
    """Node -> .md -> Node 往返。"""
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
    """QuestNode -> .md -> QuestNode 往返（不包含答案列表）。"""
    g = MGraph()
    q = QuestNode("quest_x", quester_id="Alice", content="如何定义意识？")
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
    assert parent is None
    assert stk == []


def test_answernode_md_roundtrip(tmp_path):
    """AnswerNode -> .md -> AnswerNode 往返。"""
    g = MGraph()
    a = AnswerNode("q0_ans_Bob", answerer_id="Bob", quest_name="q0", content="答案是42")
    trace = AnswerTrace(
        quest_name="q0", answer_index=0, answerer_id="Bob",
        node_names=["A", "B"], edge_refs=[("A", "B")],
        score=80.0, feedback_applied=True,
    )
    a.trace = trace
    a.match_score = 85.0
    a.novelty_score = 70.0
    g.add_node(a)

    md = _node_to_md(a)
    assert "q0_ans_Bob" in md
    assert "kind: answer" in md
    assert "answerer_id" in md
    assert "Bob" in md
    assert "match_score" in md
    assert "trace" in md

    g2 = MGraph()
    a2, parent, stk = _md_to_node(md, g2)
    assert isinstance(a2, AnswerNode)
    assert a2.kind == "answer"
    assert a2.name == "q0_ans_Bob"
    assert a2.answerer_id == "Bob"
    assert a2.quest_name == "q0"
    assert a2.content.strip() == "答案是42"
    assert a2.match_score == 85.0
    assert a2.novelty_score == 70.0
    assert a2.trace is not None
    assert a2.trace.quest_name == "q0"
    assert a2.trace.node_names == ["A", "B"]
    assert a2.trace.edge_refs == [("A", "B")]
    assert a2.trace.feedback_applied is True
    assert parent is None


def test_roundtrip_preserves_all_state(tmp_path):
    """保存 -> 加载 -> 验证所有状态不丢（含 AnswerNode）。"""
    data_dir = os.path.join(tmp_path, "data")

    g = MGraph()
    n0 = g.add_node(Node("content_A", mg=g))
    n1 = g.add_node(Node("content_B", mg=g))
    n0.link_to(n1, 1.0)

    op_alice = Operator("alice", n0)
    op_bob = Operator("bob", n1)
    operators = {"alice": op_alice, "bob": op_bob}

    board = QuestBoard()
    quest = board.post("alice", "test question", g)
    op_bob.answer_quest(quest, board, g)
    op_alice.score_answer(quest, "bob", 85, 90, g, board)

    metadata = {"round": 5, "llm_model": "deepseek-v4-flash"}
    save_graph(g, board, operators, data_dir, metadata=metadata)

    # 验证目录结构
    meta_dir = os.path.join(data_dir, "meta")
    assert os.path.isfile(os.path.join(meta_dir, "graph.json"))
    assert os.path.isfile(os.path.join(meta_dir, "edges.json"))
    assert os.path.isfile(os.path.join(meta_dir, "operators.json"))
    assert os.path.isfile(os.path.join(meta_dir, "quest_board.json"))
    assert os.path.isfile(os.path.join(data_dir, "content_A.md"))
    assert os.path.isfile(os.path.join(data_dir, "content_B.md"))

    # 验证无 op_*.md 文件（锚点不持久化）
    op_files = list(Path(data_dir).glob("op_*.md"))
    assert len(op_files) == 0, f"should not have op_*.md files, found: {op_files}"

    # 加载
    import json as _json
    g2, board2, ops2, meta2, _ = load_graph(data_dir)

    # ── 验证图 ──
    assert len(g2.V) == len(g.V)
    names2 = {n.name for n in g2.V}
    assert quest.name in names2
    # 验证 AnswerNode 存在
    ans_nodes = [n for n in g2.V if isinstance(n, AnswerNode)]
    assert len(ans_nodes) == 1
    ans_loaded = ans_nodes[0]
    assert ans_loaded.answerer_id == "bob"
    assert ans_loaded.match_score == 85.0
    assert ans_loaded.novelty_score == 90.0

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

    # ── 验证 AnswerTrace 在 AnswerNode 上 ──
    assert ans_loaded.trace is not None
    assert ans_loaded.trace.answerer_id == "bob"

    # ── 验证 Operator ──
    assert set(ops2.keys()) == {"alice", "bob"}

    # ── 验证边权重 ──
    for e_orig in g.E:
        for e_loaded in g2.E:
            if (e_orig.source.name == e_loaded.source.name
                    and e_orig.target.name == e_loaded.target.name):
                assert abs(e_orig.value - e_loaded.value) < 1e-9

    # ── 验证 metadata ──
    assert meta2 is not None
    assert meta2["round"] == 5
    assert meta2["llm_model"] == "deepseek-v4-flash"
    # API key 不应保存
    assert "llm_api_key" not in meta2


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
    g2, _, _, _, _ = load_graph(data_dir)

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
    # 同符号长跑 -> 只保留最近 20
    long_run = [[True, f"n{i}"] for i in range(50)]
    result = compress_stk(long_run)
    assert len(result) == 20
    assert result[-1][1] == "n49"

    # 交替: 每 run 长度 1，不触发压缩，全保留
    alternating = []
    for i in range(30):
        alternating.append([True, f"p{i}"])
        alternating.append([False, f"n{i}"])
    result = compress_stk(alternating)
    assert len(result) == 60

    # 超 100 -> 截断尾部 50
    huge = []
    for sign in [True, False] * 60:
        huge.append([sign, "x"])
    assert len(huge) == 120
    result = compress_stk(huge)
    assert len(result) == 50

    # 空列表
    assert compress_stk([]) == []


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
    """保存后 data/ 目录结构完整，无锚点文件。"""
    data_dir = os.path.join(tmp_path, "data")
    g = MGraph()
    g.add_node(Node("hello", kind="document", content="world", mg=g))

    board = QuestBoard()
    operators = {"test": Operator("test", next(iter(g.V)))}

    save_graph(g, board, operators, data_dir)

    # 顶层 .md 文件
    assert os.path.isfile(os.path.join(data_dir, "hello.md"))

    # 无锚点文件
    op_files = list(Path(data_dir).glob("op_*.md"))
    assert len(op_files) == 0, f"should not have op_*.md files, found: {op_files}"

    # meta 文件
    meta_files = os.listdir(os.path.join(data_dir, "meta"))
    for fname in ["edges.json", "graph.json", "operators.json",
                   "quest_board.json", "tags.json"]:
        assert fname in meta_files, f"missing meta/{fname}"
