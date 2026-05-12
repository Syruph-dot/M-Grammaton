"""消息类型 —— Operator Runtime 内部通信的消息格式。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClockTick:
    round: int


@dataclass(frozen=True)
class QuestPosted:
    quest_id: str
    quester_id: str
    content: str


@dataclass(frozen=True)
class AnswerSubmitted:
    quest_id: str
    answerer_id: str


@dataclass(frozen=True)
class AnswerScored:
    quest_id: str
    answerer_id: str
    match_score: float
    novelty_score: float