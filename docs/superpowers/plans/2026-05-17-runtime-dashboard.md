# Runtime Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI runtime dashboard with token throughput metrics and a smooth live D3 force-directed graph.

**Architecture:** Extend `RuntimeMonitor` into the telemetry hub, add usage reporting to `AsyncLLMClient`, expose a full dashboard snapshot/stream from `runtime/server.py`, and replace the root HTML with a single-file D3 dashboard. Keep the existing Gradio app and tag UI intact.

**Tech Stack:** Python, FastAPI, SSE via `sse-starlette`, in-memory dataclasses/deques, browser-native HTML/CSS/JS, D3 v7 from CDN.

---

## File Structure

- Modify `runtime/monitor.py`: add token telemetry, dashboard event subscribers, and token snapshot helpers.
- Modify `async_llm_client.py`: extract provider usage, estimate fallback tokens, and report usage to the monitor.
- Modify `runtime/runtime.py`: pass monitor to `AsyncLLMClient`, track startup time, and pass the runtime object to `run_server`.
- Modify `runtime/server.py`: add runtime-aware snapshot/stream endpoints and define `DASHBOARD_HTML`.
- Create `test_runtime_monitor_dashboard.py`: focused monitor telemetry tests.
- Create `test_async_llm_client_usage.py`: async usage extraction and fallback tests.
- Create `test_dashboard_snapshot.py`: snapshot shape test with a fake runtime.

---

### Task 1: RuntimeMonitor Telemetry

**Files:**
- Modify: `runtime/monitor.py`
- Test: `test_runtime_monitor_dashboard.py`

- [ ] **Step 1: Write monitor telemetry tests**

Create `test_runtime_monitor_dashboard.py`:

```python
import time

from runtime.monitor import RuntimeMonitor


def test_monitor_records_token_usage_totals_and_window():
    monitor = RuntimeMonitor()
    now = time.time()

    monitor.report_tokens(
        operator_id="Alice",
        action="answer",
        tokens=120,
        source="reported",
        timestamp=now - 30,
    )
    monitor.report_tokens(
        operator_id="Bob",
        action="score",
        tokens=80,
        source="estimated",
        timestamp=now - 90,
    )

    snap = monitor.token_snapshot(now=now)

    assert snap["total"] == 200
    assert snap["last_minute"] == 120
    assert snap["requests"] == 2
    assert snap["reported"] == 1
    assert snap["estimated"] == 1
    assert snap["series"][-1]["tokens"] == 80


def test_monitor_dashboard_event_subscription_gets_operator_and_token_events():
    monitor = RuntimeMonitor()
    q = monitor.subscribe_events()

    monitor.report_action("Alice", "wander", "node-a")
    monitor.report_tokens("Alice", "wander", 33, "reported")

    first = q.get_nowait()
    second = q.get_nowait()

    assert first["type"] == "operator_update"
    assert first["operator"]["id"] == "Alice"
    assert second["type"] == "token_usage"
    assert second["tokens"]["tokens"] == 33
```

- [ ] **Step 2: Run monitor tests and verify failure**

Run:

```powershell
python -m pytest test_runtime_monitor_dashboard.py -q
```

Expected: fail because `report_tokens`, `token_snapshot`, and `subscribe_events` do not exist.

- [ ] **Step 3: Implement monitor telemetry**

In `runtime/monitor.py`, add `TokenUsageEvent`, event subscribers, and methods:

```python
@dataclass
class TokenUsageEvent:
    operator_id: str
    action: str
    tokens: int
    source: str = "estimated"
    timestamp: float = 0.0
```

`RuntimeMonitor.__init__` should initialize:

```python
self._event_subscribers: list[asyncio.Queue[dict]] = []
self._token_events = deque(maxlen=512)
self._total_tokens = 0
self._reported_requests = 0
self._estimated_requests = 0
```

Add:

