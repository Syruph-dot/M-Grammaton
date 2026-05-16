# Answer Material Summary Design

Date: 2026-05-17

## Goal

Improve answer generation so every answer prompt includes at least one cited material in full, while each material independently has a 15% chance to be replaced by an LLM-generated summary. Summaries are prepared by a background LLM job and persisted with material nodes.

The feature must preserve token telemetry. Summary-generation LLM calls are background work, but their token usage still counts in the runtime token stream and dashboard throughput chart.

## Current Project Shape

Answer generation currently reads a path with `operator_core.read_context(...)`, formats all visited node content into one text block, and passes that block into `build_answer_prompt(...)`.

Recent uncommitted changes also make `_llm_ask()` in `operators.py` and `runtime/async_operator.py` embed `## 参考材料` directly into the generated quest string. That is related but should not become the long-term answer-material model. Quest text should stay question-oriented; answer prompts should receive structured material context at answer time.

The current token-flow improvement adds these fields to `RuntimeMonitor.token_snapshot()`:

- `tokens_per_sec`
- `tps_series`

The dashboard uses those fields for a token-per-second throughput graph. New summary calls must go through the same monitored LLM client path, or this graph will undercount background work.

## Data Model

### Node Summary Metadata

Each material node stores its summary in `Node.metadata`:

```python
metadata["llm_summary"] = {
    "text": "...",
    "model": "deepseek-v4-flash",
    "content_hash": "...",
    "updated_at": 1710000000.0,
}
```

Rules:

- `content_hash` is computed from the current `node.content`.
- A summary is stale if `metadata["llm_summary"]["content_hash"] != content_hash(node.content)`.
- The summary text is requested as no more than 50 Chinese characters in the prompt.
- Code must also enforce a hard 120-character cap after the model returns. This prevents verbose outputs from bloating future answer prompts.
- Summary metadata persists naturally through existing YAML frontmatter because `Node.to_dict()` already includes `metadata`.

### AnswerTrace Material Record

`AnswerTrace` gains a `materials` list:

```python
[
    {
        "node": "dopp62",
        "mode": "full",
        "content_hash": "...",
        "summary_hash": None,
    },
    {
        "node": "dopp63",
        "mode": "summary",
        "content_hash": "...",
        "summary_hash": "...",
    },
]
```

This records what the answer actually saw. It should be serialized in `AnswerTrace.to_dict()` and restored by `AnswerTrace.from_dict(...)`.

## Material Context Module

Add a focused module, `material_context.py`, responsible for summary metadata and prompt material selection.

Responsibilities:

- Compute stable content hashes.
- Determine whether a node summary is missing or stale.
- Build a summary prompt.
- Clamp summary text to 120 characters.
- Convert visited nodes into material references.
- Apply the 15% summary substitution rule.
- Guarantee at least one material is included in full.
- Format chosen materials into answer prompt context.

Proposed public functions:

```python
SUMMARY_METADATA_KEY = "llm_summary"
SUMMARY_TARGET_CHARS = 50
SUMMARY_HARD_LIMIT_CHARS = 120
SUMMARY_SUBSTITUTION_PROBABILITY = 0.15

def content_hash(text: str) -> str: ...
def get_summary_record(node) -> dict | None: ...
def summary_is_stale(node, model: str | None = None) -> bool: ...
def build_summary_prompt(node) -> list[dict]: ...
def normalize_summary_text(text: str) -> str: ...
def store_summary(node, text: str, model: str, now: float | None = None) -> dict: ...
def material_refs_from_nodes(nodes: list) -> list[dict]: ...
def choose_answer_materials(materials: list[dict], rng=None, summary_probability: float = 0.15) -> list[dict]: ...
def format_material_context(chosen: list[dict]) -> str: ...
```

## Background Summary Job

The background job scans material/document nodes and generates summaries for missing or stale records.

Runtime integration:

- `OperatorRuntime` gets a background task such as `_summary_maintainer()`.
- It runs periodically and processes a small bounded batch per cycle.
- It skips `QuestNode` and `AnswerNode`.
- It uses the same async LLM client instance already attached to runtime.
- Because `AsyncLLMClient` reports usage to `RuntimeMonitor`, summary tokens appear in `tokens_per_sec`, `tps_series`, `last_minute`, and total token counters.

If there is no API key or no `llm_client`, the job does nothing. It should not block operator loops.

The summary prompt should be strict:

```text
请把以下材料压缩为不超过50字的中文摘要。保留核心事实、人物、地点、冲突或结论。只输出摘要正文，不要解释，不要项目符号。
```

Code still clamps the returned summary to 120 characters.

## Answer Prompt Selection

Answer generation changes from:

1. `read_context(...)` returns a preformatted text block.
2. Answer prompt uses that exact block.

To:

1. `read_context(...)` also exposes the visited nodes, or a sibling helper returns `node_names`, `path_edges`, and `visited_nodes`.
2. Convert visited nodes with content into material refs.
3. For each material with a non-stale summary, independently draw a random number.
4. If draw < 0.15, use summary; otherwise use full text.
5. If every chosen material is summary, force one material back to full text.
6. Format the context and pass it to `build_answer_prompt(...)`.
7. Store the material usage list into `AnswerTrace.materials`.

Fallback:

- If a material has no valid summary, it is always full.
- If only one material exists, it is always full because the invariant requires at least one full original material.

## Question Generation Boundary

This feature targets answer prompts. The current uncommitted changes that inject full reference material into generated quest text should not be expanded. During implementation, prefer reverting that behavior or replacing it with a narrower question metadata approach if tests require it. The answer prompt path is the authoritative place for full-vs-summary material selection.

## Testing

Focused tests should cover:

- summary prompt contains the 50-character instruction
- returned summary is hard-clamped to 120 characters
- stale detection changes when node content changes
- `Node.metadata["llm_summary"]` survives `save_graph` / `load_graph`
- `choose_answer_materials(...)` uses summary when RNG falls under 0.15
- at least one material remains full even if every RNG draw selects summary
- `AnswerTrace.materials` serializes and restores
- runtime monitor still returns `tokens_per_sec` and `tps_series`
- summary job calls the monitored async LLM client so token totals increase

## Verification

Run:

```powershell
python -m pytest test_material_context.py test_trace.py test_persistence.py test_runtime_monitor_dashboard.py test_dashboard_snapshot.py -q
python -m pytest -q
```

Use a temporary data directory for runtime smoke tests to avoid committing generated quest files or mutated material files.

## Non-Goals

- No database migration.
- No dashboard UI expansion beyond preserving and verifying existing token throughput fields.
- No global replacement of question-generation behavior beyond keeping it from conflicting with answer-material selection.
