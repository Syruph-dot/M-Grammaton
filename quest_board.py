from random import choice, getrandbits

from questnode import AnswerNode, AnswerTrace, QuestNode


class QuestBoard:
    """Central quest board managing question/answer lifecycle."""

    def __init__(self):
        self.active: list[QuestNode] = []
        self.completed: list[QuestNode] = []

    def post(self, quester_id: str, content: str, graph) -> QuestNode:
        """Post a new Quest into the graph."""
        quest = QuestNode(
            name=f"quest_{len(self.active) + len(self.completed)}",
            quester_id=quester_id,
            content=content,
        )
        graph.add_node(quest)
        self.active.append(quest)
        return quest

    def available_for(self, operator_id: str) -> list[QuestNode]:
        """Get active quests answerable by an operator, excluding their own."""
        key = choice(("t_read", "t_write", "t_lp"))
        quests = [q for q in self.active if q.quester_id != operator_id]
        quests.sort(key=lambda q: getattr(q, key), reverse=bool(getrandbits(1)))
        return quests

    def submitted_by(self, operator_id: str) -> list[QuestNode]:
        """Get active quests posted by an operator."""
        return [q for q in self.active if q.quester_id == operator_id]

    def submit_answer(self, quest: QuestNode, answerer_id: str, answer: str,
                      graph, trace: AnswerTrace | None = None) -> AnswerNode:
        """Submit an answer as an AnswerNode, linked bidirectionally to reading path nodes.

        Returns the created AnswerNode.
        """
        # 计算该 quest 已有的答案数作为序号
        existing_count = sum(1 for link in quest.outlinks if isinstance(link.target, AnswerNode))
        node_name = f"{quest.name}_ans_{answerer_id}_{existing_count}"

        ans_node = AnswerNode(
            name=node_name,
            answerer_id=answerer_id,
            quest_name=quest.name,
            content=answer,
        )
        if trace is not None:
            trace.answer_index = existing_count
            ans_node.trace = trace

        graph.add_node(ans_node)

        # quest → answer
        quest.link_to(ans_node, 1.0)

        # 双向链接：阅读路径节点 ↔ 答案
        if trace and trace.node_names:
            node_map = {n.name: n for n in graph.V}
            for node_name in trace.node_names:
                path_node = node_map.get(node_name)
                if path_node is not None and path_node is not quest and path_node is not ans_node:
                    path_node.link_to(ans_node, 1.0)   # 路径节点 → 答案
                    ans_node.link_to(path_node, 1.0)   # 答案 → 路径节点

        return ans_node

    def set_score(self, ans_node: AnswerNode, match_score: float, novelty_score: float) -> None:
        """Score an answer on two dimensions: [匹配度, 新颖度]."""
        if not (0 <= match_score <= 100):
            raise ValueError(f"match_score must be in 0-100, got {match_score}")
        if not (0 <= novelty_score <= 100):
            raise ValueError(f"novelty_score must be in 0-100, got {novelty_score}")
        ans_node.match_score = match_score
        ans_node.novelty_score = novelty_score

    def close(self, quest: QuestNode) -> None:
        """Close a quest, moving it from active to completed."""
        if quest in self.active:
            self.active.remove(quest)
            self.completed.append(quest)

    def to_dict(self) -> dict:
        return {
            "active": [q.name for q in self.active],
            "completed": [q.name for q in self.completed],
        }

    @classmethod
    def from_dict(cls, data: dict, node_map: dict[str, QuestNode]):
        board = cls()
        for qname in data.get("active", []):
            qnode = node_map.get(qname)
            if isinstance(qnode, QuestNode):
                board.active.append(qnode)
        for qname in data.get("completed", []):
            qnode = node_map.get(qname)
            if isinstance(qnode, QuestNode):
                board.completed.append(qnode)
        return board
