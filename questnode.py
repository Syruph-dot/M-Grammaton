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
    materials: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "quest_name": self.quest_name,
            "answer_index": self.answer_index,
            "answerer_id": self.answerer_id,
            "node_names": self.node_names,
            "edge_refs": self.edge_refs,
            "score": self.score,
            "feedback_applied": self.feedback_applied,
            "materials": self.materials,
        }

    @classmethod
    def from_dict(cls, raw: dict | None):
        if raw is None:
            return None
        return cls(
            quest_name=raw.get("quest_name", ""),
            answer_index=raw.get("answer_index", -1),
            answerer_id=raw.get("answerer_id", ""),
            node_names=raw.get("node_names", []),
            edge_refs=[tuple(p) for p in raw.get("edge_refs", [])],
            score=raw.get("score"),
            feedback_applied=raw.get("feedback_applied", False),
            materials=list(raw.get("materials", [])),
        )


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

    def to_dict(self):
        base = super().to_dict()
        base["kind"] = "quest"
        base["quester_id"] = self.quester_id
        base["depth"] = self.depth
        base["parent_quest"] = self.parent_quest
        return base

    @classmethod
    def from_dict(cls, fm, body, graph):
        node = cls(
            name=fm.get("name", ""),
            quester_id=fm.get("quester_id", ""),
            content=body.strip(),
            parent_quest=fm.get("parent_quest"),
            depth=int(fm.get("depth", 0)),
        )
        node.title = fm.get("title", node.name)
        node.tags = set(fm.get("tags", []))
        node.t_read = float(fm.get("t_read", 0.0))
        node.t_write = float(fm.get("t_write", 0.0))
        node.t_lp = float(fm.get("t_lp", 0.0))
        node.metadata = fm.get("metadata", {})
        graph.add_node(node)
        return node


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

    def to_dict(self):
        base = super().to_dict()
        base["kind"] = "answer"
        base["answerer_id"] = self.answerer_id
        base["quest_name"] = self.quest_name
        base["match_score"] = self.match_score
        base["novelty_score"] = self.novelty_score
        base["trace"] = self.trace.to_dict() if self.trace else None
        return base

    @classmethod
    def from_dict(cls, fm, body, graph):
        node = cls(
            name=fm.get("name", ""),
            answerer_id=fm.get("answerer_id", ""),
            quest_name=fm.get("quest_name", ""),
            content=body.strip(),
        )
        node.match_score = fm.get("match_score")
        node.novelty_score = fm.get("novelty_score")
        node.trace = AnswerTrace.from_dict(fm.get("trace"))
        node.title = fm.get("title", node.name)
        node.tags = set(fm.get("tags", []))
        node.t_read = float(fm.get("t_read", 0.0))
        node.t_write = float(fm.get("t_write", 0.0))
        node.t_lp = float(fm.get("t_lp", 0.0))
        node.metadata = fm.get("metadata", {})
        graph.add_node(node)
        return node
