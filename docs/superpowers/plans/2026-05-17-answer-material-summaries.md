# Answer Material Summaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add answer-time material selection where every answer prompt includes at least one full cited material, eligible materials have a 15% summary substitution chance, summaries are prepared by a background LLM job, and summary token usage is counted by the runtime token stream.

**Architecture:** Keep reading-path traversal in `operator_core.py`, move material formatting and summary metadata into a focused `material_context.py`, and store answer material decisions in `AnswerTrace.materials`. Runtime background summarization lives in a small async service used by `OperatorRuntime`, reusing `AsyncLLMClient` so summary calls flow into `RuntimeMonitor.report_tokens()`.

**Tech Stack:** Python dataclasses, pytest, existing `MGraph` / `Node` / `QuestNode` / `AnswerNode`, existing OpenAI-compatible sync and async LLM clients, existing YAML frontmatter persistence.

---

### Task 1: Material Context Rules

**Files:**
- Create: `material_context.py`
- Test: `test_material_context.py`

- [ ] **Step 1: Write failing tests for summary prompt, truncation, stale detection, selection, and formatting**

Create `test_material_context.py` with:

```python
import random

from material_context import (
    SUMMARY_HARD_LIMIT_CHARS,
    SUMMARY_METADATA_KEY,
    SUMMARY_SUBSTITUTION_PROBABILITY,
    build_summary_prompt,
    choose_answer_materials,
    content_hash,
    format_material_context,
    material_refs_from_nodes,
    normalize_summary_text,
    store_summary,
    summary_is_stale,
)
from mgraph import Node


class FixedRandom:
    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_build_summary_prompt_requires_short_chinese_summary():
    node = Node("n1", content="这是需要摘要的原文材料。")
    messages = build_summary_prompt(node)

    assert messages[0]["role"] == "system"
    assert "不超过50字" in messages[0]["content"]
    assert "只输出摘要正文" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "这是需要摘要的原文材料" in messages[1]["content"]


def test_normalize_summary_text_hard_caps_at_120_chars():
    raw = "  " + ("甲" * (SUMMARY_HARD_LIMIT_CHARS + 20)) + "\n"
    assert normalize_summary_text(raw) == "甲" * SUMMARY_HARD_LIMIT_CHARS


def test_store_summary_records_current_content_hash_and_staleness():
    node = Node("n1", content="原文内容")
    stored = store_summary(node, " 摘要内容 ", model="deepseek-v4-flash", now=123.0)

    assert stored["text"] == "摘要内容"
    assert stored["model"] == "deepseek-v4-flash"
    assert stored["content_hash"] == content_hash("原文内容")
    assert stored["updated_at"] == 123.0
    assert node.metadata[SUMMARY_METADATA_KEY] == stored
    assert summary_is_stale(node) is False

    node.content = "原文内容已变化"
    assert summary_is_stale(node) is True


def test_material_refs_exclude_nodes_without_content_and_attach_valid_summary():
    with_summary = Node("with_summary", content="完整原文")
    with_summary.title = "标题"
    store_summary(with_summary, "短摘要", model="m", now=1.0)
    empty = Node("empty", content="")

    refs = material_refs_from_nodes([with_summary, empty])

    assert len(refs) == 1
    assert refs[0]["node"] == "with_summary"
    assert refs[0]["title"] == "标题"
    assert refs[0]["full_text"] == "完整原文"
    assert refs[0]["summary_text"] == "短摘要"
    assert refs[0]["content_hash"] == content_hash("完整原文")


def test_choose_answer_materials_uses_15_percent_probability_but_keeps_one_full():
    first = Node("first", content="第一段原文")
    second = Node("second", content="第二段原文")
    store_summary(first, "第一摘要", model="m", now=1.0)
    store_summary(second, "第二摘要", model="m", now=1.0)
    refs = material_refs_from_nodes([first, second])

    chosen = choose_answer_materials(
        refs,
        rng=FixedRandom([0.01, 0.01]),
        summary_probability=SUMMARY_SUBSTITUTION_PROBABILITY,
    )

    assert [item["mode"] for item in chosen] == ["full", "summary"]
    assert chosen[0]["text"] == "第一段原文"
    assert chosen[1]["text"] == "第二摘要"


def test_single_material_is_always_full_even_when_summary_exists():
    node = Node("solo", content="唯一原文")
    store_summary(node, "唯一摘要", model="m", now=1.0)

    chosen = choose_answer_materials(
        material_refs_from_nodes([node]),
        rng=FixedRandom([0.01]),
    )

    assert len(chosen) == 1
    assert chosen[0]["mode"] == "full"
    assert chosen[0]["text"] == "唯一原文"


def test_format_material_context_marks_full_and_summary_modes():
    full = {
        "node": "n1",
        "title": "材料一",
        "mode": "full",
        "text": "完整内容",
        "content_hash": "h1",
        "summary_hash": None,
    }
    summary = {
        "node": "n2",
        "title": "材料二",
        "mode": "summary",
        "text": "摘要内容",
        "content_hash": "h2",
        "summary_hash": "s2",
    }

    text = format_material_context([full, summary])

    assert "【材料A｜全文｜材料一】" in text
    assert "完整内容" in text
    assert "【材料B｜摘要｜材料二】" in text
    assert "摘要内容" in text
```