```python
def subscribe_events(self) -> asyncio.Queue[dict]:
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=128)
    self._event_subscribers.append(q)
    return q

def unsubscribe_events(self, q: asyncio.Queue[dict]):
    if q in self._event_subscribers:
        self._event_subscribers.remove(q)

def report_tokens(self, operator_id: str, action: str, tokens: int, source: str = "estimated", timestamp: float | None = None):
    event = TokenUsageEvent(
        operator_id=operator_id,
        action=action,
        tokens=max(0, int(tokens or 0)),
        source="reported" if source == "reported" else "estimated",
        timestamp=time.time() if timestamp is None else float(timestamp),
    )
    self._token_events.append(event)
    self._total_tokens += event.tokens
    if event.source == "reported":
        self._reported_requests += 1
    else:
        self._estimated_requests += 1
    self._push_event({
        "type": "token_usage",
        "tokens": {
            "operator_id": event.operator_id,
            "action": event.action,
            "tokens": event.tokens,
            "source": event.source,
            "timestamp": event.timestamp,
        },
    })

def token_snapshot(self, now: float | None = None) -> dict:
    now = time.time() if now is None else float(now)
    last_minute = sum(e.tokens for e in self._token_events if now - e.timestamp <= 60.0)
    return {
        "total": self._total_tokens,
        "last_minute": last_minute,
        "requests": self._reported_requests + self._estimated_requests,
        "reported": self._reported_requests,
        "estimated": self._estimated_requests,
        "series": [
            {
                "t": e.timestamp,
                "operator_id": e.operator_id,
                "action": e.action,
                "tokens": e.tokens,
                "source": e.source,
            }
            for e in self._token_events
        ],
    }
```

Extend `report_action` to also call `_push_event(...)` with an `operator_update` event.

- [ ] **Step 4: Run monitor tests and commit**

Run:

```powershell
python -m pytest test_runtime_monitor_dashboard.py -q
```

Expected: pass.

Commit:

```powershell
git add runtime/monitor.py test_runtime_monitor_dashboard.py
git commit -m "feat: add runtime monitor telemetry"
```

---

### Task 2: Async LLM Token Reporting

**Files:**
- Modify: `async_llm_client.py`
- Modify: `runtime/runtime.py`
- Test: `test_async_llm_client_usage.py`

- [ ] **Step 1: Write token extraction tests**

Create `test_async_llm_client_usage.py`:

```python
from types import SimpleNamespace

from async_llm_client import AsyncLLMClient


def test_extract_usage_prefers_total_tokens():
    data = {"usage": {"total_tokens": 42, "prompt_tokens": 20, "completion_tokens": 22}}
    assert AsyncLLMClient._usage_tokens(data, [], "") == (42, "reported")


def test_extract_usage_sums_prompt_and_completion_tokens():
    data = {"usage": {"prompt_tokens": 11, "completion_tokens": 7}}
    assert AsyncLLMClient._usage_tokens(data, [], "") == (18, "reported")


def test_extract_usage_falls_back_to_estimate():
    messages = [{"role": "user", "content": "hello world"}]
    tokens, source = AsyncLLMClient._usage_tokens({}, messages, "reply")

    assert tokens >= 1
    assert source == "estimated"
```

- [ ] **Step 2: Run token tests and verify failure**

Run:

```powershell
python -m pytest test_async_llm_client_usage.py -q
```

Expected: fail because `_usage_tokens` is not implemented.

- [ ] **Step 3: Implement usage extraction and monitor reporting**

Change `AsyncLLMClient.__init__` to accept:

```python
def __init__(self, config, monitor=None, operator_id: str | None = None):
```

Add static helpers equivalent to `LLMClient._usage_tokens`, but returning `(tokens, source)`.

After a successful API response in `chat()` and `chat_json()`, call:

```python
self._report_tokens(messages, text, data, action="chat")
```

with:

```python
def _report_tokens(self, messages, text, response_data, action: str):
    if self.monitor is None:
        return
    tokens, source = self._usage_tokens(response_data, messages, text)
    self.monitor.report_tokens(
        operator_id=self.operator_id or "",
        action=action,
        tokens=tokens,
        source=source,
    )
```

In `runtime/runtime.py`, create the async client with:

```python
self.llm_client = AsyncLLMClient(self.config, monitor=self.monitor) if self.config.api_key else None
```

The first implementation reports aggregate async-client usage under an empty operator id because calls do not pass operator id into the shared client. Operator-level token attribution is outside this implementation boundary and requires passing owner context into each call.

- [ ] **Step 4: Run token tests and commit**

Run:

```powershell
python -m pytest test_async_llm_client_usage.py test_runtime_monitor_dashboard.py -q
```

Expected: pass.

Commit:

```powershell
git add async_llm_client.py runtime/runtime.py test_async_llm_client_usage.py
git commit -m "feat: report async llm token usage"
```

---

### Task 3: Dashboard Snapshot and Stream API

**Files:**
- Modify: `runtime/server.py`
- Modify: `runtime/runtime.py`
- Test: `test_dashboard_snapshot.py`

- [ ] **Step 1: Write snapshot shape test**

Create `test_dashboard_snapshot.py` with small fake runtime objects and assert `_build_dashboard_snapshot()` returns `ready`, `stats`, `tokens`, `operators`, `graph`, and `quests`.

- [ ] **Step 2: Implement server state and helpers**

In `runtime/server.py`, add a global `runtime_ref = None`.

