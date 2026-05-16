from material_context import (
    SUMMARY_HARD_LIMIT_CHARS,
    SUMMARY_METADATA_KEY,
    SUMMARY_SUBSTITUTION_PROBABILITY,
    build_summary_prompt,
    choose_answer_materials,
    content_hash,
    format_material_context,
    material_refs_from_nodes,
    normalize_summary_text,
    store_summary,
    summary_is_stale,
)
from mgraph import Node


class FixedRandom:
    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_build_summary_prompt_requires_short_chinese_summary():
    node = Node("n1", content="这是需要摘要的原文材料。")
    messages = build_summary_prompt(node)

    assert messages[0]["role"] == "system"
    assert "不超过50字" in messages[0]["content"]
    assert "只输出摘要正文" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "这是需要摘要的原文材料" in messages[1]["content"]


def test_normalize_summary_text_hard_caps_at_120_chars():
    raw = "  " + ("甲" * (SUMMARY_HARD_LIMIT_CHARS + 20)) + "\n"
    assert normalize_summary_text(raw) == "甲" * SUMMARY_HARD_LIMIT_CHARS


def test_store_summary_records_current_content_hash_and_staleness():
    node = Node("n1", content="原文内容")
    stored = store_summary(node, " 摘要内容 ", model="deepseek-v4-flash", now=123.0)

    assert stored["text"] == "摘要内容"
    assert stored["model"] == "deepseek-v4-flash"
    assert stored["content_hash"] == content_hash("原文内容")
    assert stored["updated_at"] == 123.0
    assert node.metadata[SUMMARY_METADATA_KEY] == stored
    assert summary_is_stale(node) is False

    node.content = "原文内容已变化"
    assert summary_is_stale(node) is True


def test_material_refs_exclude_nodes_without_content_and_attach_valid_summary():
    with_summary = Node("with_summary", content="完整原文")
    with_summary.title = "标题"
    store_summary(with_summary, "短摘要", model="m", now=1.0)
    empty = Node("empty", content="")

    refs = material_refs_from_nodes([with_summary, empty])

    assert len(refs) == 1
    assert refs[0]["node"] == "with_summary"
    assert refs[0]["title"] == "标题"
    assert refs[0]["full_text"] == "完整原文"
    assert refs[0]["summary_text"] == "短摘要"
    assert refs[0]["content_hash"] == content_hash("完整原文")


def test_choose_answer_materials_uses_15_percent_probability_but_keeps_one_full():
    first = Node("first", content="第一段原文")
    second = Node("second", content="第二段原文")
    store_summary(first, "第一摘要", model="m", now=1.0)
    store_summary(second, "第二摘要", model="m", now=1.0)
    refs = material_refs_from_nodes([first, second])

    chosen = choose_answer_materials(
        refs,
        rng=FixedRandom([0.01, 0.01]),
        summary_probability=SUMMARY_SUBSTITUTION_PROBABILITY,
    )

    assert [item["mode"] for item in chosen] == ["full", "summary"]
    assert chosen[0]["text"] == "第一段原文"
    assert chosen[1]["text"] == "第二摘要"


def test_single_material_is_always_full_even_when_summary_exists():
    node = Node("solo", content="唯一原文")
    store_summary(node, "唯一摘要", model="m", now=1.0)

    chosen = choose_answer_materials(
        material_refs_from_nodes([node]),
        rng=FixedRandom([0.01]),
    )

    assert len(chosen) == 1
    assert chosen[0]["mode"] == "full"
    assert chosen[0]["text"] == "唯一原文"


def test_format_material_context_marks_full_and_summary_modes():
    full = {
        "node": "n1",
        "title": "材料一",
        "mode": "full",
        "text": "完整内容",
        "content_hash": "h1",
        "summary_hash": None,
    }
    summary = {
        "node": "n2",
        "title": "材料二",
        "mode": "summary",
        "text": "摘要内容",
        "content_hash": "h2",
        "summary_hash": "s2",
    }

    text = format_material_context([full, summary])

    assert "【材料A｜全文｜材料一】" in text
    assert "完整内容" in text
    assert "【材料B｜摘要｜材料二】" in text
    assert "摘要内容" in text