- [ ] **Step 2: Run tests to verify they fail because `material_context.py` does not exist**

Run: `python -m pytest test_material_context.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'material_context'`.

- [ ] **Step 3: Implement `material_context.py`**

Create `material_context.py` with:

```python
"""Answer material summary metadata and prompt-context selection."""

from __future__ import annotations

import hashlib
import random
import string
import time
from typing import Iterable

from mgraph import Node

SUMMARY_METADATA_KEY = "llm_summary"
SUMMARY_TARGET_CHARS = 50
SUMMARY_HARD_LIMIT_CHARS = 120
SUMMARY_SUBSTITUTION_PROBABILITY = 0.15


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def summary_hash(text: str | None) -> str | None:
    if not text:
        return None
    return content_hash(text)


def build_summary_prompt(node: Node) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "请把以下材料压缩为不超过50字的中文摘要。"
                "保留核心事实、人物、地点、冲突或结论。"
                "只输出摘要正文，不要解释，不要项目符号。"
            ),
        },
        {"role": "user", "content": node.content or ""},
    ]


def normalize_summary_text(text: str | None) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:SUMMARY_HARD_LIMIT_CHARS]


def get_summary_record(node: Node) -> dict | None:
    record = node.metadata.get(SUMMARY_METADATA_KEY)
    return record if isinstance(record, dict) else None


def summary_is_stale(node: Node, model: str | None = None) -> bool:
    record = get_summary_record(node)
    if not record:
        return True
    if record.get("content_hash") != content_hash(node.content or ""):
        return True
    if model is not None and record.get("model") != model:
        return True
    return not bool(record.get("text"))


def store_summary(node: Node, text: str, model: str, now: float | None = None) -> dict:
    record = {
        "text": normalize_summary_text(text),
        "model": model,
        "content_hash": content_hash(node.content or ""),
        "updated_at": time.time() if now is None else float(now),
    }
    node.metadata[SUMMARY_METADATA_KEY] = record
    return record


def material_refs_from_nodes(nodes: Iterable[Node]) -> list[dict]:
    refs = []
    for node in nodes:
        full_text = (node.content or "").strip()
        if not full_text:
            continue
        record = get_summary_record(node)
        summary_text = None
        if record and not summary_is_stale(node):
            summary_text = normalize_summary_text(record.get("text", ""))
        refs.append(
            {
                "node": node.name,
                "title": node.title or node.name,
                "full_text": full_text,
                "summary_text": summary_text,
                "content_hash": content_hash(full_text),
                "summary_hash": summary_hash(summary_text),
            }
        )
    return refs


def choose_answer_materials(
    materials: list[dict],
    rng=None,
    summary_probability: float = SUMMARY_SUBSTITUTION_PROBABILITY,
) -> list[dict]:
    if rng is None:
        rng = random
    chosen = []
    for material in materials:
        summary_text = material.get("summary_text")
        use_summary = (
            bool(summary_text)
            and len(materials) > 1
            and rng.random() < summary_probability
        )
        mode = "summary" if use_summary else "full"
        chosen.append(
            {
                "node": material["node"],
                "title": material["title"],
                "mode": mode,
                "text": summary_text if mode == "summary" else material["full_text"],
                "content_hash": material["content_hash"],
                "summary_hash": material.get("summary_hash") if mode == "summary" else None,
            }
        )
    if chosen and all(item["mode"] == "summary" for item in chosen):
        first = chosen[0]
        original = next(
            material for material in materials
            if material["node"] == first["node"]
        )
        first["mode"] = "full"
        first["text"] = original["full_text"]
        first["summary_hash"] = None
    return chosen


def format_material_context(chosen: list[dict]) -> str:
    parts = []
    for i, item in enumerate(chosen):
        label = string.ascii_uppercase[i] if i < 26 else str(i + 1)
        mode_label = "摘要" if item["mode"] == "summary" else "全文"
        parts.append(
            f"【材料{label}｜{mode_label}｜{item['title']}】\n{item['text']}"
        )
    return "\n\n---\n\n".join(parts)


def material_trace_records(chosen: list[dict]) -> list[dict]:
    return [
        {
            "node": item["node"],
            "mode": item["mode"],
            "content_hash": item["content_hash"],
            "summary_hash": item.get("summary_hash"),
        }
        for item in chosen
    ]
```

