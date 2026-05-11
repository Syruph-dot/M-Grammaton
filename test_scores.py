"""Phase 1: 百分制评分边界测试 — 双维度 [匹配度, 新颖度]。"""
from questnode import AnswerNode, QuestNode
from quest_board import QuestBoard
from mgraph import MGraph, Node


def _make_graph():
    g = MGraph()
    g.add_node(Node("placeholder", mg=g))
    return g


def test_set_score_accepts_valid():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    ans = board.submit_answer(quest, "bob", "answer", g)

    board.set_score(ans, 80, 90)
    assert ans.match_score == 80
    assert ans.novelty_score == 90

    board.set_score(ans, 80.1, 0)
    assert ans.match_score == 80.1
    assert ans.novelty_score == 0

    board.set_score(ans, 100, 100)
    assert ans.match_score == 100
    assert ans.novelty_score == 100


def test_set_score_rejects_out_of_range():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    ans = board.submit_answer(quest, "bob", "answer", g)

    cases = [(-1, 50), (101, 50), (50, -1), (50, 101)]
    for match_s, novel_s in cases:
        try:
            board.set_score(ans, match_s, novel_s)
            assert False, f"should have raised for ({match_s}, {novel_s})"
        except ValueError:
            pass


def test_scores_default_none():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    ans = board.submit_answer(quest, "bob", "answer_bob", g)

    assert ans.match_score is None
    assert ans.novelty_score is None

    board.set_score(ans, 86.0, 72.0)
    assert ans.match_score == 86.0
    assert ans.novelty_score == 72.0


def test_threshold_uses_average():
    """Verify score_answer reaction uses avg of both dimensions."""
    from operators import Operator
    from mgraph import MGraph as MG, Node as Nd

    g = MG()
    n0 = g.add_node(Nd("content_a", mg=g))
    n1 = g.add_node(Nd("content_b", mg=g))
    op = Operator("alice", n0)
    board = QuestBoard()

    quest = board.post("alice", "q?", g)
    ans_bob = board.submit_answer(quest, "bob", "ans", g)
    op.score_answer(quest, "bob", 90, 85, g, board)
    assert ans_bob.match_score == 90
    assert ans_bob.novelty_score == 85

    quest2 = board.post("alice", "q2?", g)
    ans2 = board.submit_answer(quest2, "bob", "ans2", g)
    op.score_answer(quest2, "bob", 70, 60, g, board)
    assert ans2.match_score == 70
    assert ans2.novelty_score == 60

    quest3 = board.post("alice", "q3?", g)
    ans3 = board.submit_answer(quest3, "bob", "ans3", g)
    op.score_answer(quest3, "bob", 100, 65, g, board)
    assert ans3.match_score == 100
    assert ans3.novelty_score == 65
