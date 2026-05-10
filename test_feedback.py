"""Phase 5: 评分后整条路径反馈测试。"""
from mgraph import MGraph, Node, binResponse
from questnode import AnswerTrace, QuestNode
from quest_board import QuestBoard
from operators import Operator


def _setup_quest_with_trace(answerer="bob"):
    """创建一个带阅读路径的 quest-answer-trace 场景。"""
    g = MGraph()
    n0 = g.add_node(Node("start", mg=g))
    n1 = g.add_node(Node("mid", mg=g))
    n2 = g.add_node(Node("end", mg=g))
    n0.link_to(n1, 1.0)
    n1.link_to(n2, 1.0)

    op = Operator(answerer, n0)
    board = QuestBoard()
    quest = board.post("alice", "question?", g)
    op.answer_quest(quest, board, g)

    return g, op, quest, board


def test_positive_feedback_on_trace_edges():
    """avg > 80 → 路径上所有边收到正反馈 (stk 末尾 +)。"""
    g, op, quest, board = _setup_quest_with_trace()

    # 用 Operator 自己的方法评分（这里是 asker 视角，但直接调 score_answer 测试逻辑）
    op.score_answer(quest, "bob", 90, 85, g, board)

    trace = quest.answer_traces[0]
    assert trace.feedback_applied

    # path_edges 中的每条边，源节点的 stk 末尾应为正反馈
    for src_name, _ in trace.edge_refs:
        src_node = next(n for n in g.V if n.name == src_name)
        assert len(src_node.stk) > 0
        assert src_node.stk[-1].reaction is True


def test_negative_feedback_on_trace_edges():
    """avg <= 80 → 路径上所有边收到负反馈 (stk 末尾 -)。"""
    g, op, quest, board = _setup_quest_with_trace()

    op.score_answer(quest, "bob", 70, 60, g, board)

    trace = quest.answer_traces[0]
    assert trace.feedback_applied

    for src_name, _ in trace.edge_refs:
        src_node = next(n for n in g.V if n.name == src_name)
        assert len(src_node.stk) > 0
        assert src_node.stk[-1].reaction is False


def test_no_duplicate_feedback():
    """同一答案重复评分不重复写入 stk。"""
    g, op, quest, board = _setup_quest_with_trace()

    # 第一次评分
    op.score_answer(quest, "bob", 90, 85, g, board)
    stk_len_after_first = len(next(n for n in g.V if n.name == "start").stk)

    # 第二次评分 — 应被 feedback_applied 拦住
    op.score_answer(quest, "bob", 50, 50, g, board)

    trace = quest.answer_traces[0]
    assert trace.feedback_applied  # 仍是 True
    stk_len_after_second = len(next(n for n in g.V if n.name == "start").stk)
    assert stk_len_after_second == stk_len_after_first


def test_no_trace_skips_gracefully():
    """答案没有 trace 时，score_answer 不崩溃。"""
    g = MGraph()
    g.add_node(Node("op_alice", mg=g))
    g.add_node(Node("op_bob", mg=g))

    board = QuestBoard()
    quest = board.post("alice", "q?", g)
    board.submit_answer(quest, "bob", "answer")  # 没有 trace

    op = Operator("alice")
    # 不会崩溃
    op.score_answer(quest, "bob", 80, 80, g, board)


def test_edge_refs_empty_skips_gracefully():
    """trace 存在但 edge_refs 为空，不崩溃也不写 stk。"""
    g = MGraph()
    anchor = g.add_node(Node("op_bob", mg=g))
    op = Operator("bob", anchor)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)

    # 手动提交没有边缘的 trace
    trace = AnswerTrace(quest.name, -1, "bob", node_names=["op_bob"])
    board.submit_answer(quest, "bob", "ans", trace=trace)

    # score_answer 应跳过，因为没有 path_edges
    op.score_answer(quest, "bob", 90, 85, g, board)
    assert quest.answer_traces[0].feedback_applied