- [ ] **Step 4: Run material context tests**

Run: `python -m pytest test_material_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add material_context.py test_material_context.py
git commit -m "feat: add answer material context selection"
```

### Task 2: Reading Path and AnswerTrace Material Records

**Files:**
- Modify: `operator_core.py`
- Modify: `questnode.py`
- Modify: `operators.py`
- Modify: `runtime/async_operator.py`
- Test: `test_trace.py`
- Test: `test_persistence.py`

- [ ] **Step 1: Write failing tests for reading-path nodes and trace material persistence**

Append these tests:

```python
def test_answer_quest_trace_records_material_modes_with_at_least_one_full():
    g = MGraph()
    n0 = g.add_node(Node("content_a", content="A full text", mg=g))
    n1 = g.add_node(Node("content_b", content="B full text", mg=g))
    n0.link_to(n1, 1.0)
    from material_context import store_summary
    store_summary(n0, "A summary", model="m", now=1.0)
    store_summary(n1, "B summary", model="m", now=1.0)

    op = Operator("bob", n0)
    board = QuestBoard()
    quest = board.post("alice", "q?", g)

    ans = op.answer_quest(quest, board, g, answer_text="manual answer")

    assert ans.trace is not None
    assert len(ans.trace.materials) >= 1
    assert any(item["mode"] == "full" for item in ans.trace.materials)
    assert {item["node"] for item in ans.trace.materials}.issubset(
        set(ans.trace.node_names)
    )
```

Append to `test_persistence.py` inside the answer-node roundtrip test after trace assertions:

```python
    assert a2.trace.materials == [
        {
            "node": "A",
            "mode": "full",
            "content_hash": "content-hash",
            "summary_hash": None,
        }
    ]
```

Also update the fixture trace in that test to include:

```python
        materials=[
            {
                "node": "A",
                "mode": "full",
                "content_hash": "content-hash",
                "summary_hash": None,
            }
        ],
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest test_trace.py test_persistence.py -q`

Expected: FAIL because `AnswerTrace` has no `materials` field and answer flow does not record materials.

- [ ] **Step 3: Add reading-path helper without breaking existing `read_context()` API**

Modify `operator_core.py` so it has:

```python
def read_path(start_node: Node, node_limit: int = 3):
    node_names: list[str] = [start_node.name]
    path_edges: list[tuple[str, str]] = []
    visited: list[Node] = [start_node]
    current = start_node
    for _ in range(node_limit - 1):
        nxt, edge = current.sample_l2()
        if edge is None:
            break
        path_edges.append((current.name, nxt.name))
        node_names.append(nxt.name)
        visited.append(nxt)
        current = nxt
    return node_names, path_edges, visited
```

Then make `read_context()` call `read_path()` and format existing context text from `visited`.

- [ ] **Step 4: Add `materials` to `AnswerTrace` serialization**

Modify `questnode.py`:

```python
    materials: list[dict] = field(default_factory=list)
```

Include `"materials": self.materials` in `to_dict()`, and pass `materials=list(raw.get("materials", []))` in `from_dict()`.

- [ ] **Step 5: Wire synchronous answer flow**

Modify `operators.py`:

