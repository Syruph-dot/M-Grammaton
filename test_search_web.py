"""测试 Search Web 证据导入管线。"""

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

from mgraph import MGraph, Node
from quest_board import QuestBoard
from runtime.async_operator import AsyncOperator
from runtime.actor_panel import ActorPanel
from runtime.decision import RandomDecider
from runtime.message_bus import MessageBus
from runtime.monitor import RuntimeMonitor
from runtime.search_service import FakeSearchService, SearchResult


def _make_panel(op_id="TestOp"):
    panel = ActorPanel(actor_id=op_id, actor_kind="operator")
    return panel


def _make_graph():
    graph = MGraph()
    src = Node("source", content="一些可搜索的内容", mg=graph)
    tgt = Node("target", content="关于机器学习的知识", mg=graph)
    src.link_to(tgt, 1.0)
    return graph


def _make_operator(graph=None, panel=None, search_results=None):
    graph = graph or _make_graph()
    board = QuestBoard()
    bus = MessageBus(["TestOp"])
    panel = panel or _make_panel("TestOp")
    search_svc = FakeSearchService(results=search_results)

    op = AsyncOperator(
        operator_id="TestOp",
        graph=graph,
        board=board,
        bus=bus,
        running_ref=[True],
        decider=RandomDecider(),
        search_service=search_svc,
    )
    op.panel = panel
    op.current = panel.current
    src = next(n for n in graph.V if n.name == "source")
    op.bind(src)
    return op, graph


class TestSearchWeb:

    def test_search_creates_web_page_artifacts(self):
        op, graph = _make_operator()
        asyncio.run(op._search_web())

        web_pages = [n for n in graph.V
                     if n.metadata.get("artifact_type") == "web_page"]
        assert len(web_pages) > 0
        wp = web_pages[0]
        assert wp.metadata["trust_level"] == "unverified"
        assert wp.metadata["content_mode"] == "snippet_only"
        assert wp.metadata["actor_id"] == "TestOp"
        assert wp.metadata["backend"] == "fake"

    def test_search_creates_search_report_artifact(self):
        op, graph = _make_operator()
        asyncio.run(op._search_web())

        reports = [n for n in graph.V
                   if n.metadata.get("artifact_type") == "search_report"]
        assert len(reports) == 1
        report = reports[0]
        assert report.metadata["status"] == "useful"
        assert "result_ids" in report.metadata
        assert len(report.metadata["result_ids"]) > 0

    def test_search_report_auto_stashed(self):
        op, graph = _make_operator()
        asyncio.run(op._search_web())

        stash_items = [s for s in op.panel.stash if s.reason == "search_report"]
        assert len(stash_items) == 1

    def test_url_dedup_skips_duplicate(self):
        op, graph = _make_operator()
        # First search
        asyncio.run(op._search_web())
        first_count = len([n for n in graph.V
                           if n.metadata.get("artifact_type") == "web_page"])

        # Second search with same results
        op.panel.search_cooldown_until = 0  # reset cooldown
        asyncio.run(op._search_web())
        second_count = len([n for n in graph.V
                            if n.metadata.get("artifact_type") == "web_page"])

        # Same URLs → no new nodes
        assert second_count == first_count

    def test_search_web_page_has_low_edge_weight(self):
        op, graph = _make_operator()
        src = next(n for n in graph.V if n.name == "source")
        asyncio.run(op._search_web())

        web_pages = [n for n in graph.V
                     if n.metadata.get("artifact_type") == "web_page"]
        if web_pages:
            wp = web_pages[0]
            edge = next((e for e in src.outlinks if e.target.name == wp.name), None)
            if edge:
                assert edge.value == op.WEB_EDGE_WEIGHT  # 0.3

    def test_empty_search_no_report(self):
        op, graph = _make_operator(search_results=[])
        asyncio.run(op._search_web())

        reports = [n for n in graph.V
                   if n.metadata.get("artifact_type") == "search_report"]
        assert len(reports) == 0

    def test_cooldown_skips_search(self):
        op, graph = _make_operator()
        op.panel.search_cooldown_until = time.time() + 9999

        asyncio.run(op._search_web())

        web_pages = [n for n in graph.V
                     if n.metadata.get("artifact_type") == "web_page"]
        assert len(web_pages) == 0

    def test_web_page_metadata_shape(self):
        op, graph = _make_operator()
        asyncio.run(op._search_web())

        web_pages = [n for n in graph.V
                     if n.metadata.get("artifact_type") == "web_page"]
        assert len(web_pages) > 0
        wp = web_pages[0]
        required_keys = {"artifact_type", "web_url", "web_title", "web_snippet",
                         "fetched_at", "query", "backend", "actor_id",
                         "trust_level", "content_mode"}
        assert required_keys.issubset(wp.metadata.keys())
        assert wp.metadata["trust_level"] == "unverified"
        assert wp.metadata["content_mode"] == "snippet_only"

    def test_stash_current_adds_node_to_stash(self):
        op, graph = _make_operator()
        asyncio.run(op._stash_current())

        assert len(op.panel.stash) == 1
        assert op.panel.stash[0].node_id == "source"

    def test_is_url_imported(self):
        op, graph = _make_operator()
        # Manually add a node with a URL
        node = Node("test_web", kind="artifact", mg=graph)
        node.metadata["web_url"] = "https://example.com/test"
        assert op._is_url_imported("https://example.com/test", graph) is True
        assert op._is_url_imported("https://other.com", graph) is False
