from random import randint, uniform

from mgraph import Node, NodePtr, insert_response
from quest_board import QuestBoard
from questnode import AnswerTrace, QuestNode


class Operator:
    MAX_ACTIVE_QUESTS = 3

    def __init__(self, id: str = None, current=None):
        if id is None:
            self.id = f"Operator {randint(0, 1000)}"
        else:
            self.id = id
        self.current = current if isinstance(current, NodePtr) else NodePtr(current)
        self.submitted_quests: list[QuestNode] = []

    def bind(self, node):
        self.current.bind(node)
        return self

    def random_act(self):
        source = self.current.get()
        current, edge = source.sample_l2()
        if edge is None:
            return None, None, None
        reaction = bool(randint(0, 1))
        insert_response(reaction, edge)
        self.current.bind(current)
        return self.current, edge, reaction

    def ask(self, graph, board: QuestBoard, content: str) -> QuestNode:
        own_active = [quest for quest in self.submitted_quests if quest in board.active]
        for old_quest in own_active[: max(0, len(own_active) - self.MAX_ACTIVE_QUESTS + 1)]:
            board.close(old_quest)
        quest = board.post(self.id, content, graph)
        self.submitted_quests.append(quest)
        source = self.current.get()
        if source is not None:
            source.link_to(quest, uniform(0.5, 1.0))
        self.current.bind(quest)
        return quest

    def find_quest(self, board: QuestBoard) -> QuestNode | None:
        available = board.available_for(self.id)
        if not available:
            return None
        return available[0]

    def navigate_to(self, graph, target: Node, steps: int = 3) -> Node | None:
        current = self.current.get()
        for _ in range(steps):
            if current is target:
                return current
            for edge in current.outlinks:
                if edge.target is target:
                    self.current.bind(target)
                    return target
            nxt, _ = current.sample_l1()
            if nxt is current:
                break
            self.current.bind(nxt)
            current = nxt
        try:
            current.link_to(target, uniform(0.2, 0.5))
        except ValueError:
            pass
        self.current.bind(target)
        return target

    def read_for_quest(self, node_limit: int = 3):
        """从当前节点出发，沿 sample_l2 行走并记录阅读路径。

        返回:
            node_names: list[str]   — 访问过的节点名
            path_edges: list[tuple[str, str]] — (source, target) 边列表
            context_text: str       — 节点内容拼接
        """
        start = self.current.get()
        node_names: list[str] = [start.name]
        path_edges: list[tuple[str, str]] = []
        context_parts: list[str] = []

        if start.content:
            context_parts.append(f"「{start.title}」：\n{start.content}")

        current = start
        for _ in range(node_limit - 1):
            nxt, edge = current.sample_l2()
            if edge is None:
                break
            path_edges.append((current.name, nxt.name))
            node_names.append(nxt.name)
            if nxt.content:
                context_parts.append(f"「{nxt.title}」：\n{nxt.content}")
            current = nxt

        context_text = "\n\n---\n\n".join(context_parts)
        return node_names, path_edges, context_text

    def answer_quest(
        self, quest: QuestNode, board: QuestBoard, graph, answer_text: str = None
    ) -> int:
        if answer_text is None:
            answer_text = f"{self.id} answers '{quest.content}'"
        self.navigate_to(graph, quest)
        trace = AnswerTrace(
            quest_name=quest.name,
            answer_index=-1,  # filled by submit_answer
            answerer_id=self.id,
        )
        return board.submit_answer(quest, self.id, answer_text, trace=trace)

    def score_answer(
        self,
        quest: QuestNode,
        answerer_id: str,
        match_score: float,
        novelty_score: float,
        graph,
        board: QuestBoard,
    ) -> None:
        board.set_score(quest, answerer_id, match_score, novelty_score)
        avg_score = (match_score + novelty_score) / 2
        reaction = avg_score > 80

        answerer_anchor = asker_anchor = None
        for node in graph.V:
            if node.name == f"op_{answerer_id}":
                answerer_anchor = node
            if node.name == f"op_{self.id}":
                asker_anchor = node

        if answerer_anchor is not None and asker_anchor is not None:
            edge = None
            for e in answerer_anchor.outlinks:
                if e.target is asker_anchor:
                    edge = e
                    break
            if edge is None:
                edge = answerer_anchor.link_to(asker_anchor, 0.5)
            insert_response(reaction, edge)