```python
from material_context import (
    choose_answer_materials,
    format_material_context,
    material_refs_from_nodes,
    material_trace_records,
)
from operator_core import read_context, read_path, navigate
```

Update `read_for_quest()` to return the old tuple and add:

```python
    def read_materials_for_quest(self, node_limit: int = 3):
        node_names, path_edges, visited = read_path(self.current.get(), node_limit)
        refs = material_refs_from_nodes(visited)
        chosen = choose_answer_materials(refs)
        return node_names, path_edges, format_material_context(chosen), material_trace_records(chosen)
```

In `answer_quest()`, use `read_materials_for_quest()` and put `materials=material_records` into `AnswerTrace`.

In `_llm_ask()`, remove the uncommitted reference-material wrapper and return only `format_question_text(qdata)`.

- [ ] **Step 6: Wire async answer flow**

Modify `runtime/async_operator.py` the same way:

```python
from material_context import choose_answer_materials, format_material_context, material_refs_from_nodes, material_trace_records
from operator_core import read_context, read_path, navigate
```

Add `_read_materials_for_quest()`, use it in `_answer()`, pass `materials=material_records`, and remove the reference-material wrapper from `_llm_ask()`.

- [ ] **Step 7: Run trace and persistence tests**

Run: `python -m pytest test_trace.py test_persistence.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add operator_core.py questnode.py operators.py runtime/async_operator.py test_trace.py test_persistence.py
git commit -m "feat: record answer prompt material choices"
```

### Task 3: Background Summary Job and Token Telemetry

**Files:**
- Create: `runtime/material_summary.py`
- Modify: `async_llm_client.py`
- Modify: `runtime/runtime.py`
- Test: `test_material_summary_runtime.py`
- Test: `test_async_llm_client_usage.py`

- [ ] **Step 1: Write failing tests for summary worker and telemetry action**

Create `test_material_summary_runtime.py` with:

```python
import asyncio

from material_context import SUMMARY_METADATA_KEY
from mgraph import MGraph, Node
from questnode import AnswerNode, QuestNode
from runtime.material_summary import summarize_stale_materials_once
from runtime.monitor import RuntimeMonitor


class FakeAsyncLLM:
    model = "summary-model"

    def __init__(self):
        self.calls = []

    async def chat(self, messages, telemetry_action="chat"):
        self.calls.append((messages, telemetry_action))
        return "这是一个超过五十字约束但仍应被代码硬截断的摘要" * 4


def test_summarize_stale_materials_once_stores_summary_and_skips_qa_nodes():
    async def run():
        graph = MGraph()
        material = Node("material", content="完整材料内容", mg=graph)
        QuestNode("quest", quester_id="Alice", content="q?",).mg
        quest = QuestNode("quest", quester_id="Alice", content="q?")
        answer = AnswerNode("answer", answerer_id="Bob", quest_name="quest", content="a")
        graph.add_node(quest)
        graph.add_node(answer)
        fake = FakeAsyncLLM()

        count = await summarize_stale_materials_once(graph, fake, batch_size=10)

        assert count == 1
        assert len(fake.calls) == 1
        assert fake.calls[0][1] == "summary"
        assert "不超过50字" in fake.calls[0][0][0]["content"]
        assert len(material.metadata[SUMMARY_METADATA_KEY]["text"]) <= 120
        assert SUMMARY_METADATA_KEY not in quest.metadata
        assert SUMMARY_METADATA_KEY not in answer.metadata

    asyncio.run(run())
```

Update `test_async_llm_client_usage.py` with a fake monitor test:

```python
class _FakeMonitor:
    def __init__(self):
        self.events = []

    def report_tokens(self, **kwargs):
        self.events.append(kwargs)


def test_report_tokens_accepts_custom_telemetry_action():
    monitor = _FakeMonitor()
    client = AsyncLLMClient.__new__(AsyncLLMClient)
    client.monitor = monitor
    client.operator_id = "system"

    client._report_tokens([], "摘要", {"usage": {"total_tokens": 9}}, action="summary")

    assert monitor.events == [
        {
            "operator_id": "system",
            "action": "summary",
            "tokens": 9,
            "source": "reported",
        }
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest test_material_summary_runtime.py test_async_llm_client_usage.py -q`

