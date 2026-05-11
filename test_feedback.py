"""Phase 5: 评分后整条路径反馈测试。"""
from mgraph import MGraph, Node, binResponse
from questnode import AnswerNode, AnswerTrace, QuestNode
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


def _get_trace(quest):
    """从 quest 的第一个 AnswerNode 获取 trace。"""
    answers = quest.get_answers()
    assert len(answers) > 0
    return answers[0].trace


def test_positive_feedback_on_trace_edges():
    """avg > 80 -> 路径上所有边收到正反馈 (stk 末尾 +)。"""
    g, op, quest, board = _setup_quest_with_trace()

    op.score_answer(quest, "bob", 90, 85, g, board)

    trace = _get_trace(quest)
    assert trace.feedback_applied

    for src_name, _ in trace.edge_refs:
        src_node = next(n for n in g.V if n.name == src_name)
        assert len(src_node.stk) > 0
        assert src_node.stk[-1].reaction is True


def test_negative_feedback_on_trace_edges():
    """avg <= 80 -> 路径上所有边收到负反馈 (stk 末尾 -)。"""
    g, op, quest, board = _setup_quest_with_trace()

    op.score_answer(quest, "bob", 70, 60, g, board)

    trace = _get_trace(quest)
    assert trace.feedback_applied

    for src_name, _ in trace.edge_refs:
        src_node = next(n for n in g.V if n.name == src_name)
        assert len(src_node.stk) > 0
        assert src_node.stk[-1].reaction is False


def test_no_duplicate_feedback():
    """同一答案重复评分不重复写入 stk。"""
    g, op, quest, board = _setup_quest_with_trace()

    op.score_answer(quest, "bob", 90, 85, g, board)
    stk_len_after_first = len(next(n for n in g.V if n.name == "start").stk)

    op.score_answer(quest, "bob", 50, 50, g, board)

    trace = _get_trace(quest)
    assert trace.feedback_applied
    stk_len_after_second = len(next(n for n in g.V if n.name == "start").stk)
    assert stk_len_after_second == stk_len_after_first


def test_no_trace_skips_gracefully():
    """答案没有 trace 时，score_answer 不崩溃。"""
    g = MGraph()
    n0 = g.add_node(Node("content_a", mg=g))
    n1 = g.add_node(Node("content_b", mg=g))

    board = QuestBoard()
    quest = board.post("alice", "q?", g)
    board.submit_answer(quest, "bob", "answer", g)  # 没有 trace

    op = Operator("alice", n0)
    op.score_answer(quest, "bob", 80, 80, g, board)


def test_edge_refs_empty_skips_gracefully():
    """trace 存在但 edge_refs 为空，不崩溃也不写 stk。"""
    g = MGraph()
    n0 = g.add_node(Node("content_a", mg=g))
    op = Operator("bob", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)

    trace = AnswerTrace(quest.name, -1, "bob", node_names=["content_a"])
    board.submit_answer(quest, "bob", "ans", g, trace=trace)

    op.score_answer(quest, "bob", 90, 85, g, board)
    ans = quest.get_answer_by_id("bob")
    assert ans is not None
    assert ans.trace.feedback_applied
