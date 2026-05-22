"""异步 Operator —— 拥有自主意识循环的独立 Agent。"""

import asyncio
import logging
import random
import time
from typing import Any

from mgraph import Node, NodePtr, insert_response
from material_context import (
    choose_answer_materials,
    format_material_context,
    material_refs_from_nodes,
    material_trace_records,
)
from persona import Persona, random_persona
from prompts import build_answer_prompt, build_question_prompt, build_score_prompt, format_question_text
from quest_board import QuestBoard
from questnode import AnswerNode, AnswerTrace, QuestNode
from runtime.actor_panel import ActorPanel
from runtime.messages import AnswerScored, AnswerSubmitted, ClockTick, QuestPosted
from runtime.search_service import FakeSearchService, SearchBackend, SearchResult
from operator_core import read_context, read_path, navigate

logger = logging.getLogger(__name__)


# ── 搜索报告 prompt ───────────────────────


def _search_report_prompt(query: str, imported_context: str) -> list[dict]:
    return [
        {"role": "system", "content":
         "你是一个知识图谱研究助手。根据搜索结果撰写一份连贯的中文搜索报告。"
         "要求：\n1. 使用中文\n2. 输出为文章形式（总结 + 反思），不要 JSON 或列表\n"
         "3. 不要分段成 claims/evidence/limits 等小结构"},
        {"role": "user", "content":
         f"搜索查询: {query}\n\n搜索结果:\n{imported_context}\n\n"
         "以上材料说明了什么？这些材料引发了怎样的联想和反思？"},
    ]


def _search_query_prompt(node_title: str, node_content: str) -> list[dict]:
    return [
        {"role": "system", "content": "你是一个知识图谱研究助手。根据当前阅读的节点内容，生成一个简短的中文搜索查询（一句话，不要标点）。"},
        {"role": "user", "content": f"当前节点: {node_title}\n内容: {node_content[:500]}\n\n请生成搜索查询："},
    ]


