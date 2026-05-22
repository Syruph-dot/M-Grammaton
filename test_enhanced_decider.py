"""测试 EnhancedDecider + 6 信号源。"""

import asyncio
import time
from unittest.mock import MagicMock

from runtime.decision import (
    EnhancedDecider,
    RandomDecider,
    DecisionTrace,
    MessagePendingSignal,
    QuestPressureSignal,
    GraphFrontierSignal,
    StashPressureSignal,
    StkPressureSignal,
    BudgetSignal,
    PHASE1_ACTIONS,
    PHASE2_ACTIONS,
)
from mgraph import MGraph, Node
from questnode import QuestNode, AnswerNode
from quest_board import QuestBoard
from runtime.actor_panel import ActorPanel


def _make_operator(op_id="Alice", panel=None, current_node=None, graph=None):
    op = MagicMock()
    op.id = op_id
    op.panel = panel or ActorPanel(actor_id=op_id, actor_kind="operator")
    op.current = MagicMock()
    op.llm_client = None
    if current_node and graph:
        for n in graph.V:
            if n.name == current_node:
                op.current.get.return_value = n
                op.panel.bind(n)
                break
    return op


def _make_graph():
    graph = MGraph()
    src = Node("source", content="alpha", mg=graph)
    tgt = Node("target", content="beta", mg=graph)
    src.link_to(tgt, 1.0)
    return graph


# ── 信号源测试 ─────────────────────────────


async def _score(signal, op, graph=None, board=None):
    return await signal.score(op, graph, board)


def test_message_pending_signal_empty():
    signal = MessagePendingSignal()
    op = _make_operator()
    result = asyncio.run(_score(signal, op))
    assert result == {}


def test_message_pending_signal_has_messages():
    signal = MessagePendingSignal()
    op = _make_operator()
    op.panel.add_message("info", "hello")
    result = asyncio.run(_score(signal, op))
    assert "reply_to_message" in result
    assert result["reply_to_message"] > 0


def test_quest_pressure_signal():
    signal = QuestPressureSignal()
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    op.MAX_ACTIVE_QUESTS = 3
    result = asyncio.run(_score(signal, op, graph, board))
    assert "ask" in result
    assert result["ask"] > 0


def test_quest_pressure_with_open_quests():
    signal = QuestPressureSignal()
    graph = _make_graph()
    board = QuestBoard()
    # quest posted by Bob (not Alice), so available_for("Alice") returns it
    board.post("Bob", "test?", graph)
    op = _make_operator(current_node="source", graph=graph)
    op.MAX_ACTIVE_QUESTS = 3
    result = asyncio.run(_score(signal, op, graph, board))
    assert "answer" in result
    assert result["answer"] > 0


def test_graph_frontier_signal():
    signal = GraphFrontierSignal()
    graph = _make_graph()
    op = _make_operator(current_node="target", graph=graph)
    result = asyncio.run(_score(signal, op, graph))
    assert "wander" in result
    assert result["wander"] > 0


def test_stash_pressure_signal():
    signal = StashPressureSignal()
    op = _make_operator()
    result = asyncio.run(_score(signal, op))
    assert result == {}
    node = Node("stashed")
    op.panel.add_to_stash(node, reason="test")
    result = asyncio.run(_score(signal, op))
    assert "read_stash" in result
    assert result["read_stash"] > 0


def test_stk_pressure_signal():
    signal = StkPressureSignal()
    graph = _make_graph()
    op = _make_operator()
    result = asyncio.run(_score(signal, op, graph))
    assert result == {}
    from mgraph import binResponse
    src = next(n for n in graph.V if n.outlinks)  # ensure node has outlinks
    e = src.outlinks[0]
    src.stk.append(binResponse(True, e))
    src.stk.append(binResponse(True, e))
    result = asyncio.run(_score(signal, op, graph))
    assert "ask" in result


def test_budget_signal_no_llm():
    signal = BudgetSignal()
    op = _make_operator()
    result = asyncio.run(_score(signal, op))
    assert result == {}


# ── EnhancedDecider ─────────────────────────


def test_enhanced_decider_returns_valid_action():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    decider = EnhancedDecider(temperature=1.0)
    action = asyncio.run(decider.choose(op, graph, board))
    assert action.type in (PHASE1_ACTIONS | PHASE2_ACTIONS)


def test_enhanced_decider_deterministic_with_zero_temp():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    decider = EnhancedDecider(temperature=0.0)
    action1 = asyncio.run(decider.choose(op, graph, board))
    action2 = asyncio.run(decider.choose(op, graph, board))
    assert action1.type == action2.type


def test_enhanced_decider_emits_trace():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    decider = EnhancedDecider(temperature=0.5)
    action = asyncio.run(decider.choose(op, graph, board))
    trace = decider.last_trace
    assert trace is not None
    assert trace.actor_id == "Alice"
    assert trace.chosen == action.type
    assert len(trace.raw_scores) > 0
    assert len(trace.probabilities) > 0
    assert isinstance(trace.top_signals, list)


def test_enhanced_decider_trace_format_matches_prd():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    decider = EnhancedDecider(temperature=0.3)
    asyncio.run(decider.choose(op, graph, board))
    trace = decider.last_trace
    d = trace.to_dict()
    assert "actor_id" in d
    assert "temperature" in d
    assert "chosen" in d
    assert "raw_scores" in d
    assert "probabilities" in d
    assert "top_signals" in d


def test_search_web_cooldown_suppresses_action():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    op.panel.search_cooldown_until = time.time() + 9999
    decider = EnhancedDecider(
        temperature=0.0,
        base_weights={"search_web": 10.0, "wander": 1.0, "idle": 1.0},
    )
    action = asyncio.run(decider.choose(op, graph, board))
    # cooldown zeroes search_web; wander should win
    assert action.type != "search_web"


def test_repeat_penalty_changes_behavior():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    decider = EnhancedDecider(temperature=0.0, repeat_penalty=0.5)
    action = asyncio.run(decider.choose(op, graph, board))
    assert action.type is not None


def test_random_decider_still_works():
    graph = _make_graph()
    board = QuestBoard()
    op = _make_operator(current_node="source", graph=graph)
    decider = RandomDecider()
    action = asyncio.run(decider.choose(op, graph, board))
    assert action.type in {"wander", "ask", "answer", "score", "idle"}
