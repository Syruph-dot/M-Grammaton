# M-Grammaton Runtime Dashboard Design

Date: 2026-05-17

## Goal

Build a first-screen runtime dashboard for M-Grammaton that makes the async operator system observable while it is running. The dashboard should show token throughput, operator activity, quest state, and a smooth real-time D3 force-directed graph of the live knowledge graph.

The dashboard will replace the current root monitor page served by `runtime/server.py`. It will stay inside the existing FastAPI app and avoid a new frontend build system.

## Current Project Shape

The runtime path is:

- `runtime.runtime.OperatorRuntime` owns the shared `MGraph`, `QuestBoard`, `TagManager`, `MessageBus`, and `AsyncOperator` instances.
- `runtime.async_operator.AsyncOperator` performs `wander`, `ask`, `answer`, `score`, `idle`, and `sleep`.
- `runtime.monitor.RuntimeMonitor` records per-operator state and already supports snapshot polling plus SSE subscriptions.
- `runtime.server` serves FastAPI routes, an SSE stream, and an older tag-management D3 page.

The existing monitor only reports operator-level state. It does not expose the live graph, quest counts, runtime round, or token usage. The existing D3 graph is tag-oriented and rebuilds its SVG and simulation on each render, which is not suitable for a smooth live graph.

## D3 Force Reference

D3 force simulations use velocity Verlet integration, not implicit Euler. On each tick, forces adjust velocity, velocity decay is applied, and positions are updated from velocity. The dashboard should tune `alpha`, `alphaTarget`, `velocityDecay`, collision radius, link distance, and positioning forces according to that model.

The graph implementation will follow official D3 patterns:

- `d3.forceSimulation(nodes)`
- `d3.forceLink(links).id(d => d.id)`
- `d3.forceManyBody()`
- `d3.forceCollide()`
- `d3.forceX()` and `d3.forceY()` as soft layout anchors
- drag handlers that set `fx/fy`, call `simulation.alphaTarget(0.25).restart()`, then release pins on drag end

For disconnected subgraphs, the design follows the Observable disjoint-force graph pattern: use position forces to give components or node classes stable areas, rather than relying only on `forceCenter`.

Sources:

- `https://d3js.org/d3-force`
- `https://d3js.org/d3-force/simulation`
- `https://d3js.org/d3-force/link`
- `https://d3js.org/d3-force/position`
- `https://observablehq.com/@d3/disjoint-force-directed-graph/2`

## Dashboard Layout

The page is a dense operations dashboard, not a landing page.

Top band:

- Runtime status
- Current round
- Operator count
- Node count
- Edge count
- Active quests
- Completed quests
- Total tokens
- Tokens per minute

Main band:

- Left: full-height D3 force graph.
- Right: operator panel with one row per operator, including MBTI, current node, active quest count, last action, and last detail.

Bottom band:

- Token throughput sparkline.
- Recent runtime events.
- Quest summary table.

Visual style:

- Quiet work-focused interface.
- Neutral dark background with restrained accent colors.
- No nested cards.
- No hero section.
- Stable dimensions for graph, KPI cells, operator rows, and charts.

## Data Model

Add a dashboard snapshot structure returned by a new endpoint:

```json
{
  "runtime": {
    "running": true,
    "round": 12,
    "started_at": 1778940000.0,
    "uptime_seconds": 93.2
  },
  "stats": {
    "operators": 3,
    "nodes": 18,
    "edges": 42,
    "active_quests": 4,
    "completed_quests": 8,
    "stk_entries": 15
  },
  "tokens": {
    "total": 23120,
    "last_minute": 4700,
    "requests": 14,
    "estimated": 5,
    "reported": 9,
    "series": [
      {"t": 1778940001.0, "tokens": 520}
    ]
  },
  "operators": [
    {
      "id": "Alice",
      "node": "node-a",
      "mbti": "INTJ",
      "quests": 2,
      "action": "answer",
      "detail": "quest-4",
      "timestamp": 1778940003.0
    }
  ],
  "graph": {
    "version": 19,
    "nodes": [
      {"id": "node-a", "kind": "document", "label": "node-a", "tags": ["x"], "activeOperators": ["Alice"]}
    ],
    "links": [
      {"id": "node-a->quest-4", "source": "node-a", "target": "quest-4", "weight": 0.73}
    ]
  },
  "quests": {
    "active": [],
    "completed": []
  }
}
```

