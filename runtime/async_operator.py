"""异步 Operator —— 拥有自主意识循环的独立 Agent。"""

import asyncio
import logging
import random
import string
from typing import Any

from mgraph import Node, NodePtr, insert_response
from persona import Persona, random_persona
from prompts import build_answer_prompt, build_question_prompt, build_score_prompt, format_question_text
from quest_board import QuestBoard
from questnode import AnswerNode, AnswerTrace, QuestNode
from runtime.messages import AnswerScored, AnswerSubmitted, ClockTick, QuestPosted

logger = logging.getLogger(__name__)


class AsyncOperator:
    MAX_ACTIVE_QUESTS = 3
    BASE_INTERVAL = 1.0

    def __init__(
        self,
        operator_id: str,
        runtime,
        decider=None,
        llm_client=None,
        persona: Persona | None = None,
    ):
        self.id = operator_id
        self.runtime = runtime
        self.decider = decider
        self.llm_client = llm_client
        self.persona = persona if persona is not None else random_persona()
        self.current = NodePtr()
        self.submitted_quests: list[QuestNode] = []
        # PATIENCE: J 型 0.9 ±0.05, P 型 0.8 ±0.05 — 每封消息独立掷骰
        base = 0.9 if "J" in self.persona.mbti else 0.8
        self.patience = base + random.uniform(-0.05, 0.05)

    def bind(self, node):
        self.current.bind(node)
        monitor = getattr(self.runtime, "monitor", None)
        if monitor:
            monitor.update_node(self.id, node.name)
        return self

    async def run(self):
        logger.info("[%s] 启动 Operator 主循环", self.id)
        monitor = getattr(self.runtime, "monitor", None)
        if monitor:
            monitor.update_mbti(self.id, str(self.persona.mbti))
            if self.current:
                monitor.update_node(self.id, self.current.get().name)

        while self.runtime.running:
            try:
                inbox = self.runtime.bus
                for msg in inbox.drain(self.id):
                    await self._handle(msg)
                    if random() > self.patience: break

                graph = self.runtime.graph
                board = self.runtime.board

                action = await self.decider.choose(
                    operator=self,
                    graph=graph,
                    board=board,
                )

                detail = ""
                match action.type:
                    case "wander":
                        await self._wander(graph)
                        node = self.current.get()
                        detail = node.name if node else ""
                    case "ask":
                        quest = await self._ask(graph, board)
                        if quest is not None:
                            await self.runtime.broadcast(
                                QuestPosted(
                                    quest_id=quest.name,
                                    quester_id=self.id,
                                    content=quest.content,
                                )
                            )
                            detail = quest.name
                    case "answer":
                        if action.target is not None:
                            ans = await self._answer(action.target, graph, board)
                            if ans is not None:
                                await self.runtime.broadcast(
                                    AnswerSubmitted(
                                        quest_id=action.target.name,
                                        answerer_id=self.id,
                                    )
                                )
                                detail = action.target.name
                    case "score":
                        if action.target is not None:
                            await self._score(action.target, graph, board)
                            detail = action.target.name
                    case "idle":
                        pass
                    case "sleep":
                        await asyncio.sleep(3.0)
                        if monitor:
                            monitor.report_action(self.id, "sleep")
                        continue

                if monitor:
                    monitor.report_action(self.id, action.type, detail)
            except asyncio.CancelledError:
                logger.info("[%s]  Operator 被取消", self.id)
                break
            except Exception:
                logger.exception("[%s] Operator 循环异常", self.id)

            await asyncio.sleep(self.BASE_INTERVAL)

        logger.info("[%s] Operator 主循环结束", self.id)

    async def _handle(self, msg):
        if isinstance(msg, ClockTick):
            pass
        elif isinstance(msg, QuestPosted):
            logger.debug("[%s] 收到新 Quest: %s", self.id, msg.quest_id)
        elif isinstance(msg, AnswerSubmitted):
            logger.debug("[%s] %s 回答了 Quest: %s", self.id, msg.answerer_id, msg.quest_id)
        elif isinstance(msg, AnswerScored):
            logger.debug(
                "[%s] Quest %s 评分: match=%s, novelty=%s",
                self.id,
                msg.quest_id,
                msg.match_score,
                msg.novelty_score,
            )

    async def _wander(self, graph):
        if not self.current:
            if not graph.V:
                return
            self.current.bind(graph.random_node())
            logger.info("[%s] 绑定至 %s", self.id, self.current.get().name)
            return
        source = self.current.get()
        nxt, edge = source.sample_l2()
        if edge is None:
            candidates = [n for n in graph.V if n is not source]
            if not candidates:
                return
            nxt = random.choice(candidates)
            self.current.bind(nxt)
            logger.info("[%s] 跳跃至 %s", self.id, nxt.name)
            return
        reaction = bool(random.randint(0, 1))
        insert_response(reaction, edge)
        self.current.bind(nxt)
        logger.info("[%s] 漫游至 %s", self.id, nxt.name)

        monitor = getattr(self.runtime, "monitor", None)
        if monitor:
            monitor.update_node(self.id, nxt.name)

    async def _ask(self, graph, board) -> QuestNode | None:
        content = None
        if self.llm_client is not None:
            content = await self._llm_ask()

        if content is None:
            content = f"{self.id} 提出了一个关于知识图谱的问题"

        own_active = [q for q in self.submitted_quests if q in board.active]
        for old_quest in own_active[: max(0, len(own_active) - self.MAX_ACTIVE_QUESTS + 1)]:
            board.close(old_quest)

        quest = board.post(self.id, content, graph)
        self.submitted_quests.append(quest)

        source = self.current.get()
        if source is not None:
            source.link_to(quest, random.uniform(0.5, 1.0))
        self.current.bind(quest)
        logger.info("[%s] 提问: %s — %s", self.id, quest.name, quest.content[:60])

        monitor = getattr(self.runtime, "monitor", None)
        if monitor:
            monitor.update_quests(self.id, len(self.submitted_quests))
            monitor.update_node(self.id, quest.name)
        return quest

    async def _llm_ask(self) -> str | None:
        _, _, context_text = self._read_for_quest(graph=self.runtime.graph)
        if not context_text:
            return None

        messages = build_question_prompt(
            self.id, context_text, mbti=self.persona.mbti
        )
        try:
            qdata = await self.llm_client.chat_json(messages)
        except Exception:
            logger.warning("[%s] LLM 出题失败，使用默认问题", self.id)
            return None

        if not qdata or "problems" not in qdata:
            return None

        return format_question_text(qdata)

    async def _answer(self, quest: QuestNode, graph, board) -> AnswerNode | None:
        node_names, path_edges, context_text = self._read_for_quest(graph)

        self._navigate_to(graph, quest)

        answer_text = None
        if self.llm_client is not None and context_text:
            answer_text = await self._llm_answer(quest, context_text)

        if answer_text is None:
            answer_text = f"{self.id} 回答 '{quest.content[:50]}...'"

        existing = sum(1 for link in quest.outlinks if isinstance(link.target, AnswerNode))
        trace = AnswerTrace(
            quest_name=quest.name,
            answer_index=existing,
            answerer_id=self.id,
            node_names=node_names,
            edge_refs=path_edges,
        )
        ans = board.submit_answer(quest, self.id, answer_text, graph, trace=trace)
        logger.info("[%s] 回答 %s", self.id, quest.name)
        return ans

    async def _llm_answer(self, quest: QuestNode, context_text: str) -> str | None:
        messages = build_answer_prompt(
            self.id, quest.content, context_text, mbti=self.persona.mbti
        )
        try:
            return await self.llm_client.chat(messages)
        except Exception:
            logger.warning("[%s] LLM 回答失败", self.id)
            return None

    async def _score(self, quest: QuestNode, graph, board):
        ans_node = quest.get_answer_by_id(self.id)
        if ans_node is None:
            answers = quest.get_answers()
            if not answers:
                return
            ans_node = answers[0]
            answerer_id = ans_node.answerer_id
        else:
            answerer_id = self.id

        answer_text = ans_node.content
        if self.llm_client is not None:
            match_score, novelty_score = await self._llm_score(quest, answer_text)
        else:
            match_score = 50.0
            novelty_score = 50.0

        board.set_score(ans_node, match_score, novelty_score)

        trace = ans_node.trace
        if trace is not None and not trace.feedback_applied:
            avg_score = (match_score + novelty_score) / 2
            reaction = avg_score > 80

            edge_map = {(e.source.name, e.target.name): e for e in graph.E}
            for src_name, tgt_name in trace.edge_refs:
                edge = edge_map.get((src_name, tgt_name))
                if edge is not None:
                    insert_response(reaction, edge)

            trace.feedback_applied = True

        logger.info(
            "[%s] 评分 %s (由 %s): match=%s, novelty=%s",
            self.id,
            quest.name,
            answerer_id,
            match_score,
            novelty_score,
        )

        await self.runtime.broadcast(
            AnswerScored(
                quest_id=quest.name,
                answerer_id=answerer_id,
                match_score=match_score,
                novelty_score=novelty_score,
            )
        )

        monitor = getattr(self.runtime, "monitor", None)
        if monitor:
            active = board.submitted_by(self.id)
            monitor.update_quests(self.id, len(active))

    async def _llm_score(self, quest: QuestNode, answer_text: str) -> tuple[float, float]:
        messages = build_score_prompt(
            quest.content, answer_text, mbti=self.persona.mbti
        )
        try:
            result = await self.llm_client.chat_json(messages)
            match = float(result.get("score_match", 50))
            novelty = float(result.get("score_novelty", 50))
            return max(0, min(100, match)), max(0, min(100, novelty))
        except Exception:
            logger.warning("[%s] LLM 评分失败，使用默认分数", self.id)
            return 50.0, 50.0

    def _read_for_quest(self, graph, node_limit: int = 3):
        if not self.current:
            if not graph.V:
                return [], [], ""
            self.current.bind(graph.random_node())
        start = self.current.get()
        node_names: list[str] = [start.name]
        path_edges: list[tuple[str, str]] = []
        context_parts: list[str] = []

        visited: list[Node] = [start]
        current = start
        for _ in range(node_limit - 1):
            nxt, edge = current.sample_l2()
            if edge is None:
                break
            path_edges.append((current.name, nxt.name))
            node_names.append(nxt.name)
            visited.append(nxt)
            current = nxt

        for i, node in enumerate(visited):
            if node.content:
                tag = f"【材料{string.ascii_uppercase[i]}】" if i < 26 else f"【材料{i+1}】"
                context_parts.append(f"{tag}「{node.title}」：\n{node.content}")

        context_text = "\n\n---\n\n".join(context_parts)
        return node_names, path_edges, context_text

    def _navigate_to(self, graph, target: Node, steps: int = 3):
        current = self.current.get()
        for _ in range(steps):
            if current is target:
                self.current.bind(target)
                return
            for edge in current.outlinks:
                if edge.target is target:
                    self.current.bind(target)
                    return
            nxt, _ = current.sample_l1()
            if nxt is current:
                break
            self.current.bind(nxt)
            current = nxt
        try:
            current.link_to(target, random.uniform(0.2, 0.5))
        except ValueError:
            pass
        self.current.bind(target)