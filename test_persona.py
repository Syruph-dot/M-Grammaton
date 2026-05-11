"""测试：MBTI 人格系统——persona.py + prompts.py 集成。"""

import random
from persona import Persona, random_persona, all_types, MBTI_DIMENSIONS
from prompts import _persona_block, build_question_prompt, build_answer_prompt, build_score_prompt


class TestPersona:
    def test_random_persona_creates_valid_mbti(self):
        """随机生成的人格必须包含有效的 MBTI 类型之一。"""
        valid = all_types()
        for _ in range(100):
            p = random_persona()
            assert p.mbti in valid, f"unexpected MBTI: {p.mbti}"

    def test_persona_has_all_styles(self):
        """人格必须包含三域风格描述。"""
        for mbti in all_types():
            p = Persona(mbti=mbti)
            assert p.question_style, f"{mbti} missing question_style"
            assert p.answer_style, f"{mbti} missing answer_style"
            assert p.score_style, f"{mbti} missing score_style"

    def test_persona_label_format(self):
        """标签格式为 'MBTI（维度1‐维度2‐维度3‐维度4）'。"""
        p = Persona(mbti="INTJ")
        assert p.label.startswith("INTJ（")
        assert p.label.endswith("）")

    def test_all_types_returns_16(self):
        """all_types() 返回 16 种类型。"""
        types = all_types()
        assert len(types) == 16
        assert "INTJ" in types
        assert "ESFP" in types

    def test_custom_persona_keeps_styles(self):
        """自定义风格描述不应被覆盖。"""
        p = Persona(mbti="INFP", question_style="自定义风格")
        assert p.question_style == "自定义风格"
        assert p.answer_style  # 自动生成
        assert p.score_style   # 自动生成

    def test_dimension_every_letter_covered(self):
        """所有 8 个 MBTI 字母都有对应的维度描述。"""
        for letter in "EINSFTJP":
            assert letter in MBTI_DIMENSIONS, f"missing dimension: {letter}"

    def test_random_is_reproducible(self):
        """随机生成应覆盖多种类型（统计：100 次应出现至少 4 种）。"""
        random.seed(42)
        types_seen = set()
        for _ in range(100):
            p = random_persona()
            types_seen.add(p.mbti)
        # 100 次随机至少出现 4 种不同 MBTI（概率 > 99.999%）
        assert len(types_seen) >= 4, f"only {len(types_seen)} types in 100 rolls"


class TestPersonaPromptInjection:
    def test_persona_block_contains_mbti(self):
        """_persona_block 应包含 MBTI 标记。"""
        block = _persona_block("INTJ", "question")
        assert "INTJ" in block
        assert "认知风格" in block

    def test_question_prompt_without_mbti(self):
        """不传 mbti 时保持原样。"""
        msgs = build_question_prompt("Alice", "测试上下文")
        assert "你的认知风格" not in msgs[0]["content"]
        assert "你的任务" in msgs[0]["content"]

    def test_question_prompt_with_mbti(self):
        """传 mbti 时注入认知风格。"""
        msgs = build_question_prompt("Alice", "测试上下文", mbti="INTJ")
        assert "你的认知风格" in msgs[0]["content"]
        assert "INTJ" in msgs[0]["content"]

    def test_answer_prompt_with_mbti(self):
        """答题 prompt 注入 MBTI。"""
        msgs = build_answer_prompt("Bob", "问题", "上下文", mbti="ENTP")
        assert "你的认知风格" in msgs[0]["content"]

    def test_score_prompt_with_mbti(self):
        """评分 prompt 注入 MBTI。"""
        msgs = build_score_prompt("问题", "答案", mbti="ISTJ")
        assert "你的认知风格" in msgs[0]["content"]

    def test_mbti_varies_by_type(self):
        """不同 MBTI 生成不同的风格描述。"""
        block_a = _persona_block("INTJ", "question")
        block_b = _persona_block("ENFP", "question")
        assert block_a != block_b

    def test_question_and_score_blocks_differ(self):
        """同一 MBTI 在不同域的风格描述不同。"""
        q = _persona_block("INTJ", "question")
        s = _persona_block("INTJ", "score")
        assert q != s
