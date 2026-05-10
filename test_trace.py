"""Phase 2: AnswerTrace 绑定测试。"""
from mgraph import MGraph, Node
from questnode import AnswerTrace, QuestNode
from quest_board import QuestBoard
from operators import Operator


def _make_graph():
    g = MGraph()
    g.add_node(Node("placeholder", mg=g))
    return g


def test_answer_trace_dataclass():
    trace = AnswerTrace(
        quest_name="quest_0",
        answer_index=0,
        answerer_id="bob",
    )
    assert trace.quest_name == "quest_0"
    assert trace.answer_index == 0
    assert trace.answerer_id == "bob"
    assert trace.node_names == []
    assert trace.edge_refs == []
    assert trace.score is None
    assert trace.feedback_applied is False


def test_submit_answer_with_trace():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)

    trace = AnswerTrace(quest_name=quest.name, answer_index=-1, answerer_id="bob")
    idx = board.submit_answer(quest, "bob", "answer_text", trace=trace)

    assert idx == 0
    assert quest.answers[idx] == "answer_text"
    assert quest.from_ids[idx] == "bob"
    assert quest.scores[idx] is None
    assert quest.answer_traces[idx] is not None
    assert quest.answer_traces[idx].answer_index == 0
    assert quest.answer_traces[idx].answerer_id == "bob"


def test_submit_answer_without_trace():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)

    idx = board.submit_answer(quest, "bob", "answer_text")

    assert quest.answer_traces[idx] is None


def test_trace_index_alignment():
    """Multiple answers — traces align by index with answers/from_ids/scores."""
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)

    # bob answers first
    board.submit_answer(quest, "bob", "bob_ans",
                        trace=AnswerTrace(quest.name, -1, "bob"))
    # carol answers second
    board.submit_answer(quest, "carol", "carol_ans",
                        trace=AnswerTrace(quest.name, -1, "carol"))

    assert len(quest.answers) == 2
    assert len(quest.answer_traces) == 2
    assert quest.answer_traces[0].answerer_id == "bob"
    assert quest.answer_traces[1].answerer_id == "carol"
    assert quest.answer_traces[0].answer_index == 0
    assert quest.answer_traces[1].answer_index == 1


def test_answer_quest_creates_trace():
    """Operator.answer_quest() creates a basic trace automatically."""
    g = MGraph()
    anchor = g.add_node(Node("op_bob", mg=g))
    op = Operator("bob", anchor)

    board = QuestBoard()
    quest = board.post("alice", "will bob answer?", g)

    idx = op.answer_quest(quest, board, g)

    # The trace was stored
    trace = quest.answer_traces[idx]
    assert trace is not None
    assert trace.answerer_id == "bob"
    assert trace.quest_name == quest.name
    assert trace.answer_index == idx
