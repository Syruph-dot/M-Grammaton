from dataclasses import dataclass, field
from mgraph import Node, Edge
from random import randint


@dataclass
class AnswerTrace:
    """一条答案绑定的阅读路径。

    与 answers/from_ids/scores 按 index 对齐。
    node_names / edge_refs 由 Phase 3 read_for_quest() 填充。
    """
    quest_name: str
    answer_index: int
    answerer_id: str
    node_names: list[str] = field(default_factory=list)
    edge_refs: list[tuple[str, str]] = field(default_factory=list)
    score: float | None = None
    feedback_applied: bool = False


class QuestNode(Node):
    def __init__(self, name: str, quester_id: str, content: str = "This is a test quest node{}".format(randint(0, 1000))):
        super().__init__(name, kind="quest")
        self.name = name
        self.quester_id = quester_id
        self.content = content
        self.answers: list[str] = []
        self.scores: list[None | tuple[float, float]] = []  # [匹配度, 新颖度]
        self.from_ids: list[str] = []
        self.answer_traces: list[None | AnswerTrace] = []
