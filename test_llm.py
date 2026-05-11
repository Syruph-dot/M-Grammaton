"""Phase 8: LLM 出题/答题/评分测试。"""
from mgraph import MGraph, Node
from operators import Operator
from quest_board import QuestBoard
from questnode import AnswerNode
from prompts import (
    build_answer_prompt,
    build_question_prompt,
    build_score_prompt,
    format_question_text,
    parse_question_json,
    parse_score_json,
)


# ── 出题 prompt ──────────────────────────────────


def test_build_question_prompt_structure():
    messages = build_question_prompt("Alice", "材料内容……")
    assert len(messages) == 2
    assert "Alice" in messages[0]["content"]
    assert "材料内容" in messages[1]["content"]
    assert "JSON" in messages[0]["content"] or "json" in messages[1]["content"]


def test_format_question_text():
    qdata = {
        "problem_theme": "主题理解",
        "problem_introduction": "请阅读材料回答问题。",
        "problems": ["问题一", "问题二"],
    }
    text = format_question_text(qdata)
    assert "请阅读材料回答问题。" in text
    assert "1. 问题一" in text
    assert "2. 问题二" in text


def test_parse_question_json():
    raw = '{"problem_theme": "主题", "problems": ["q1", "q2"]}'
    result = parse_question_json(raw)
    assert result is not None
    assert result["problem_theme"] == "主题"
    assert len(result["problems"]) == 2


def test_parse_question_json_with_code_block():
    raw = '```json\n{"problem_theme": "T", "problems": ["q"]}\n```'
    result = parse_question_json(raw)
    assert result is not None
    assert result["problem_theme"] == "T"


def test_parse_question_json_invalid():
    assert parse_question_json("not json") is None
    assert parse_question_json("") is None


def test_parse_score_json():
    raw = '{"score_match": 85, "score_novelty": 70, "reasoning": "好"}'
    result = parse_score_json(raw)
    assert result is not None
    assert result["score_match"] == 85
    assert result["score_novelty"] == 70


# ── ask: 出题 ────────────────────────────────────


def test_ask_with_content():
    """提供 content 时直接使用。"""
    g = MGraph()
    n0 = g.add_node(Node("content_x", mg=g))
    op = Operator("alice", n0)
    board = QuestBoard()
    quest = op.ask(g, board, "自定义问题")
    assert quest.content == "自定义问题"


def test_ask_without_content_and_no_llm_raises():
    """没有 llm_client 且没有 content 时报错。"""
    g = MGraph()
    n0 = g.add_node(Node("content_x", mg=g))
    op = Operator("alice", n0)
    board = QuestBoard()
    import pytest
    with pytest.raises(ValueError, match="ask requires content"):
        op.ask(g, board)


# ── 答题 prompt ──────────────────────────────────


def test_build_answer_prompt_returns_correct_structure():
    """build_answer_prompt 返回 system + user 消息结构。"""
    messages = build_answer_prompt("Bob", "什么是 consciousness？", "材料内容……")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Bob" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "consciousness" in messages[1]["content"]
    assert "材料内容" in messages[1]["content"]


# ── answer_quest ─────────────────────────────────


def test_answer_quest_fallback_without_llm():
    """没有 llm_client 时，使用规则模板。"""
    g = MGraph()
    n0 = g.add_node(Node("content_b", mg=g))
    op = Operator("bob", n0)
    board = QuestBoard()
    quest = board.post("alice", "test question?", g)
    ans = op.answer_quest(quest, board, g)
    assert isinstance(ans, AnswerNode)
    assert "bob answers" in ans.content


def test_answer_quest_with_explicit_text():
    """传入 answer_text 时直接使用。"""
    g = MGraph()
    n0 = g.add_node(Node("content_b", mg=g))
    op = Operator("bob", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)
    ans = op.answer_quest(quest, board, g, answer_text="自定义答案")
    assert ans.content == "自定义答案"


# ── 评分 prompt ──────────────────────────────────


def test_build_score_prompt_structure():
    messages = build_score_prompt("测试问题？", "测试答案。", "参考答案。")
    assert len(messages) == 2
    assert "score_match" in messages[0]["content"]
    assert "score_novelty" in messages[0]["content"]
    assert "测试问题" in messages[1]["content"]
    assert "测试答案" in messages[1]["content"]
    assert "参考答案" in messages[1]["content"]


def test_build_score_prompt_without_reference():
    """没有参考答案时，prompt 不包含参考内容。"""
    messages = build_score_prompt("问题", "答案")
    assert "参考答案" not in messages[1]["content"]


# ── score_answer ─────────────────────────────────


def test_score_answer_with_explicit_scores():
    """显式传入评分时，直接使用。"""
    g = MGraph()
    n0 = g.add_node(Node("content_a", mg=g))
    alice = Operator("alice", n0)
    bob = Operator("bob", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)
    ans = bob.answer_quest(quest, board, g)

    alice.score_answer(quest, "bob", 80, 70, g, board)
    assert ans.match_score == 80
    assert ans.novelty_score == 70


def test_score_answer_without_scores_and_no_llm_raises():
    """没有 llm_client 且没有显式评分时报错。"""
    g = MGraph()
    n0 = g.add_node(Node("content_a", mg=g))
    op = Operator("alice", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)
    op.answer_quest(quest, board, g, answer_text="dummy")

    import pytest
    with pytest.raises(ValueError, match="score_answer requires"):
        op.score_answer(quest, "alice", graph=g, board=board)