class AsyncOperator:
    MAX_ACTIVE_QUESTS = 3
    BASE_INTERVAL = 1.0
    SEARCH_COOLDOWN_SECONDS = 60
    SEARCH_MAX_RESULTS = 5
    WEB_EDGE_WEIGHT = 0.3
    REPORT_EDGE_WEIGHT = 0.5

    def __init__(
        self,
        operator_id: str,
        *,
        graph,
        board,
        bus,
        running_ref,
        decider=None,
        llm_client=None,
        persona: Persona | None = None,
        monitor=None,
        search_service: SearchBackend | None = None,
    ):
        self.id = operator_id
        self.graph = graph
        self.board = board
        self.bus = bus
        self._running_ref = running_ref
        self.monitor = monitor
        self.decider = decider
        self.llm_client = llm_client
        self.persona = persona if persona is not None else random_persona()
        self.panel = ActorPanel(actor_id=operator_id, actor_kind="operator")
        self.current = self.panel.current  # 共享指针
        self.submitted_quests: list[QuestNode] = []
        self.search_service = search_service or FakeSearchService()
        # PATIENCE: J 型 0.9 ±0.05, P 型 0.8 ±0.05 — 每封消息独立掷骰
        base = 0.9 if "J" in self.persona.mbti else 0.8
        self.patience = base + random.uniform(-0.05, 0.05)

    def bind(self, node):
        self.current.bind(node)
        self.panel.bind(node)
        if self.monitor:
            self.monitor.update_node(self.id, node.name)
        return self

    async def run(self):
        logger.info("[%s] 启动 Operator 主循环", self.id)
        if self.monitor:
            self.monitor.update_mbti(self.id, str(self.persona.mbti))
            if self.current:
                self.monitor.update_node(self.id, self.current.get().name)

        while self._running_ref[0]:
            try:
                for msg in self.bus.drain(self.id):
                    await self._handle(msg)
                    if random.random() > self.patience: break

                graph = self.graph
                board = self.board

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
                            await self.bus.broadcast(
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
                                await self.bus.broadcast(
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
                        if self.monitor:
                            self.monitor.report_action(self.id, "sleep")
                        continue
                    case "stash_current":
                        await self._stash_current()
                        detail = "stashed"
                    case "read_stash":
                        stash_len = len(self.panel.stash)
                        detail = f"{stash_len} items"
                    case "search_web":
                        await self._search_web()
                        detail = "search_done"
                    case "send_message":
                        await self._send_message_stub()
                        detail = "msg_stub"
                    case "reply_to_message":
                        await self._reply_to_message_stub()
                        detail = "reply_stub"

                if self.monitor:
                    self.monitor.report_action(self.id, action.type, detail)
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

    # ── Phase 2: stash_current ──────────────────────

    async def _stash_current(self):
        try:
            node = self.current.get()
        except Exception:
            return
        self.panel.add_to_stash(node, reason="auto_stash")
        logger.info("[%s] 收藏当前节点: %s", self.id, node.name)

    # ── Phase 2: search_web ─────────────────────────

    async def _search_web(self):
        # 1. 冷却检查（硬门，Decider 应该已经处理了，但再检查一次）
        now = time.time()
        if self.panel.search_cooldown_until > now:
            logger.debug("[%s] 搜索冷却中，跳过", self.id)
            return

        # 2. 生成搜索查询
        query = await self._generate_search_query()
        if not query:
            logger.info("[%s] 无法生成搜索查询", self.id)
            if self.monitor:
                self.monitor.report_action(self.id, "search_failed", "no_query")
            return

        # 3. 设置冷却
        self.panel.search_cooldown_until = now + self.SEARCH_COOLDOWN_SECONDS

        # 4. 执行搜索
        logger.info("[%s] 搜索: %s", self.id, query)
        if self.monitor:
            self.monitor.report_action(self.id, "search_started", query[:60])

        try:
            results = await self.search_service.search(query, self.SEARCH_MAX_RESULTS)
        except Exception:
            logger.exception("[%s] 搜索失败", self.id)
            if self.monitor:
                self.monitor.report_action(self.id, "search_failed", "exception")
            return

        if not results:
            logger.info("[%s] 搜索无结果: %s", self.id, query)
            if self.monitor:
                self.monitor.report_action(self.id, "search_failed", "empty")
            return

        # 5. URL 去重 + 导入
        imported = []
        graph = self.graph
        for result in results:
            if self._is_url_imported(result.url, graph):
                continue
            node = self._create_web_page_node(result, graph)
            try:
                source = self.current.get()
                source.link_to(node, self.WEB_EDGE_WEIGHT)
            except Exception:
                pass
            imported.append(node)
            logger.debug("[%s] 导入 web_page: %s", self.id, result.url)

        if not imported:
            logger.info("[%s] 搜索结果全是重复", self.id)
            if self.monitor:
                self.monitor.report_action(self.id, "search_done", "all_dup")
            return

        # 6. 创建搜索报告
        report = await self._create_search_report(query, imported, graph)
        if report is not None:
            self.panel.add_to_stash(report, reason="search_report")
            logger.info("[%s] 搜索完成: %d 结果, 有报告", self.id, len(imported))

        if self.monitor:
            self.monitor.report_action(
                self.id, "search_done",
                f"{len(imported)} results, report={'yes' if report else 'no'}",
            )

    async def _generate_search_query(self) -> str | None:
        try:
            node = self.current.get()
            title = getattr(node, "title", node.name) or node.name
            content = getattr(node, "content", "") or ""
        except Exception:
            return None

        if self.llm_client is not None:
            try:
                messages = _search_query_prompt(title, content)
                query = await self.llm_client.chat(messages)
                if query and query.strip():
                    return query.strip().strip('"').strip("'")[:200]
            except Exception:
                logger.warning("[%s] LLM 生成查询失败", self.id)

        # 降级：用节点标题前 60 字
        fallback = (title or content)[:60].strip()
        return fallback if fallback else "知识图谱相关搜索"

    def _is_url_imported(self, url: str, graph) -> bool:
        if not url:
            return False
        for node in graph.V:
            if node.metadata.get("web_url") == url:
                return True
        return False

    def _create_web_page_node(self, result: SearchResult, graph) -> Node:
        node_id = f"web_{len(graph.V)}_{int(time.time() * 1000)}_{random.randint(100, 999)}"
        node = Node(node_id, kind="artifact", content=result.snippet or "", mg=graph)
        node.title = result.title or node_id
        node.metadata = {
            "artifact_type": "web_page",
            "web_url": result.url,
            "web_title": result.title,
            "web_snippet": result.snippet,
            "fetched_at": time.time(),
            "query": result.query,
            "backend": result.source,
            "actor_id": self.id,
            "trust_level": "unverified",
            "content_mode": "snippet_only",
        }
        return node

    async def _create_search_report(self, query: str, imported_nodes: list[Node],
                                     graph) -> Node | None:
        imported_context = "\n".join(
            f"- {n.metadata.get('web_title', '')}: "
            f"{n.metadata.get('web_snippet', '')[:200]}"
            for n in imported_nodes
        )

        if self.llm_client is not None:
            try:
                messages = _search_report_prompt(query, imported_context)
                content = await self.llm_client.chat(messages)
                if not content or not content.strip():
                    content = None
            except Exception:
                logger.warning("[%s] LLM 生成搜索报告失败", self.id)
                content = None
        else:
            content = None

        if not content:
            content = (
                f"搜索报告: {query}\n\n"
                f"共找到 {len(imported_nodes)} 条相关结果。\n"
                f"{imported_context}"
            )

        node_id = f"sreport_{len(graph.V)}_{int(time.time() * 1000)}"
        node = Node(node_id, kind="artifact", content=content, mg=graph)
        node.title = f"Search Report: {query[:40]}"
        node.metadata = {
            "artifact_type": "search_report",
            "status": "useful",
            "query": query,
            "actor_id": self.id,
            "result_count": len(imported_nodes),
            "result_ids": [n.name for n in imported_nodes],
            "created_at": time.time(),
        }

        try:
            source = self.current.get()
            source.link_to(node, self.REPORT_EDGE_WEIGHT)
        except Exception:
            pass

        return node

    # ── Phase 2: send_message / reply_to_message 桩（Slice-002 实现） ──

    async def _send_message_stub(self):
        logger.debug("[%s] send_message 暂由 Slice-002 实现", self.id)

    async def _reply_to_message_stub(self):
        logger.debug("[%s] reply_to_message 暂由 Slice-002 实现", self.id)

    # ── Phase 1 原有方法 ──────────────────────────

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

        if self.monitor:
            self.monitor.update_node(self.id, nxt.name)

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

        if self.monitor:
            self.monitor.update_quests(self.id, len(self.submitted_quests))
            self.monitor.update_node(self.id, quest.name)
        return quest

    async def _llm_ask(self) -> str | None:
        _, _, context_text = self._read_for_quest(graph=self.graph)
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
        node_names, path_edges, context_text, material_records = (
            self._read_materials_for_quest(graph)
        )

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
            materials=material_records,
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

        await self.bus.broadcast(
            AnswerScored(
                quest_id=quest.name,
                answerer_id=answerer_id,
                match_score=match_score,
                novelty_score=novelty_score,
            )
        )

        if self.monitor:
            active = board.submitted_by(self.id)
            self.monitor.update_quests(self.id, len(active))

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
        return read_context(self.current.get(), node_limit)

    def _read_materials_for_quest(self, graph, node_limit: int = 3):
        if not self.current:
            if not graph.V:
                return [], [], "", []
            self.current.bind(graph.random_node())
        node_names, path_edges, visited = read_path(self.current.get(), node_limit)
        refs = material_refs_from_nodes(visited)
        chosen = choose_answer_materials(refs)
        return (
            node_names,
            path_edges,
            format_material_context(chosen),
            material_trace_records(chosen),
        )

    def _navigate_to(self, graph, target: Node, steps: int = 3):
        navigate(self.current, target, steps)
