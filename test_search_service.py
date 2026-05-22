"""测试搜索后端抽象层。"""

import asyncio

from runtime.search_service import (
    SearchResult,
    FakeSearchService,
    DuckDuckGoSearchService,
    TavilySearchService,
)


def test_search_result_dataclass():
    r = SearchResult(title="T", url="https://x.com", snippet="S", source="fake", query="q")
    assert r.title == "T"
    assert r.url == "https://x.com"
    assert r.snippet == "S"
    assert r.source == "fake"
    assert r.query == "q"


def test_fake_search_returns_results():
    service = FakeSearchService()
    results = asyncio.run(service.search("test query"))
    assert len(results) == 5
    for r in results:
        assert r.source == "fake"
        assert r.query == "test query"
        assert r.url.startswith("https://")


def test_fake_search_respects_max_results():
    service = FakeSearchService()
    results = asyncio.run(service.search("test", max_results=2))
    assert len(results) == 2


def test_fake_search_custom_results():
    custom = [
        SearchResult(title="Custom", url="https://custom.com", snippet="custom", source="fake"),
    ]
    service = FakeSearchService(results=custom)
    results = asyncio.run(service.search("q"))
    assert len(results) == 1
    assert results[0].title == "Custom"


def test_fake_search_sets_query_on_results():
    service = FakeSearchService()
    results = asyncio.run(service.search("my query"))
    for r in results:
        assert r.query == "my query"


def test_duckduckgo_not_available_without_dep():
    # 不安装依赖的情况下，应优雅降级
    service = DuckDuckGoSearchService()
    results = asyncio.run(service.search("test"))
    assert results == []  # 依赖未安装返回空列表


def test_tavily_not_available_without_dep():
    service = TavilySearchService(api_key="test")
    results = asyncio.run(service.search("test"))
    assert results == []  # 依赖未安装返回空列表


def test_tavily_no_api_key():
    service = TavilySearchService()
    results = asyncio.run(service.search("test"))
    assert results == []


def test_fake_default_config():
    config = FakeSearchService.default_config()
    assert config["enabled"] is True
    assert config["backend"] == "fake"
