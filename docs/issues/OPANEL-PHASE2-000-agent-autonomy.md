# OPANEL-PHASE2-000: Agent Autonomy PRD

Type: Parent
Label: ready-for-agent

## This Document Wants

This PRD wants Phase 2 to turn an Operator from a visible but mostly reactive loop into an autonomous Actor that can:

- notice when its local graph context is insufficient;
- decide which action is worth taking next;
- search outside the graph when needed;
- create graph artifacts from its own observations;
- communicate findings or requests to User and other Operators;
- use the same panel primitives as User Actor, not a separate hidden control path;
- explain why an action was selected.

In other words, this is not only a "web search feature". Web search is one tool inside a larger autonomy upgrade.

## Inferred Real Intent

The real intent is to prove the philosophical claim behind the Actor Panel work:

> User and LLM Operator are operationally isomorphic. They differ in embodiment and policy, not in allowed primitives.

Phase 1 makes this visible by giving User and Operator the same panel shape. Phase 2 should make it operational: Operator must be able to use the same primitives that the User can use, then extend them with autonomous decision policy.

The deeper product goal is a self-growing knowledge graph. Human Source remains immutable seed material, while Operators continuously produce new artifacts, external evidence nodes, messages, questions, answers, scores, and notes. The graph should grow through observable Actor actions, not through hidden backend magic.

## Current Baseline And Dependency

Phase 2 depends on OPANEL-MVP, but should not pretend OPANEL-MVP is already shipped unless those issues are complete. The hard dependency is:

- `ActorPanelState`
- User Actor
- shared stash structure
- shared message node plus queue-item structure
- note/reply artifact commit
- dashboard actor selection
- panel event stream

If any of those are missing, Phase 2 must either wait or add only a narrow compatibility shim that does not fork the data model.

Existing repo capabilities that Phase 2 should reuse:

- `AsyncOperator` loop with `wander / ask / answer / score / idle / sleep`
- `OperatorRuntime` lifecycle and shared graph/board/bus state
- `RuntimeMonitor` snapshots and SSE event stream
- `MessageBus` per-operator queues
- `QuestBoard`, `QuestNode`, `AnswerNode`, `AnswerTrace`
- split persistence: `data/human/*.md`, `data/operator/artifacts.json`, `data/meta/*.json`
- `Persona` / MBTI prompt style
- Persona/MBTI policy is intentionally undecided for new systems. Any Phase 2 feature that wants to use Persona/MBTI as a behavior signal must ask the user and record that decision before implementation.
- token telemetry from LLM calls

## Problem Statement

After Phase 1, the system will have a visible shared panel protocol, but Operator autonomy is still incomplete in four ways.

1. **Operators cannot expand the world.**  
   They can traverse and transform the existing graph, but they cannot acquire external evidence. This makes the graph a closed system.

2. **Operators do not use the full Actor primitive set.**  
   User Actor can stash, message, and commit notes/replies through the panel. Operator actions still mostly live in the older `wander / ask / answer / score` loop.

3. **Action choice is not explainable enough for larger action sets.**  
   `RandomDecider` is acceptable for a small toy loop. It becomes unhelpful once actions include search, stash, message, note, re-read, and sleep.

4. **Tool execution and action selection are conflated.**  
   The system needs to separate "what action should this Actor take?" from "how does the Actor draft a query/message/note?". Otherwise every tick becomes an expensive opaque LLM decision.

## Recommended Product Direction

Use a two-layer autonomy architecture.

### Layer 1: Action Selection

A fast, observable, mostly deterministic policy chooses the next action from available actions. It uses graph and panel signals:

- pending message count;
- open quest pressure;
- own active quest pressure;
- current node out-degree and in-degree;
- current node freshness;
- stash age and stash size;
- STK pressure;
- recent repeated actions;
- web search cooldown;
- token budget.

This layer should produce a decision trace, not only an action. The trace should show top signals and final weights.

### Layer 2: Tool Execution

After an action is chosen, execution can use LLM/tool calling only where language quality is needed:

- generate a web search query;
- summarize why a result matters;
- draft a message;
- draft a note;
- choose which stash items to cite in an answer.

This keeps the runtime cheap and observable while still allowing high-quality language output.

## Capabilities Worth Improving Or Adding

### 1. Complete Operator Use Of Panel Primitives