## Backend Changes

`RuntimeMonitor` will be extended with:

- Token totals.
- Recent token events in a bounded deque.
- Request counts split between reported usage and local estimates.
- A generic dashboard event stream for operator updates, token events, and graph dirty notifications.

`AsyncLLMClient` will be extended to measure token usage:

- Prefer provider `usage.total_tokens`.
- Fall back to `prompt_tokens + completion_tokens`.
- Fall back to the same local text estimate shape used by `LLMClient`.
- Report token events to `RuntimeMonitor` when available.

`OperatorRuntime` will expose enough state to the server:

- running flag
- round
- graph
- board
- operators
- tag manager
- monitor
- started timestamp

`runtime.server.run_server(...)` will accept a runtime reference, not only a monitor. Existing call sites can still pass the older arguments temporarily, but the runtime path should use the richer reference.

New routes:

- `GET /api/dashboard/snapshot`
- `GET /api/dashboard/stream`

The existing `/snapshot` and `/stream` routes can remain for compatibility.

## Graph Snapshot Rules

The dashboard graph represents the live `MGraph`, not only tags.

Node mapping:

- `Node.kind == "document"` maps to document nodes.
- `QuestNode` maps to quest nodes.
- `AnswerNode` maps to answer nodes.
- Current operator positions are represented as `activeOperators` on graph nodes, not as separate nodes by default.

Link mapping:

- Each `Edge` maps to one directed link.
- Link id is stable: `${source}->${target}`.
- Link width and opacity derive from `Edge.value`.

Graph version:

- Increment when node count, edge count, or operator current-node mapping changes.
- The client can use this to decide whether to merge new graph data or only update operator overlays.

## Frontend D3 Design

The graph code must create SVG, groups, zoom behavior, and simulation once.

Data updates must:

- Merge nodes by `id`.
- Preserve existing `x`, `y`, `vx`, and `vy` values when a node remains present.
- Merge links by stable `id`.
- Update DOM with `selection.data(...).join(...)`.
- Call `simulation.nodes(nodes)` and `simulation.force("link").links(links)`.
- Restart with a low alpha, such as `simulation.alpha(0.35).restart()`, only when topology changes.

Forces:

- `link`: distance based on node kind and link weight.
- `charge`: negative strength, weaker for large graphs.
- `collide`: radius based on node size plus label padding.
- `x/y`: soft anchors by node kind and connected component.
- `center`: weak centering, not the primary layout mechanism.

Rendering:

- `requestAnimationFrame` coalesces tick DOM writes.
- Labels are shortened and only prominent for active, quest, and hovered nodes.
- Tooltips show id, kind, tags, degree, active operators, and weight detail.
- Resize updates dimensions and force centers without rebuilding the simulation.

## Token Throughput

The dashboard shows:

- total token count
- tokens in the last 60 seconds
- requests in the last 60 seconds
- reported vs estimated request count
- a 60-second sparkline

Token events are generated by `AsyncLLMClient.chat()` and `AsyncLLMClient.chat_json()` after each request attempt completes. Failed requests report estimated prompt tokens only if no provider usage is available.

## Error Handling

If the monitor or runtime is not ready, dashboard endpoints return a valid empty snapshot with `"ready": false` rather than breaking the page.

If SSE disconnects, the frontend backs off and keeps polling `/api/dashboard/snapshot` every 2 seconds.

If D3 fails to load from CDN, the page shows a visible error in the graph region. The first implementation can use CDN D3 because the existing tag UI already does.

## Verification

Backend verification:

- Unit tests for token usage extraction and fallback estimates.
- Unit tests or focused smoke checks for dashboard snapshot shape.
- Existing tests must still pass.

Runtime verification:

- Start `python -m runtime --web --timeout 20`.
- Open the dashboard endpoint.
- Confirm `/api/dashboard/snapshot` returns operators, graph nodes, graph links, and token counters.
- Confirm SSE produces operator updates.

Frontend verification:

- Use a browser screenshot or Playwright check if available.
- Confirm SVG has nonzero nodes and links for the sample data.
- Confirm topology updates do not recreate the simulation on every event.
- Confirm graph remains visible after resize.

## Implementation Boundary

This feature does not replace the Gradio app. It improves the FastAPI runtime dashboard path used by `python -m runtime --web`.

This feature does not add a React/Vite build, a database, authentication, or persistent metrics storage. Token history is in-memory runtime telemetry.
