"""Phase 2: AnswerTrace 绑定测试。"""
from mgraph import MGraph, Node
from questnode import AnswerNode, AnswerTrace, QuestNode
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
    ans = board.submit_answer(quest, "bob", "answer_text", g, trace=trace)

    assert isinstance(ans, AnswerNode)
    assert ans.answerer_id == "bob"
    assert ans.content == "answer_text"
    assert ans.match_score is None
    assert ans.trace is not None
    assert ans.trace.answer_index == 0
    assert ans.trace.answerer_id == "bob"


def test_submit_answer_without_trace():
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)

    ans = board.submit_answer(quest, "bob", "answer_text", g)

    assert isinstance(ans, AnswerNode)
    assert ans.trace is None


def test_multiple_answers_order():
    """Multiple answers — each as independent AnswerNode."""
    board = QuestBoard()
    g = _make_graph()
    quest = board.post("alice", "test?", g)

    board.submit_answer(quest, "bob", "bob_ans", g,
                        trace=AnswerTrace(quest.name, -1, "bob"))
    board.submit_answer(quest, "carol", "carol_ans", g,
                        trace=AnswerTrace(quest.name, -1, "carol"))

    answers = quest.get_answers()
    assert len(answers) == 2
    assert answers[0].answerer_id == "bob"
    assert answers[1].answerer_id == "carol"
    assert answers[0].trace.answer_index == 0
    assert answers[1].trace.answer_index == 1


def test_answer_quest_creates_trace():
    """Operator.answer_quest() creates a trace with reading path data."""
    g = MGraph()
    n0 = g.add_node(Node("content_a", mg=g))
    op = Operator("bob", n0)

    board = QuestBoard()
    quest = board.post("alice", "will bob answer?", g)

    ans = op.answer_quest(quest, board, g)

    assert isinstance(ans, AnswerNode)
    assert ans.trace is not None
    assert ans.trace.answerer_id == "bob"
    assert ans.trace.quest_name == quest.name
    assert len(ans.trace.node_names) >= 1
    assert ans.trace.node_names[0] == "content_a"


def test_answer_quest_trace_has_edges_when_path_exists():
    """When the graph has edges, trace records the traversed path."""
    from mgraph import MGraph as MG, Node as Nd

    g = MG()
    n0 = g.add_node(Nd("start", mg=g))
    n1 = g.add_node(Nd("mid", mg=g))
    n2 = g.add_node(Nd("end", mg=g))
    n0.link_to(n1, 1.0)
    n1.link_to(n2, 1.0)

    op = Operator("reader", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)

    ans = op.answer_quest(quest, board, g)

    assert ans.trace is not None
    assert len(ans.trace.node_names) >= 2
    assert len(ans.trace.edge_refs) >= 1
    assert ans.trace.edge_refs[0] == ("start", "mid")


def test_answer_quest_trace_records_material_modes_with_at_least_one_full():
    g = MGraph()
    n0 = g.add_node(Node("content_a", content="A full text", mg=g))
    n1 = g.add_node(Node("content_b", content="B full text", mg=g))
    n0.link_to(n1, 1.0)
    from material_context import store_summary

    store_summary(n0, "A summary", model="m", now=1.0)
    store_summary(n1, "B summary", model="m", now=1.0)

    op = Operator("bob", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)

    ans = op.answer_quest(quest, board, g, answer_text="manual answer")

    assert ans.trace is not None
    assert len(ans.trace.materials) >= 1
    assert any(item["mode"] == "full" for item in ans.trace.materials)
    assert {item["node"] for item in ans.trace.materials}.issubset(
        set(ans.trace.node_names)
    )