Before adding web search, Operator should be able to use the same Actor primitives as User:

- stash current node;
- read stash;
- send message;
- receive/select/complete/delete message nodes through queue items;
- commit note artifact;
- commit reply artifact;
- expose all of the above through `ActorPanelState`.

This is the highest-priority Phase 2 work because it validates the isomorphism principle.

### 2. Message Semantics And Routing

The PRD should distinguish system messages from actor-level messages.

- System messages: `ClockTick`, `QuestPosted`, `AnswerSubmitted`, `AnswerScored`.
- Actor messages: graph-persisted communication artifacts visible through panel queues, such as `info`, `question`, `alert`, `result`, `request_review`.

Actor messages should use `kind: "artifact"` with `metadata.artifact_type: "actor_message"`. Their body is a detailed short essay that may contain a question, an answer, and an embedded request. The queue remains an acceptable implementation structure, but it should hold delivery/selection/status references to message nodes rather than becoming the only durable form of the message.

Actor messages need stable ids, sender, recipient, summary/title, body, payload metadata, queue status, and timestamps. They must be observable and soft-deletable from the queue without deleting the message node by default.

### 3. Artifact Types Beyond Quest/Answer

Phase 2 should explicitly add or formalize artifact kinds:

- `note`: observation attached to current node;
- `actor_message`: a graph-persisted communication short essay routed through Actor queues;
- `reply`: response to a visible message, quest, or selected artifact;
- `web_page`: external evidence result, represented as `kind: "artifact"` with `metadata.artifact_type: "web_page"`;
- `search_report`: essay-style summary and reflection for one search session;
- `patch_suggestion`: later, for suggested edits to Human Source.

All are Operator/User artifacts. None may mutate Human Source.

### 4. Web Search As External Evidence Ingestion

Web search should be implemented as evidence ingestion, not a generic browser.

Required behavior:

- search query is generated from current node, selected message, selected quest, or stash context;
- results become artifact graph nodes with `kind: "artifact"` and `metadata.artifact_type: "web_page"`;
- results are imported directly without pre-approval, but always as unverified Operator Artifacts;
- imported web evidence is snippet-first by default; full extracted content is fetched only through a later explicit tool/action;
- metadata includes URL, title, snippet, fetched_at, backend, query, actor_id, trust_level, content_mode;
- each result links back to the source context node or message-derived anchor;
- each search action with at least one imported result creates a `search_report` artifact;
- empty or failed searches do not create a `search_report`; they only emit monitor events;
- the report body is a single essay-style main text: summarize and synthesize the search materials, then write a reflection inspired by those materials;
- do not split the main report body into claims, observations, limits, or other small structured sections;
- search does not automatically move the Operator cursor to the report; cursor remains on the triggering node unless a later explicit navigation action moves it;
- a generated `search_report` is automatically added to the Operator's stash with reason `search_report`; individual `web_page` artifacts are not auto-stashed;
- `search_report` and imported `web_page` artifacts are globally visible graph nodes, but search does not broadcast actor-level messages by default;
- initial edge weight should be lower than edges derived from Human Source or explicit answers;
- dashboard visually distinguishes external evidence nodes;
- monitor records search started, result imported, search failed.

Search should default to a mockable backend in tests. Real network use must be optional.

### 5. Decision Trace

The EnhancedDecider should not only choose actions. It must report why:

```json
{
  "actor_id": "Alice",
  "temperature": 0.3,
  "chosen": "search_web",
  "raw_scores": {
    "wander": 0.2,
    "answer": 0.7,
    "search_web": 1.4,
    "idle": 0.1
  },
  "probabilities": {
    "wander": 0.08,
    "answer": 0.18,
    "search_web": 0.74,
    "idle": 0.02
  },
  "top_signals": [
    {"name": "current_node_low_outdegree", "action": "search_web", "delta": 0.6},
    {"name": "message_pending", "action": "reply_to_message", "delta": 0.4}
  ]
}
```

This trace is part of the product surface because the user is observing autonomous Operators in real time.

### 6. Guardrails

Autonomy needs practical limits:

- web search cooldown per actor;
- max imported results per search;
- token budget per runtime window;
- action repeat penalty;
- no autonomous delete;
- no automatic Human Source mutation;
- optional allowlist/denylist for search domains;
- disabled-by-default real network backend in tests.

### 7. Stash-As-Memory

