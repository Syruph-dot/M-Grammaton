from dataclasses import dataclass, field
from mgraph import Node, Edge
from random import randint


@dataclass
class AnswerTrace:
    """一条答案绑定的阅读路径。

    由 Phase 3 read_for_quest() 填充，绑定到 AnswerNode.trace。
    """
    quest_name: str
    answer_index: int
    answerer_id: str
    node_names: list[str] = field(default_factory=list)
    edge_refs: list[tuple[str, str]] = field(default_factory=list)
    score: float | None = None
    feedback_applied: bool = False


class QuestNode(Node):
    """问题节点 —— 仅持有问题本身。答案由独立的 AnswerNode 承载。"""

    def __init__(self, name: str, quester_id: str, content: str = "This is a test quest node{}".format(randint(0, 1000)),
                 parent_quest: str | None = None, depth: int = 0):
        super().__init__(name, kind="quest")
        self.name = name
        self.quester_id = quester_id
        self.content = content
        self.parent_quest = parent_quest
        self.depth = depth

    def get_answers(self):
        """返回所有链接到此 quest 的 AnswerNode（按 outlinks 顺序）。"""
        return [link.target for link in self.outlinks if isinstance(link.target, AnswerNode)]

    def get_answer_by_id(self, answerer_id: str):
        """按 answerer_id 查找 AnswerNode。"""
        for link in self.outlinks:
            target = link.target
            if isinstance(target, AnswerNode) and target.answerer_id == answerer_id:
                return target
        return None


class AnswerNode(Node):
    """答案节点 —— 一条回答作为一等图节点存在。

    与阅读路径节点建立双向链接（A ↔ answer, B ↔ answer, C ↔ answer）。
    """

    def __init__(self, name: str, answerer_id: str, quest_name: str, content: str = ""):
        super().__init__(name, kind="answer")
        self.answerer_id = answerer_id
        self.quest_name = quest_name
        self.content = content
        self.trace: AnswerTrace | None = None
        self.match_score: float | None = None
        self.novelty_score: float | None = None
