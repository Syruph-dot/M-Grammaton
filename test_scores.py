"""Phase 1: 百分制评分边界测试 — 双维度 [匹配度, 新颖度]。"""
from questnode import QuestNode
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
    board.submit_answer(quest, "bob", "answer")

    board.set_score(quest, "bob", 80, 90)
    assert quest.scores[-1] == (80, 90)

    board.set_score(quest, "bob", 80.1, 0)
    assert quest.scores[-1] == (80.1, 0)

    board.set_score(quest, "bob", 100, 100)
    assert quest.scores[-1] == (100, 100)


def test_set_score_rejects_out_of_range():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    board.submit_answer(quest, "bob", "answer")

    cases = [(-1, 50), (101, 50), (50, -1), (50, 101)]
    for match_s, novel_s in cases:
        try:
            board.set_score(quest, "bob", match_s, novel_s)
            assert False, f"should have raised for ({match_s}, {novel_s})"
        except ValueError:
            pass


def test_scores_type_is_none_or_tuple():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    board.submit_answer(quest, "bob", "answer_bob")

    # submit_answer appends None
    assert quest.scores[-1] is None

    board.set_score(quest, "bob", 86.0, 72.0)
    assert isinstance(quest.scores[-1], tuple)
    assert len(quest.scores[-1]) == 2
    assert quest.scores[-1][0] == 86.0
    assert quest.scores[-1][1] == 72.0


def test_threshold_uses_average():
    """Verify score_answer reaction uses avg of both dimensions."""
    from operators import Operator
    from mgraph import MGraph as MG, Node as Nd

    g = MG()
    g.add_node(Nd("op_alice", mg=g))
    g.add_node(Nd("op_bob", mg=g))
    op = Operator("alice")
    board = QuestBoard()

    # both high → avg > 80 → positive
    quest = board.post("alice", "q?", g)
    board.submit_answer(quest, "bob", "ans")
    op.score_answer(quest, "bob", 90, 85, g, board)
    assert quest.scores[-1] == (90, 85)

    # both low → avg <= 80 → negative
    quest2 = board.post("alice", "q2?", g)
    board.submit_answer(quest2, "bob", "ans2")
    op.score_answer(quest2, "bob", 70, 60, g, board)
    assert quest2.scores[-1] == (70, 60)

    # mixed: one high, one low → avg > 80 → positive
    quest3 = board.post("alice", "q3?", g)
    board.submit_answer(quest3, "bob", "ans3")
    op.score_answer(quest3, "bob", 100, 65, g, board)
    assert quest3.scores[-1] == (100, 65)