Add `_build_dashboard_snapshot(runtime_obj=None, monitor_obj=None)` that:

- returns `{"ready": False, ...}` if no runtime is available
- reads `runtime.graph.V`, `runtime.graph.E`, `runtime.board.active`, `runtime.board.completed`, `runtime.round`, `runtime.running`
- reads `monitor.snapshot()` for operators
- reads `monitor.token_snapshot()` for token counters

Add graph helpers:

```python
def _node_kind(node):
    if isinstance(node, QuestNode):
        return "quest"
    if isinstance(node, AnswerNode):
        return "answer"
    return getattr(node, "kind", "document")
```

Nodes include `id`, `label`, `kind`, `tags`, `degree`, and `activeOperators`.

Links include `id`, `source`, `target`, and `weight`.

- [ ] **Step 3: Add routes**

Add:

```python
@app.get("/api/dashboard/snapshot")
async def dashboard_snapshot():
    return _build_dashboard_snapshot(runtime_ref, monitor)

@app.get("/api/dashboard/stream")
async def dashboard_stream(request: Request):
    ...
```

The stream uses `monitor.subscribe_events()` and emits `"dashboard"` events with JSON payloads, plus ping timeouts.

- [ ] **Step 4: Pass runtime into server**

Change `run_server(...)` signature to accept `runtime_instance=None` and set global `runtime_ref`.

In `runtime/runtime.py`, call:

```python
server_task = asyncio.create_task(
    run_server(
        monitor,
        port=args.port,
        tag_manager_instance=runtime.tag_manager,
        runtime_instance=runtime,
    )
)
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m pytest test_dashboard_snapshot.py test_runtime_monitor_dashboard.py test_async_llm_client_usage.py -q
```

Expected: pass.

Commit:

```powershell
git add runtime/server.py runtime/runtime.py test_dashboard_snapshot.py
git commit -m "feat: expose dashboard runtime snapshot"
```

---

### Task 4: Single-Page Dashboard Frontend

**Files:**
- Modify: `runtime/server.py`

- [ ] **Step 1: Define `DASHBOARD_HTML`**

Add a raw HTML string before `TAGS_HTML` in `runtime/server.py`.

Required DOM regions:

```html
<section class="kpis" id="kpis"></section>
<main class="dashboard-grid">
  <section class="graph-panel">
    <svg id="graph"></svg>
    <div id="graph-empty"></div>
  </section>
  <aside class="side-panel">
    <section id="operators"></section>
    <section id="token-chart"></section>
  </aside>
</main>
<section class="bottom-grid">
  <section id="events"></section>
  <section id="quests"></section>
</section>
```

- [ ] **Step 2: Implement D3 graph lifecycle**

The script must:

- fetch `/api/dashboard/snapshot`
- open `/api/dashboard/stream`
- create the SVG and simulation once
- merge nodes and links by stable id
- preserve node positions across updates
- configure `forceLink`, `forceManyBody`, `forceCollide`, `forceX`, `forceY`, and `forceCenter`
- use drag handlers with `alphaTarget`
- update only DOM attributes on tick

- [ ] **Step 3: Implement KPI, operators, token sparkline, and event rendering**

Render:

- KPI cells from `snapshot.stats`, `snapshot.runtime`, and `snapshot.tokens`
- operator rows from `snapshot.operators`
- an SVG sparkline from `snapshot.tokens.series`
- recent events from SSE payloads
- quest counts from `snapshot.quests`

- [ ] **Step 4: Run syntax checks and commit**

Run:

```powershell
python -m py_compile runtime/server.py
```

Expected: no output and exit code 0.

Commit:

```powershell
git add runtime/server.py
git commit -m "feat: add d3 runtime dashboard"
```

---

### Task 5: Runtime Verification

**Files:**
- No source changes unless verification exposes a bug.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest test_runtime_monitor_dashboard.py test_async_llm_client_usage.py test_dashboard_snapshot.py -q
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: pass, or record unrelated pre-existing failures with exact test names.

- [ ] **Step 3: Start runtime dashboard smoke**

Run:

```powershell
python -m runtime --web --timeout 20 --port 8763
```

Expected:

- server logs show dashboard URL
- `/api/dashboard/snapshot` returns a ready snapshot while running
- root `/` serves HTML containing `id="graph"`

- [ ] **Step 4: Final commit if fixes were needed**

If verification required fixes:

```powershell
git add runtime\\monitor.py async_llm_client.py runtime\\runtime.py runtime\\server.py test_runtime_monitor_dashboard.py test_async_llm_client_usage.py test_dashboard_snapshot.py
git commit -m "fix: stabilize runtime dashboard verification"
```

If no fixes were needed, do not create an empty commit.
