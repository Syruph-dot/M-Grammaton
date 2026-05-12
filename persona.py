"""MBTI 人格系统 —— 为每个 Operator 赋予差异化认知风格。"""

from dataclasses import dataclass
import random

# ── MBTI 各维度描述 ──────────────────────────────

MBTI_DIMENSIONS = {
    "E": {
        "label": "外向",
        "question": "偏好互动讨论式问题，喜欢从多角度切入",
        "answer": "表达活跃，善于联想和发散",
        "score": "鼓励参与，倾向于给略高的分数",
    },
    "I": {
        "label": "内向",
        "question": "偏好需要深入独立思考的问题",
        "answer": "思考周密，用词谨慎，回答精炼",
        "score": "标准严格，倾向于保守给分",
    },
    "S": {
        "label": "实感",
        "question": "偏好基于具体事实和文本细节的问题",
        "answer": "注重文本证据，回答紧扣原文具体表述",
        "score": "看重答案与材料的匹配度，对凭空发挥敏感",
    },
    "N": {
        "label": "直觉",
        "question": "偏好抽象概念、隐喻和可能性空间的问题",
        "answer": "擅长抽象概括和延伸，常读出字面之外的意涵",
        "score": "看重答案的洞察力和格局",
    },
    "T": {
        "label": "思考",
        "question": "偏好逻辑分析、因果推理型问题",
        "answer": "逻辑严密，条理清晰，偏好结构化表达",
        "score": "客观理性，就事论事，不受情感影响",
    },
    "F": {
        "label": "情感",
        "question": "偏好价值判断、情感共鸣型问题",
        "answer": "注重人文关怀与情感价值，常关注人物动机",
        "score": "考虑回答者的用心和态度",
    },
    "J": {
        "label": "判断",
        "question": "偏好有明确结论或立场的问题",
        "answer": "结论明确，结构完整，有收束感",
        "score": "偏好干脆利落、有立场的回答",
    },
    "P": {
        "label": "感知",
        "question": "偏好开放探索型、无标准答案的问题",
        "answer": "灵活开放，接受多种可能性，留有余地",
        "score": "包容不同角度，不轻易否定非常规回答",
    },
}

_ALL_TYPES = [
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]


def _compose_style(mbti: str, field: str) -> str:
    """从 MBTI 四维组合出某领域的行为描述。"""
    parts = []
    for letter in mbti:
        dim = MBTI_DIMENSIONS.get(letter)
        if dim:
            parts.append(dim[field])
    return "；".join(parts)


@dataclass
class Persona:
    """Operator 人格配置。"""
    mbti: str
    question_style: str = ""
    answer_style: str = ""
    score_style: str = ""

    def __post_init__(self):
        if not self.question_style:
            self.question_style = _compose_style(self.mbti, "question")
        if not self.answer_style:
            self.answer_style = _compose_style(self.mbti, "answer")
        if not self.score_style:
            self.score_style = _compose_style(self.mbti, "score")

    def to_dict(self) -> dict:
        return {"mbti": self.mbti, "question_style": self.question_style,
                "answer_style": self.answer_style, "score_style": self.score_style}

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            mbti=data.get("mbti", "INTJ"),
            question_style=data.get("question_style", ""),
            answer_style=data.get("answer_style", ""),
            score_style=data.get("score_style", ""),
        )

    @property
    def label(self) -> str:
        """MBTI 标签 + 中文描述，如 'INTJ（内向-直觉-思考-判断）'"""
        dims = []
        for letter in self.mbti:
            dim = MBTI_DIMENSIONS.get(letter)
            dims.append(dim["label"] if dim else letter)
        return f"{self.mbti}（{'‐'.join(dims)}）"


def random_persona() -> Persona:
    """随机生成一个 MBTI 人格。"""
    mbti = random.choice(_ALL_TYPES)
    return Persona(mbti=mbti)


def all_types() -> list[str]:
    """返回所有 16 种 MBTI 类型列表。"""
    return list(_ALL_TYPES)