Stash should stop being only a visible list. It should influence Operator context:

- old stash items can trigger re-read;
- selected stash items can enter answer/note/search context;
- stash age and size feed the decider;
- stale stash should be deprioritized, not silently deleted.

### 8. Deferred Memory / Impression Layer

Phase 2 does not implement a dedicated realtime memory layer. A later Phase 3 may insert a dynamically maintained memory/impression block before normal prompt content. That block would be available to the LLM but not mandatory to use. Its maintenance strategy remains a Phase 3 design decision.

## User Stories

1. As a User, I want Operator and User panels to expose the same primitive actions, so that I can verify the isomorphism claim.
2. As an Operator, I want to stash a node I find relevant, so that I can return to it without random traversal.
3. As an Operator, I want to create a note artifact attached to my current node, so that my observations become part of the graph.
4. As an Operator, I want to send a visible message to User or another Operator, so that coordination happens through the same panel queue the User sees.
5. As an Operator, I want messages addressed to me to appear in my panel queue, so that I can process them in my action loop.
6. As an Operator, I want to search for external evidence when local context is thin or a message asks for outside information, so that the graph can grow beyond seed material.
7. As a User, I want search-result nodes to show source URL and fetch time, so that external evidence is auditable.
8. As a User, I want to see Operator search activity and failures in Recent Events, so that autonomous ingestion is not hidden.
9. As an Operator, I want my decision policy to consider messages, quests, stash, graph topology, and budget, so that action choice is not pure random drift.
10. As a User, I want to see the decision trace behind an Operator action, so that I can judge whether it is acting sensibly.
11. As an Operator, I want LLM drafting only when language is needed, so that routine decisions remain fast and cheap.
12. As a maintainer, I want search and LLM-backed tools to be mockable, so that tests do not depend on network or paid APIs.

## Functional Requirements

### FR1: Operator Panel Primitive Parity

Operator can perform the same primitive operations defined by OPANEL-MVP:

- stash current node;
- read stash;
- send message;
- receive message;
- select message;
- mark message done;
- soft-delete message;
- commit note artifact;  (deferred to Phase 3)
- commit reply artifact.

These operations must update the same `ActorPanel` structures used by User Actor.

Implementation strategy: extract a shared `ActorPanel` component from MVP's `UserActor`, then have both `UserActor` and `AsyncOperator` hold their own `ActorPanel` instance. This avoids forking the data model and keeps the isomorphism principle intact.

### FR2: Tool Registry

Introduce a registry for Operator-executable tools. Initial tools:

| Tool | Purpose | Writes graph? | Uses LLM? |
|---|---|---:|---:|
| `stash_current` | Add current node to actor stash | No | No |
| `send_message` | Create an `actor_message` artifact and enqueue it for recipients | Yes | Optional |
| `create_note` | Create note artifact on current node | Yes | Optional | *(deferred to Phase 3)* |
| `create_reply` | Reply to selected message or quest | Yes | Optional |
| `search_web` | Import external evidence nodes | Yes | Optional query drafting |
| `write_search_report` | Built-in post-step of `search_web`, not a standalone Decider action | Yes | Yes |
| `fetch_web_page` | Fetch full content for a previously imported web evidence node | Yes | No |
| `read_stash` | Return stash context | No | No |

Tool execution should report monitor events and return structured results for tests.

### FR3: Web Search Service

Add a search abstraction:

```python
@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str | None
    source: str

class WebSearchService(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...
```

Backends:

- `FakeSearchService` for tests;
- `TavilySearchService` or equivalent API backend, optional;
- `DirectFetchService` only as fetch-by-URL or fallback extraction, not as true search unless explicitly configured.

Search import behavior:

- create `kind: "artifact"` nodes with `metadata.artifact_type: "web_page"`;
- store them under operator artifact storage;
- attach metadata: `source_url`, `title`, `snippet`, `fetched_at`, `query`, `backend`, `actor_id`, `trust_level: "unverified"`, `content_mode: "snippet_only"`;
- link each imported node to the triggering context node;
- use a low initial edge weight for imported evidence links;
- avoid duplicate URL imports in the same graph unless content changed or force is requested.
- create one `search_report` artifact for every search session that imports at least one result.
- do not create a `search_report` for empty or failed searches; emit monitor events instead.
- if full content is fetched later, update `content_mode: "content_fetched"`, store `content_hash`, and enforce a maximum content length.

