"""Phase 1: 百分制评分边界测试。"""
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

    board.set_score(quest, "bob", 80)
    assert quest.scores[-1] == 80

    board.set_score(quest, "bob", 80.1)
    assert quest.scores[-1] == 80.1

    board.set_score(quest, "bob", 100)
    assert quest.scores[-1] == 100

    board.set_score(quest, "bob", 0)
    assert quest.scores[-1] == 0


def test_set_score_rejects_out_of_range():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    board.submit_answer(quest, "bob", "answer")

    try:
        board.set_score(quest, "bob", -1)
        assert False, "should have raised"
    except ValueError:
        pass

    try:
        board.set_score(quest, "bob", 101)
        assert False, "should have raised"
    except ValueError:
        pass


def test_scores_type_is_none_or_float():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)
    board.submit_answer(quest, "bob", "answer_bob")

    # submit_answer appends None
    assert quest.scores[-1] is None

    board.set_score(quest, "bob", 86.0)
    assert isinstance(quest.scores[-1], float)
