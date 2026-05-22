"""搜索后端抽象 —— ABC + Fake + DuckDuckGo + Tavily 占位.

FR3 要求：
- FakeSearchService 必须离线可用（默认）
- 真实网络后端可选、可配置
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """统一搜索结果结构。"""
    title: str = ""
    url: str = ""
    snippet: str = ""
    content: str | None = None  # 完整页面内容（仅显式 fetch 后填充）
    source: str = ""  # 后端名: "fake" | "duckduckgo" | "tavily"
    query: str = ""


class SearchBackend(ABC):
    """搜索后端抽象。"""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...


# ── FakeSearchService ─────────────────────────


class FakeSearchService(SearchBackend):
    """假搜索后端 —— 返回预设结果，离线可用。"""

    def __init__(self, results: list[SearchResult] | None = None):
        if results is not None:
            self._results = results
        else:
            self._results = [
                SearchResult(
                    title=f"Fake Result {i}",
                    url=f"https://example.com/fake-{i}",
                    snippet=f"这是第 {i} 条假搜索结果，用于测试。",
                    source="fake",
                )
                for i in range(1, 6)
            ]

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        import asyncio
        await asyncio.sleep(0.01)  # 模拟微小延迟
        results = []
        for r in self._results[:max_results]:
            r.query = query
            results.append(r)
        return results

    @staticmethod
    def default_config() -> dict:
        return {"enabled": True, "backend": "fake"}


# ── DuckDuckGoSearchService ───────────────────


class DuckDuckGoSearchService(SearchBackend):
    """DuckDuckGo 搜索后端（免费，无需 API key）。

    依赖: pip install duckduckgo-search
    """

    def __init__(self, timeout: float = 10.0):
        self._timeout = timeout
        self._available = False
        self._check_deps()

    def _check_deps(self):
        try:
            global DDGS
            from duckduckgo_search import DDGS
            self._available = True
        except ImportError:
            logger.warning(
                "DuckDuckGoSearchService: duckduckgo_search 未安装。"
                "运行 pip install duckduckgo-search 启用。"
            )

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._available:
            logger.warning("DuckDuckGoSearchService 不可用（依赖未安装）")
            return []

        import asyncio

        def _sync_search():
            try:
                with DDGS(timeout=self._timeout) as ddgs:
                    raw = list(ddgs.text(query, max_results=max_results))
                    return raw
            except Exception:
                logger.exception("DuckDuckGo 搜索失败")
                return []

        raw = await asyncio.to_thread(_sync_search)
        results = []
        for item in raw:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("href", ""),
                snippet=item.get("body", ""),
                source="duckduckgo",
                query=query,
            ))
        return results


# ── TavilySearchService 占位 ──────────────────


class TavilySearchService(SearchBackend):
    """Tavily API 搜索后端（可选，需要 API key）。

    依赖: pip install tavily-python
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._available = False
        self._check_deps()

    def _check_deps(self):
        try:
            from tavily import TavilyClient
            self._client_cls = TavilyClient
            self._available = True
        except ImportError:
            logger.warning(
                "TavilySearchService: tavily-python 未安装。"
                "运行 pip install tavily-python 启用。"
            )

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._available:
            logger.warning("TavilySearchService 不可用（依赖未安装）")
            return []
        if not self._api_key:
            logger.warning("TavilySearchService: 未配置 API key")
            return []

        import asyncio

        def _sync_search():
            try:
                client = self._client_cls(api_key=self._api_key)
                resp = client.search(query, max_results=max_results)
                return resp.get("results", [])
            except Exception:
                logger.exception("Tavily 搜索失败")
                return []

        raw = await asyncio.to_thread(_sync_search)
        results = []
        for item in raw:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source="tavily",
                query=query,
            ))
        return results