Search report behavior:

- represent the report as `kind: "artifact"` with `metadata.artifact_type: "search_report"`;
- set `metadata.status` to `useful`;
- store query, triggering context, and imported result ids in metadata;
- write the report content as one coherent main text, like an essay prompt: "以上材料说明了什么？这些材料引发了怎样的联想和反思？";
- include summary/synthesis and reflection in the prose, without forcing a claim/evidence/limits schema;
- default to Chinese prose;
- do not output JSON or bullet lists;
- do not become the Operator's current node automatically.
- automatically enter the Operator's stash with reason `search_report`.
- remain globally visible through the graph without automatically notifying User or other Operators.

### FR4: EnhancedDecider

Add `EnhancedDecider` beside `RandomDecider`, not as a breaking replacement.

It should support:

- base action weights;
- pluggable signal sources;
- **softmax + temperature sampling**: temperature → 0 is deterministic, temperature → ∞ approximates uniform RandomDecider;
- cooldown and budget signals;
- repeat-action penalty;
- decision trace emission (raw_scores + softmax probabilities).

Initial signal sources:

- `MessagePendingSignal`
- `QuestPressureSignal`
- `GraphFrontierSignal`
- `StashPressureSignal`
- `StkPressureSignal`
- `BudgetSignal`

### FR5: Dashboard Observability

Dashboard should show:

- latest chosen action per Operator;
- decision trace summary;
- web search events;
- search-result nodes visually distinguished by `metadata.artifact_type: "web_page"`;
- search reports visually distinguished by `metadata.artifact_type: "search_report"`;
- whether web evidence is `snippet_only` or `content_fetched`;
- actor-level messages in panel queues;
- artifact nodes created by Operator tools.

Dashboard should not become the place for tuning every decider weight in Phase 2. Configuration can stay file-based.

### FR6: Configuration

Add configuration for:

```json
{
  "decider": "random|enhanced",
  "web_search": {
    "enabled": false,
    "backend": "fake|tavily|direct_fetch",
    "api_key_env": "TAVILY_API_KEY",
    "max_results": 5,
    "cooldown_seconds": 60,
    "allowed_domains": [],
    "blocked_domains": []
  },
  "autonomy": {
    "max_repeated_action": 3,
    "decider_temperature": 0.3
  }
}
```

Token budget 由全局 `RequestPool`（15s 滑动窗口 / 250K tokens）天然提供，不另设 per-hour 计数器。`BudgetSignal` 取 `pool.used_tokens / pool.token_budget` 做全域衰减因子。

Defaults must keep tests offline and deterministic.

## Non-Functional Requirements

- No real network calls in unit tests.
- No paid API requirement for smoke tests.
- All new artifacts persist through existing split persistence.
- Human Source remains immutable.
- Operator action loops should not block on long web requests without timeout.
- All tool failures become observable events, not swallowed exceptions.
- The system should be useful with `RandomDecider` disabled and `EnhancedDecider` enabled, but both paths remain testable.

## Out Of Scope

- Multi-round debate or negotiation protocol between Operators.
- Full browser automation or JavaScript-rendered page browsing.
- Autonomous deletion of graph nodes.
- Automatic mutation of Human Source.
- Online reinforcement learning.
- Search result TTL deletion.
- Full decider weight tuning UI.
- Treating LLM function calling as the top-level action selector on every tick.
- Dedicated Memory / Impression Layer prompt prefixing; this is deferred to Phase 3.

## Implementation Slices

### Dependency Map

```
Slice-003 (Actor Panel) ─────────────────┐
Slice-005 (EnhancedDecider) ────────────┐├→ Slice-002 (Actor Message)
Slice-008 (Search Backend Abstraction) ─┼┤
Slice-001 (Web Search Primitive) ───────┘┤
                                         ├→ Slice-004 (Memory) → Phase 3
Slice-006 (UI/UX) ───────────────────────┘
Slice-007 (Graph Concurrency Lock) ──── 可独立在任何阶段做
```

### Recommended Execution Order

1. **OPANEL-PHASE2-SLICE-003: Actor Panel Primitive Parity** — 提取共享 `ActorPanel`、stash 持久化、为 Operator 增加 stash/message/reply 能力。一切的上游。