Expected: FAIL because `runtime.material_summary` does not exist and `AsyncLLMClient.chat()` does not accept `telemetry_action`.

- [ ] **Step 3: Add telemetry action parameter to `AsyncLLMClient.chat()`**

Modify signature and reporting call:

```python
    async def chat(self, messages: list[dict], max_retries=3, telemetry_action: str = "chat") -> str:
        ...
                self._report_tokens(messages, text, data, action=telemetry_action)
```

Keep `chat_json()` unchanged.

- [ ] **Step 4: Implement summary worker**

Create `runtime/material_summary.py`:

```python
"""Background material-summary maintenance for the async runtime."""

from __future__ import annotations

import asyncio
import logging

from material_context import build_summary_prompt, store_summary, summary_is_stale
from questnode import AnswerNode, QuestNode

logger = logging.getLogger(__name__)


def _material_nodes(graph):
    return [
        node for node in graph.V
        if not isinstance(node, (QuestNode, AnswerNode)) and (node.content or "").strip()
    ]


async def summarize_stale_materials_once(graph, llm_client, batch_size: int = 2) -> int:
    if llm_client is None:
        return 0
    count = 0
    model = getattr(llm_client, "model", "")
    for node in _material_nodes(graph):
        if count >= batch_size:
            break
        if not summary_is_stale(node, model=model):
            continue
        messages = build_summary_prompt(node)
        try:
            text = await llm_client.chat(messages, telemetry_action="summary")
        except TypeError:
            text = await llm_client.chat(messages)
        except Exception:
            logger.exception("material summary failed for %s", node.name)
            continue
        store_summary(node, text, model=model)
        count += 1
    return count


async def material_summary_loop(runtime, interval_seconds: float = 30.0, batch_size: int = 2):
    while runtime.running:
        await summarize_stale_materials_once(
            runtime.graph,
            runtime.llm_client,
            batch_size=batch_size,
        )
        await asyncio.sleep(interval_seconds)
```

- [ ] **Step 5: Start summary loop from runtime**

Modify `runtime/runtime.py`:

```python
from runtime.material_summary import material_summary_loop
```

In `start()`:

```python
        tasks = [op.run() for op in self.operators.values()]
        tasks.append(self._clock())
        if self.llm_client is not None:
            tasks.append(material_summary_loop(self))
```

- [ ] **Step 6: Run worker and telemetry tests**

Run: `python -m pytest test_material_summary_runtime.py test_async_llm_client_usage.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add async_llm_client.py runtime/material_summary.py runtime/runtime.py test_material_summary_runtime.py test_async_llm_client_usage.py
git commit -m "feat: summarize materials in background"
```

### Task 4: Token Throughput Stabilization and Full Verification

**Files:**
- Modify: `runtime/monitor.py`
- Modify: `runtime/dashboard.html`
- Modify: `runtime/server.py`
- Test: `test_runtime_monitor_dashboard.py`
- Test: `test_dashboard_snapshot.py`

- [ ] **Step 1: Keep the current token-throughput tests and add one explicit bucket assertion if missing**

Ensure `test_dashboard_snapshot.py` asserts:

```python
    assert snapshot["tokens"]["tokens_per_sec"] == 0.9
    assert len(snapshot["tokens"]["tps_series"]) == 24
    assert snapshot["tokens"]["tps_series"][20] == 11.0
```

Ensure `test_runtime_monitor_dashboard.py` still asserts totals, last-minute counts, reported/estimated request counts, and token event subscription.

- [ ] **Step 2: Run focused token tests**

Run: `python -m pytest test_runtime_monitor_dashboard.py test_dashboard_snapshot.py test_async_llm_client_usage.py -q`

Expected: PASS.

- [ ] **Step 3: Commit token-flow changes only if still uncommitted**

```bash
git add runtime/monitor.py runtime/dashboard.html runtime/server.py test_dashboard_snapshot.py test_runtime_monitor_dashboard.py
git commit -m "feat: show token throughput series"
```

If these files are already committed or unchanged, skip the commit.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Inspect final dirty worktree and leave generated runtime artifacts out of commits**

Run: `git status --short`

Expected: remaining dirty files, if any, are runtime-generated artifacts under `data/`, `data/meta/`, or `__pycache__/`, or unrelated user changes that should not be included.
