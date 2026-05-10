from random import choice, getrandbits

from questnode import QuestNode


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

    def submit_answer(self, quest: QuestNode, answerer_id: str, answer: str) -> int:
        """Submit an answer and return its index."""
        idx = len(quest.answers)
        quest.answers.append(answer)
        quest.from_ids.append(answerer_id)
        quest.scores.append(None)
        return idx

    def set_score(self, quest: QuestNode, answerer_id: str, score: float) -> None:
        """Score the latest answer from an answerer for a quest."""
        if not (0 <= score <= 100):
            raise ValueError(f"score must be in 0-100 range, got {score}")
        indices = [i for i, fid in enumerate(quest.from_ids) if fid == answerer_id]
        if not indices:
            raise ValueError(f"{answerer_id} has not answered this quest")
        idx = indices[-1]
        quest.scores[idx] = score

    def close(self, quest: QuestNode) -> None:
        """Close a quest, moving it from active to completed."""
        if quest in self.active:
            self.active.remove(quest)
            self.completed.append(quest)