2. **OPANEL-PHASE2-SLICE-005: EnhancedDecider And Decision Trace** — softmax + temperature 决策器、6 信号源、决策 trace。

3. **OPANEL-PHASE2-SLICE-008: Search Backend Abstraction** — `SearchBackend(ABC)`、FakeSearchService、Tavily 实现。轻量接口。

4. **OPANEL-PHASE2-SLICE-001: Web Search Evidence Ingestion** — `search_web` 工具、URL 级去重、`web_page` artifact 导入、`write_search_report` 内置后处理、冷却硬门。

5. **OPANEL-PHASE2-SLICE-002: Actor Message Semantics** — 消息阅读管线、envelope/body 两层协议、PATIENCE 约束、`send_message`/`reply_to_message` 工具。

6. **OPANEL-PHASE2-SLICE-006: Dashboard Autonomy Observability** — 新增 search_activity、message 面板、决策 trace 展示。

7. **OPANEL-PHASE2-SLICE-007: Graph Concurrency Lock** — `asyncio.Lock` 包裹 URL 去重 + 节点导入原子操作、force_normalize 加锁。

8. **OPANEL-PHASE2-SLICE-004: Operator Artifact Tools (Phase 3)** — `create_note` 延期。

9. **OPANEL-PHASE2-SLICE-000: Acceptance Smoke** — 整合验收测试。

### Slice Descriptions

### OPANEL-PHASE2-SLICE-003: Actor Panel Primitive Parity

提取共享 `ActorPanel` 组件，`UserActor` 和 `AsyncOperator` 各自持有一个实例。Operator 获得 stash/note/reply 等同级原语。Stash 写入 `data/operator/stash-{op_id}.json` 持久化。

### OPANEL-PHASE2-SLICE-005: EnhancedDecider And Decision Trace

Signal-based 决策器（softmax + temperature），6 个信号源（MessagePending、QuestPressure、GraphFrontier、StashPressure、StkPressure、Budget），决策 trace 输出 raw_scores + probabilities。`RandomDecider` 保持可用。

### OPANEL-PHASE2-SLICE-008: Search Backend Abstraction

`SearchBackend(ABC)`：`search(query, max_results) → list[SearchResult]`。默认实现 DuckDuckGo（免费、无需 API key）或 FakeSearchService（测试用）。可选的 Tavily 后端。

### OPANEL-PHASE2-SLICE-001: Web Search Evidence Ingestion

`search_web` 工具：搜索 → URL 级去重 → `web_page` artifact 导入 → `write_search_report` 内置后处理。冷却硬门（cooldown_seconds 内 search_web 信号权重为 0）。日用品搜索导入功能。

### OPANEL-PHASE2-SLICE-002: Actor Message Semantics

两层协议：envelope（msg_type、sender、recipients、in_reply_to、priority、status）+ body（自由中文短文章）。消息阅读管线（→ current_context → LLM prompt 注入 → Decider 信号）。PATIENCE 只约束 Actor Message。

### OPANEL-PHASE2-SLICE-006: Dashboard Autonomy Observability

`RuntimeMonitor` 新增 search_activity 槽、actor message 队列视图、决策 trace 展示。TUI 新增可选消息面板。

### OPANEL-PHASE2-SLICE-007: Graph Concurrency Lock

`MGraph` 加 `asyncio.Lock`，URL 去重 + 节点导入原子操作。`force_normalize()` 也走同一锁。

### OPANEL-PHASE2-SLICE-004: Operator Artifact Tools (延期至 Phase 3)

`create_note` 延期至 Phase 3。

### OPANEL-PHASE2-SLICE-000: Phase 2 Acceptance Smoke

离线冒烟测试覆盖：primitive parity、fake search 导入、消息路由、artifact 创建、decider trace、persistence、dashboard snapshot shape。

## Acceptance Criteria

