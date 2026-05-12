from random import randint, uniform

from mgraph import Node, NodePtr, insert_response
from persona import Persona, random_persona
from quest_board import QuestBoard
from questnode import AnswerNode, AnswerTrace, QuestNode
from operator_core import read_context, navigate


class Operator:
    MAX_ACTIVE_QUESTS = 3

    def __init__(self, id: str = None, current=None, llm_client=None,
                 persona: Persona | None = None):
        if id is None:
            self.id = f"Operator {randint(0, 1000)}"
        else:
            self.id = id
        self.current = current if isinstance(current, NodePtr) else NodePtr(current)
        self.submitted_quests: list[QuestNode] = []
        self.llm_client = llm_client
        self.persona = persona if persona is not None else random_persona()

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

    def ask(self, graph, board: QuestBoard, content: str = None) -> QuestNode:
        if content is None:
            if self.llm_client is not None:
                content = self._llm_ask()
            else:
                raise ValueError("ask requires content when no llm_client")

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

    def _llm_ask(self) -> str:
        """使用 LLM 基于当前阅读路径生成问题。"""
        from prompts import build_question_prompt, format_question_text

        _, _, context_text = self.read_for_quest()

        if not context_text:
            return "请阅读材料后提出问题。"

        if hasattr(self.llm_client, "chat_json"):
            messages = build_question_prompt(self.id, context_text,
                                             mbti=self.persona.mbti)
            qdata = self.llm_client.chat_json(messages)
        else:
            return "LLM 客户端不支持 JSON 模式。"

        if not qdata or "problems" not in qdata:
            return "出题失败，请重试。"

        return format_question_text(qdata)

    def find_quest(self, board: QuestBoard) -> QuestNode | None:
        available = board.available_for(self.id)
        if not available:
            return None
        return available[0]

    def navigate_to(self, graph, target: Node, steps: int = 3) -> Node:
        return navigate(self.current, target, steps)

    def read_for_quest(self, node_limit: int = 3):
        return read_context(self.current.get(), node_limit)

    def answer_quest(
        self, quest: QuestNode, board: QuestBoard, graph, answer_text: str = None
    ) -> AnswerNode:
        # 先阅读路径
        node_names, path_edges, context_text = self.read_for_quest()
        # 导航到 quest 节点
        self.navigate_to(graph, quest)
        # 生成答案
        if answer_text is None:
            if self.llm_client is not None and context_text:
                answer_text = self._llm_answer(quest, context_text)
            else:
                answer_text = f"{self.id} answers '{quest.content}'"
        trace = AnswerTrace(
            quest_name=quest.name,
            answer_index=-1,  # filled by submit_answer
            answerer_id=self.id,
            node_names=node_names,
            edge_refs=path_edges,
        )
        return board.submit_answer(quest, self.id, answer_text, graph, trace=trace)

    def _llm_answer(self, quest: QuestNode, context_text: str) -> str:
        """使用 LLM 生成答案。"""
        from prompts import build_answer_prompt

        messages = build_answer_prompt(self.id, quest.content, context_text,
                                       mbti=self.persona.mbti)
        return self.llm_client.chat(messages) or f"{self.id} answers '{quest.content}'"

    def _llm_score(self, quest: QuestNode, answer_text: str) -> tuple[float, float]:
        """使用 LLM 对回答评分，返回 (match_score, novelty_score)。"""
        from prompts import build_score_prompt

        messages = build_score_prompt(quest.content, answer_text,
                                      mbti=self.persona.mbti)
        result = self.llm_client.chat_json(messages)

        match = float(result.get("score_match", 50))
        novelty = float(result.get("score_novelty", 50))
        return max(0, min(100, match)), max(0, min(100, novelty))

    def score_answer(
        self,
        quest: QuestNode,
        answerer_id: str,
        match_score: float | None = None,
        novelty_score: float | None = None,
        graph=None,
        board: QuestBoard | None = None,
    ) -> None:
        ans_node = quest.get_answer_by_id(answerer_id)
        if ans_node is None:
            return

        answer_text = ans_node.content

        if match_score is None or novelty_score is None:
            if self.llm_client is not None:
                match_score, novelty_score = self._llm_score(quest, answer_text)
            else:
                raise ValueError(
                    "score_answer requires match_score and novelty_score "
                    "when no llm_client"
                )

        board.set_score(ans_node, match_score, novelty_score)

        trace = ans_node.trace
        if trace is None or trace.feedback_applied:
            return

        avg_score = (match_score + novelty_score) / 2
        reaction = avg_score > 80

        # 只反馈 evidence path（不反馈导航到 quest 的边）
        edge_map = {(e.source.name, e.target.name): e for e in graph.E}
        for src_name, tgt_name in trace.edge_refs:
            edge = edge_map.get((src_name, tgt_name))
            if edge is not None:
                insert_response(reaction, edge)

        trace.feedback_applied = True