- [ ] Operator can stash, message, and create note/reply artifacts through the same panel primitives as User Actor.
- [ ] Actor-level messages are persisted as `kind: "artifact"` nodes with `metadata.artifact_type: "actor_message"`.
- [ ] Target panel queues reference actor message nodes and support selection, done, and soft delete without deleting the message node by default.
- [ ] Actor message body is treated as a detailed short essay that can contain question, answer, and request content.
- [ ] Fake web search imports artifact nodes with `metadata.artifact_type: "web_page"`, source metadata, and graph links.
- [ ] Imported web evidence enters the graph directly with `trust_level: "unverified"` and low initial edge weight.
- [ ] Imported web evidence defaults to `content_mode: "snippet_only"`.
- [ ] Search actions with imported results create a `search_report` artifact linked to the triggering context and imported web evidence.
- [ ] Empty or failed searches emit monitor events and do not create `search_report` artifacts.
- [ ] Search reports record `metadata.status` as `useful`.
- [ ] Search report content is one coherent essay-style main text that summarizes/synthesizes materials and reflects on them, not a fragmented claims schema.
- [ ] Search report prompt asks for default Chinese prose and rejects JSON/list output.
- [ ] Search does not move the Operator cursor automatically; cursor remains on the triggering node.
- [ ] Generated search reports are automatically added to the Operator stash; imported web pages are not auto-stashed.
- [ ] Search artifacts are globally visible in the graph but do not create actor-level messages unless `send_message` is explicitly used.
- [ ] Full content fetch, if implemented in Phase 2, is explicit, bounded, and records `content_hash`.
- [ ] Optional real search backend is configurable but not required for tests.
- [ ] EnhancedDecider can choose among old and new actions using signal weights.
- [ ] EnhancedDecider does not add Persona/MBTI as a behavior signal unless the user explicitly approves that specific use.
- [ ] Each enhanced decision emits a trace visible through monitor/dashboard data.
- [ ] Search/tool failures become monitor events and do not crash the runtime loop.
- [ ] New artifact and web evidence nodes persist in operator storage, not human source storage.
- [ ] Human Source files remain unchanged after all Phase 2 tool actions.
- [ ] Offline smoke tests cover the complete Phase 2 path.

## Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Web search turns the graph into noisy scraped data | Import limited results, keep source metadata, add dedupe, record query provenance |
| Autonomy becomes opaque | Decision traces are required product output |
| LLM calls make every tick slow and expensive | Keep action selection statistical; LLM only drafts language when needed |
| Tool actions fork User and Operator behavior | Tools must write shared `ActorPanelState` and shared artifact/message structures |
| External search tests become flaky | Fake backend is mandatory; real backend optional |
| Operators spam messages or notes | Cooldowns, repeat penalties, token budget, max results, and monitor visibility |

## Resolved Design Decisions

以下设计问题已通过 grill-with-docs 会话决议（2026-05-22），记录于 `docs/CONTEXT.md`：

| 问题 | 决议 |
|---|---|
| 两层自治边界 | Layer 1 用 softmax + temperature（可配，→0 确定性，→∞ 等价 RandomDecider） |
| Operator 如何获得 panel primitives | 提取共享 `ActorPanel` 组件，UserActor 和 AsyncOperator 各持一个实例 |
| Actor Message 协议 | 两层：envelope（结构化 metadata）+ body（自由中文短文章） |
| System vs Actor Message 共存 | System 走 bus 全量 drain，Actor 走 ActorPanel.active_messages 受 PATIENCE 约束 |
| 消息阅读管线 | 纳入 current_context → 本轮已读全注入 LLM prompt → metadata 转 Decider 信号 |
| Decider Action 空间 | `{wander, ask, answer, score, idle, sleep, stash_current, send_message, reply_to_message, search_web, read_stash}`；`create_note` Phase 3 |
| Stash 持久化 | 存 `data/operator/stash-{op_id}.json` |
| Web 搜索去重粒度 | URL 级去重（查 `metadata.web_url`） |
| 搜索冷却 | 硬门（Hard Gate），signal 注入阶段权重归零，cooldown 状态在 ActorPanel |
| Token 预算 | 复用 `RequestPool`（15s/250K tokens），`BudgetSignal` 做全域衰减 |
| 并发搜索竞态 | `MGraph.asyncio.Lock` 包裹去重+导入原子操作 |
| 决策 trace 格式 | 两层：`raw_scores` + `probabilities`（softmax 后） |
| User Actor Phase 2 能力 | 不获得 search_web；User 通过 send_message 请求 Operator 代劳 |
| Stash-as-Memory 边界 | Phase 2：规则选取注入 prompt；Phase 3：检索策略（关键词/TF-IDF/向量/rerank） |
| Slice 执行顺序 | Slice-003 → 005 → 008 → 001 → 002 → 006 → 007 → 004(Phase 3)
