"""FastAPI + SSE 监控面板 —— 与 Runtime 共享事件循环。"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from questnode import AnswerNode, QuestNode
from runtime.monitor import RuntimeMonitor
from tag_manager import TagManager

# ── FastAPI App ────────────────────────────────────

app = FastAPI(title="M-Grammaton Runtime Monitor")
monitor: RuntimeMonitor | None = None
tag_manager: TagManager | None = None
runtime_ref = None


# ── Pydantic models ────────────────────────────────

class TagCreate(BaseModel):
    name: str
    aliases: list[str] = []

class TagAliasAdd(BaseModel):
    alias: str

class TagLink(BaseModel):
    node: str

class TagConc(BaseModel):
    target: str
    weight: int = 1

class TagRename(BaseModel):
    name: str


# ── Snapshot & Stream (existing) ───────────────────

@app.get("/")
async def index():
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/snapshot")
async def get_snapshot():
    if monitor is None:
        return {"error": "monitor not ready", "operators": [], "count": 0}
    ops = [
        {
            "id": s.operator_id,
            "node": s.current_node,
            "mbti": s.mbti,
            "quests": s.active_quests,
            "action": s.last_action,
            "detail": s.last_detail,
        }
        for s in sorted(monitor.snapshot().values(), key=lambda s: s.operator_id)
    ]
    return {"operators": ops, "count": len(ops)}


@app.get("/api/dashboard/snapshot")
async def dashboard_snapshot():
    return _build_dashboard_snapshot(runtime_ref, monitor)


@app.get("/stream")
async def stream_events(request: Request):
    if monitor is None:
        return {"error": "monitor not ready"}

    queue = monitor.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    snap = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield {
                        "event": "operator_update",
                        "data": json.dumps({
                            "id": snap.operator_id,
                            "node": snap.current_node,
                            "mbti": snap.mbti,
                            "quests": snap.active_quests,
                            "action": snap.last_action,
                            "detail": snap.last_detail,
                        }),
                    }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if monitor:
                monitor.unsubscribe(queue)

    return EventSourceResponse(event_generator())


@app.get("/api/dashboard/stream")
async def dashboard_stream(request: Request):
    if monitor is None:
        return {"error": "monitor not ready"}

    queue = monitor.subscribe_events()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield {
                        "event": "dashboard",
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if monitor:
                monitor.unsubscribe_events(queue)

    return EventSourceResponse(event_generator())


def _build_dashboard_snapshot(runtime_obj=None, monitor_obj=None, now: float | None = None) -> dict:
    now = time.time() if now is None else float(now)
    empty = {
        "ready": False,
        "runtime": {
            "running": False,
            "round": 0,
            "started_at": None,
            "uptime_seconds": 0.0,
        },
        "stats": {
            "operators": 0,
            "nodes": 0,
            "edges": 0,
            "active_quests": 0,
            "completed_quests": 0,
            "stk_entries": 0,
        },
        "tokens": _token_snapshot(monitor_obj, now),
        "operators": _operator_snapshots(monitor_obj),
        "graph": {"version": 0, "nodes": [], "links": []},
        "quests": {"active": [], "completed": []},
    }
    if runtime_obj is None:
        return empty

    graph = getattr(runtime_obj, "graph", None)
    board = getattr(runtime_obj, "board", None)
    operators = getattr(runtime_obj, "operators", {}) or {}
    nodes = list(getattr(graph, "V", []) or [])
    edges = list(getattr(graph, "E", []) or [])
    active_quests = list(getattr(board, "active", []) or [])
    completed_quests = list(getattr(board, "completed", []) or [])
    started_at = getattr(runtime_obj, "started_at", None)
    uptime = max(0.0, now - float(started_at)) if started_at is not None else 0.0
    operator_rows = _operator_snapshots(monitor_obj)
    active_by_node = _active_operators_by_node(operator_rows)

    return {
        "ready": True,
        "runtime": {
            "running": bool(getattr(runtime_obj, "running", False)),
            "round": int(getattr(runtime_obj, "round", 0) or 0),
            "started_at": started_at,
            "uptime_seconds": uptime,
        },
        "stats": {
            "operators": len(operators) if operators else len(operator_rows),
            "nodes": len(nodes),
            "edges": len(edges),
            "active_quests": len(active_quests),
            "completed_quests": len(completed_quests),
            "stk_entries": sum(len(getattr(node, "stk", []) or []) for node in nodes),
        },
        "tokens": _token_snapshot(monitor_obj, now),
        "operators": operator_rows,
        "graph": {
            "version": _graph_version(nodes, edges, active_by_node),
            "nodes": [_dashboard_node(node, active_by_node) for node in sorted(nodes, key=lambda item: item.name)],
            "links": [_dashboard_link(edge) for edge in sorted(edges, key=lambda item: (item.source.name, item.target.name))],
        },
        "quests": {
            "active": [_quest_summary(item) for item in active_quests],
            "completed": [_quest_summary(item) for item in completed_quests],
        },
    }


def _operator_snapshots(monitor_obj) -> list[dict]:
    if monitor_obj is None:
        return []
    return [
        {
            "id": snap.operator_id,
            "node": snap.current_node,
            "mbti": snap.mbti,
            "quests": snap.active_quests,
            "action": snap.last_action,
            "detail": snap.last_detail,
            "timestamp": snap.timestamp,
        }
        for snap in sorted(monitor_obj.snapshot().values(), key=lambda item: item.operator_id)
    ]


def _token_snapshot(monitor_obj, now: float) -> dict:
    if monitor_obj is None or not hasattr(monitor_obj, "token_snapshot"):
        return {
            "total": 0,
            "last_minute": 0,
            "requests": 0,
            "reported": 0,
            "estimated": 0,
            "series": [],
        }
    return monitor_obj.token_snapshot(now=now)


def _active_operators_by_node(operator_rows: list[dict]) -> dict[str, list[str]]:
    active: dict[str, list[str]] = {}
    for row in operator_rows:
        node = row.get("node")
        if node:
            active.setdefault(node, []).append(row["id"])
    return active


def _dashboard_node(node, active_by_node: dict[str, list[str]]) -> dict:
    return {
        "id": node.name,
        "label": getattr(node, "title", node.name) or node.name,
        "kind": _node_kind(node),
        "tags": sorted(getattr(node, "tags", []) or []),
        "degree": len(getattr(node, "inlinks", []) or []) + len(getattr(node, "outlinks", []) or []),
        "activeOperators": sorted(active_by_node.get(node.name, [])),
    }


def _dashboard_link(edge) -> dict:
    return {
        "id": f"{edge.source.name}->{edge.target.name}",
        "source": edge.source.name,
        "target": edge.target.name,
        "weight": edge.value,
    }


def _node_kind(node) -> str:
    if isinstance(node, QuestNode):
        return "quest"
    if isinstance(node, AnswerNode):
        return "answer"
    return getattr(node, "kind", "document")


def _quest_summary(quest) -> dict:
    answers = quest.get_answers() if hasattr(quest, "get_answers") else []
    return {
        "id": quest.name,
        "quester": getattr(quest, "quester_id", ""),
        "content": getattr(quest, "content", ""),
        "answers": len(answers),
        "depth": getattr(quest, "depth", 0),
    }


def _graph_version(nodes, edges, active_by_node: dict[str, list[str]]) -> int:
    active = tuple(
        (node, tuple(operators))
        for node, operators in sorted(active_by_node.items())
    )
    return hash((len(nodes), len(edges), active))


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M-Grammaton Runtime Dashboard</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  *,*::before,*::after{box-sizing:border-box}
  html,body{margin:0;min-height:100%;background:#101418;color:#e5e7eb;font-family:Inter,"Segoe UI","Microsoft YaHei",Arial,sans-serif}
  body{padding:18px}
  .shell{max-width:1800px;margin:0 auto}
  .topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:14px}
  h1{font-size:20px;line-height:1.2;margin:0;font-weight:700;letter-spacing:0}
  .subtitle{font-size:12px;color:#8b949e;margin-top:4px}
  .nav{display:flex;gap:10px;font-size:12px;white-space:nowrap}
  .nav a{color:#66c2ff;text-decoration:none}.nav a:hover{text-decoration:underline}
  .kpis{display:grid;grid-template-columns:repeat(8,minmax(120px,1fr));gap:8px;margin-bottom:12px}
  .kpi{background:#171d23;border:1px solid #2d3742;border-radius:8px;padding:10px 12px;min-height:68px}
  .kpi-label{font-size:11px;color:#91a1b2;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
  .kpi-value{font-size:22px;font-weight:700;margin-top:6px;color:#f8fafc;font-variant-numeric:tabular-nums}
  .dashboard-grid{display:grid;grid-template-columns:minmax(520px,1fr) 390px;gap:12px;min-height:610px}
  .graph-panel{position:relative;background:#121820;border:1px solid #2d3742;border-radius:8px;overflow:hidden;min-height:610px}
  #graph{display:block;width:100%;height:100%;min-height:610px}
  #graph-empty{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:#7c8794;font-size:14px;pointer-events:none}
  .side-panel{display:grid;grid-template-rows:1fr 220px;gap:12px;min-height:610px}
  .panel{background:#171d23;border:1px solid #2d3742;border-radius:8px;overflow:hidden}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #2d3742}
  .panel-title{font-size:13px;font-weight:700;color:#d7dee7}
  .panel-meta{font-size:11px;color:#7c8794}
  #operators{height:100%;overflow:auto}
  .op-row{display:grid;grid-template-columns:70px 58px 1fr 72px;gap:8px;align-items:center;padding:10px 12px;border-bottom:1px solid #242d36;font-size:12px}
  .op-row:last-child{border-bottom:0}
  .op-id{font-weight:700;color:#f8fafc;overflow:hidden;text-overflow:ellipsis}
  .badge{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;background:#25313d;color:#a7d7ff;min-width:44px;padding:2px 8px;font-size:11px}
  .op-node{color:#b8c2cc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .op-action{font-variant-numeric:tabular-nums;text-align:right;color:#79d8b0}
  #token-chart{height:170px;padding:8px 10px 12px}
  #token-chart svg{width:100%;height:100%}
  .bottom-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;min-height:220px}
  #events,#quests{max-height:260px;overflow:auto}
  .event-row,.quest-row{display:grid;grid-template-columns:92px 1fr;gap:10px;padding:8px 12px;border-bottom:1px solid #242d36;font-size:12px}
  .event-type,.quest-id{color:#66c2ff;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .event-detail,.quest-detail{color:#b8c2cc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .link{stroke:#3a4652;stroke-opacity:.55}
  .node{stroke:#111820;stroke-width:1.5px;cursor:pointer}
  .node.document{fill:#5da9e9}.node.quest{fill:#f2c94c}.node.answer{fill:#79d8b0}.node.active{stroke:#ff7a59;stroke-width:3px}
  .label{fill:#cbd5df;font-size:11px;paint-order:stroke;stroke:#121820;stroke-width:3px;stroke-linejoin:round;pointer-events:none}
  .tooltip{position:absolute;z-index:10;background:#0b1015;border:1px solid #344250;border-radius:6px;padding:8px 10px;color:#e5e7eb;font-size:12px;pointer-events:none;opacity:0;max-width:280px;box-shadow:0 12px 24px rgba(0,0,0,.32)}
  .error{color:#ff9b8f;padding:18px}
  @media (max-width:1100px){
    body{padding:10px}.kpis{grid-template-columns:repeat(2,minmax(130px,1fr))}
    .dashboard-grid,.bottom-grid{grid-template-columns:1fr}.side-panel{grid-template-rows:auto auto}
    .graph-panel,#graph{min-height:520px}.topbar{align-items:flex-start;flex-direction:column}
  }
</style>
</head>
<body>
<div class="shell">
  <div class="topbar">
    <div>
      <h1>M-Grammaton Runtime Dashboard</h1>
      <div class="subtitle" id="status">connecting...</div>
    </div>
    <nav class="nav"><a href="/tags/ui">Tag UI</a><a href="/snapshot">Legacy Snapshot</a></nav>
  </div>

  <section class="kpis" id="kpis"></section>

  <main class="dashboard-grid">
    <section class="graph-panel">
      <svg id="graph"></svg>
      <div id="graph-empty">No graph data</div>
      <div class="tooltip" id="tooltip"></div>
    </section>
    <aside class="side-panel">
      <section class="panel">
        <div class="panel-header"><div class="panel-title">Operators</div><div class="panel-meta" id="operator-count">0</div></div>
        <div id="operators"></div>
      </section>
      <section class="panel">
        <div class="panel-header"><div class="panel-title">Token Throughput</div><div class="panel-meta" id="token-meta">0/min</div></div>
        <div id="token-chart"></div>
      </section>
    </aside>
  </main>

  <section class="bottom-grid">
    <section class="panel">
      <div class="panel-header"><div class="panel-title">Recent Events</div><div class="panel-meta" id="event-count">0</div></div>
      <div id="events"></div>
    </section>
    <section class="panel">
      <div class="panel-header"><div class="panel-title">Quests</div><div class="panel-meta" id="quest-count">0</div></div>
      <div id="quests"></div>
    </section>
  </section>
</div>

<script>
const state = {
  snapshot: null,
  events: [],
  nodes: [],
  links: [],
  nodeById: new Map(),
  linkById: new Map(),
  graphVersion: null,
  source: null
};

const svg = d3.select('#graph');
const graphPanel = document.querySelector('.graph-panel');
const tooltip = d3.select('#tooltip');
const root = svg.append('g');
const linkLayer = root.append('g');
const nodeLayer = root.append('g');
const labelLayer = root.append('g');

const simulation = d3.forceSimulation(state.nodes)
  .force('link', d3.forceLink(state.links).id(d => d.id).distance(d => 90 + 80 * (1 - Math.min(1, d.weight || 0))))
  .force('charge', d3.forceManyBody().strength(d => d.kind === 'document' ? -190 : -150))
  .force('collide', d3.forceCollide().radius(d => 18 + Math.min(14, (d.degree || 0) * 2)).iterations(2))
  .force('x', d3.forceX(d => kindAnchor(d).x).strength(0.055))
  .force('y', d3.forceY(d => kindAnchor(d).y).strength(0.065))
  .force('center', d3.forceCenter(400, 300))
  .velocityDecay(0.32);

let linkSel = linkLayer.selectAll('line');
let nodeSel = nodeLayer.selectAll('circle');
let labelSel = labelLayer.selectAll('text');
let framePending = false;

svg.call(d3.zoom().scaleExtent([0.18, 5]).on('zoom', event => {
  root.attr('transform', event.transform);
}));

simulation.on('tick', () => {
  if (framePending) return;
  framePending = true;
  requestAnimationFrame(() => {
    framePending = false;
    linkSel
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);
    nodeSel.attr('cx', d => d.x).attr('cy', d => d.y);
    labelSel.attr('x', d => d.x + 12).attr('y', d => d.y + 4);
  });
});

function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
}

function fmt(value) {
  return new Intl.NumberFormat('en-US').format(Math.round(Number(value) || 0));
}

function panelSize() {
  const box = graphPanel.getBoundingClientRect();
  return {width: Math.max(320, box.width), height: Math.max(320, box.height)};
}

function kindAnchor(d) {
  const {width, height} = panelSize();
  if (d.kind === 'quest') return {x: width * 0.72, y: height * 0.32};
  if (d.kind === 'answer') return {x: width * 0.72, y: height * 0.70};
  return {x: width * 0.34, y: height * 0.52};
}

function resizeGraph() {
  const {width, height} = panelSize();
  svg.attr('viewBox', [0, 0, width, height]).attr('width', width).attr('height', height);
  simulation.force('center', d3.forceCenter(width / 2, height / 2));
  simulation.alpha(0.18).restart();
}

function mergeGraph(graph) {
  const oldNodes = state.nodeById;
  const newNodes = graph.nodes.map(item => {
    const old = oldNodes.get(item.id);
    return Object.assign(old || {}, item);
  });
  const newNodeById = new Map(newNodes.map(node => [node.id, node]));
  const newLinks = graph.links
    .filter(link => newNodeById.has(link.source) && newNodeById.has(link.target))
    .map(link => Object.assign(state.linkById.get(link.id) || {}, link));

  state.nodes = newNodes;
  state.links = newLinks;
  state.nodeById = newNodeById;
  state.linkById = new Map(newLinks.map(link => [link.id, link]));

  document.getElementById('graph-empty').style.display = state.nodes.length ? 'none' : 'flex';

  linkSel = linkLayer.selectAll('line')
    .data(state.links, d => d.id)
    .join(
      enter => enter.append('line').attr('class', 'link'),
      update => update,
      exit => exit.remove()
    )
    .attr('stroke-width', d => Math.max(1, Math.min(7, 1 + (d.weight || 0) * 5)));

  nodeSel = nodeLayer.selectAll('circle')
    .data(state.nodes, d => d.id)
    .join(
      enter => enter.append('circle')
        .attr('class', d => 'node ' + d.kind)
        .attr('r', d => 8 + Math.min(10, d.degree || 0))
        .on('mouseenter', showTooltip)
        .on('mousemove', moveTooltip)
        .on('mouseleave', hideTooltip)
        .call(d3.drag()
          .on('start', dragStart)
          .on('drag', dragged)
          .on('end', dragEnd)),
      update => update,
      exit => exit.remove()
    )
    .attr('class', d => 'node ' + d.kind + ((d.activeOperators && d.activeOperators.length) ? ' active' : ''))
    .attr('r', d => 8 + Math.min(12, d.degree || 0) + ((d.activeOperators && d.activeOperators.length) ? 3 : 0));

  labelSel = labelLayer.selectAll('text')
    .data(state.nodes.filter(d => d.kind !== 'document' || (d.activeOperators && d.activeOperators.length)), d => d.id)
    .join(
      enter => enter.append('text').attr('class', 'label'),
      update => update,
      exit => exit.remove()
    )
    .text(d => shortLabel(d.label || d.id));

  simulation.nodes(state.nodes);
  simulation.force('link').links(state.links);
  simulation.alpha(state.graphVersion === graph.version ? 0.12 : 0.35).restart();
  state.graphVersion = graph.version;
}

function shortLabel(text) {
  text = String(text || '');
  return text.length > 18 ? text.slice(0, 17) + '...' : text;
}

function showTooltip(event, d) {
  tooltip.style('opacity', 1).html(
    `<strong>${esc(d.id)}</strong><br>` +
    `kind: ${esc(d.kind)}<br>` +
    `degree: ${fmt(d.degree)}<br>` +
    `operators: ${esc((d.activeOperators || []).join(', ') || '-')}` +
    (d.tags && d.tags.length ? `<br>tags: ${esc(d.tags.join(', '))}` : '')
  );
  moveTooltip(event);
}

function moveTooltip(event) {
  const box = graphPanel.getBoundingClientRect();
  tooltip
    .style('left', (event.clientX - box.left + 14) + 'px')
    .style('top', (event.clientY - box.top + 14) + 'px');
}

function hideTooltip() {
  tooltip.style('opacity', 0);
}

function dragStart(event, d) {
  if (!event.active) simulation.alphaTarget(0.25).restart();
  d.fx = d.x;
  d.fy = d.y;
}

function dragged(event, d) {
  d.fx = event.x;
  d.fy = event.y;
}

function dragEnd(event, d) {
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null;
  d.fy = null;
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  document.getElementById('status').textContent = snapshot.ready
    ? `running=${snapshot.runtime.running} round=${snapshot.runtime.round} uptime=${fmt(snapshot.runtime.uptime_seconds)}s`
    : 'runtime not ready';
  renderKpis(snapshot);
  renderOperators(snapshot.operators || []);
  renderTokenChart(snapshot.tokens || {series: []});
  renderQuests(snapshot.quests || {active: [], completed: []});
  mergeGraph(snapshot.graph || {version: 0, nodes: [], links: []});
}

function renderKpis(snapshot) {
  const stats = snapshot.stats || {};
  const tokens = snapshot.tokens || {};
  const runtime = snapshot.runtime || {};
  const cells = [
    ['Round', runtime.round],
    ['Nodes', stats.nodes],
    ['Edges', stats.edges],
    ['Active Quests', stats.active_quests],
    ['Completed', stats.completed_quests],
    ['STK Entries', stats.stk_entries],
    ['Total Tokens', tokens.total],
    ['Tokens / Min', tokens.last_minute],
  ];
  document.getElementById('kpis').innerHTML = cells.map(([label, value]) =>
    `<div class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${fmt(value)}</div></div>`
  ).join('');
}

function renderOperators(operators) {
  document.getElementById('operator-count').textContent = fmt(operators.length);
  document.getElementById('operators').innerHTML = operators.length ? operators.map(op => `
    <div class="op-row">
      <div class="op-id">${esc(op.id)}</div>
      <div class="badge">${esc(op.mbti || '-')}</div>
      <div class="op-node" title="${esc(op.node || '')}">${esc(op.node || '(none)')}</div>
      <div class="op-action">${esc(op.action || '-')}</div>
    </div>
  `).join('') : '<div class="event-row"><div class="event-type">empty</div><div class="event-detail">No operators reported yet</div></div>';
}

function renderTokenChart(tokens) {
  document.getElementById('token-meta').textContent = `${fmt(tokens.last_minute || 0)}/min`;
  const el = document.getElementById('token-chart');
  const width = Math.max(280, el.clientWidth - 20);
  const height = Math.max(130, el.clientHeight - 20);
  const series = (tokens.series || []).slice(-120);
  el.innerHTML = '';
  const chart = d3.select(el).append('svg').attr('viewBox', [0, 0, width, height]);
  chart.append('rect').attr('width', width).attr('height', height).attr('rx', 6).attr('fill', '#101820');
  if (!series.length) {
    chart.append('text').attr('x', width / 2).attr('y', height / 2).attr('text-anchor', 'middle').attr('fill', '#7c8794').attr('font-size', 12).text('No token events');
    return;
  }
  const x = d3.scaleLinear().domain(d3.extent(series, d => d.t)).range([12, width - 12]);
  const y = d3.scaleLinear().domain([0, d3.max(series, d => d.tokens) || 1]).nice().range([height - 18, 12]);
  const line = d3.line().x(d => x(d.t)).y(d => y(d.tokens)).curve(d3.curveMonotoneX);
  chart.append('path').datum(series).attr('fill', 'none').attr('stroke', '#79d8b0').attr('stroke-width', 2).attr('d', line);
  chart.selectAll('circle').data(series).join('circle').attr('cx', d => x(d.t)).attr('cy', d => y(d.tokens)).attr('r', 2.5).attr('fill', '#f2c94c');
}

function renderQuests(quests) {
  const active = quests.active || [];
  const completed = quests.completed || [];
  document.getElementById('quest-count').textContent = `${fmt(active.length)} active / ${fmt(completed.length)} done`;
  const rows = [
    ...active.map(q => Object.assign({state: 'active'}, q)),
    ...completed.slice(-8).map(q => Object.assign({state: 'done'}, q)),
  ];
  document.getElementById('quests').innerHTML = rows.length ? rows.map(q => `
    <div class="quest-row">
      <div class="quest-id">${esc(q.state)} ${esc(q.id)}</div>
      <div class="quest-detail">${esc((q.content || '').slice(0, 120))}</div>
    </div>
  `).join('') : '<div class="quest-row"><div class="quest-id">empty</div><div class="quest-detail">No quests yet</div></div>';
}

function pushEvent(event) {
  if (event.type === 'ping') return;
  state.events.unshift(Object.assign({at: Date.now()}, event));
  state.events = state.events.slice(0, 60);
  document.getElementById('event-count').textContent = fmt(state.events.length);
  document.getElementById('events').innerHTML = state.events.map(item => {
    const detail = item.operator ? `${item.operator.id} ${item.operator.action} ${item.operator.detail || ''}` :
      item.tokens ? `${item.tokens.operator_id || 'llm'} ${item.tokens.action}: ${item.tokens.tokens} tokens (${item.tokens.source})` :
      JSON.stringify(item);
    return `<div class="event-row"><div class="event-type">${esc(item.type)}</div><div class="event-detail">${esc(detail)}</div></div>`;
  }).join('');
}

async function fetchSnapshot() {
  try {
    const res = await fetch('/api/dashboard/snapshot');
    const data = await res.json();
    renderSnapshot(data);
  } catch (error) {
    document.getElementById('status').innerHTML = `<span class="error">${esc(error.message)}</span>`;
  }
}

function connectStream() {
  if (state.source) state.source.close();
  state.source = new EventSource('/api/dashboard/stream');
  state.source.addEventListener('dashboard', event => {
    try {
      pushEvent(JSON.parse(event.data));
      fetchSnapshot();
    } catch (error) {
      pushEvent({type: 'stream_error', message: error.message});
    }
  });
  state.source.onerror = () => {
    state.source.close();
    setTimeout(connectStream, 2000);
  };
}

window.addEventListener('resize', resizeGraph);
resizeGraph();
fetchSnapshot();
connectStream();
setInterval(fetchSnapshot, 2000);
</script>
</body>
</html>
"""


# ── Tag Management API ─────────────────────────────


@app.get("/tags")
async def list_tags():
    """返回所有标签的完整信息列表。"""
    if tag_manager is None:
        return {"tags": []}
    return {"tags": tag_manager.get_all_tags()}


@app.get("/tags/graph")
async def tag_graph():
    """返回概念关系图数据，供 D3 力导向图渲染。"""
    if tag_manager is None:
        return {"nodes": [], "edges": []}
    nodes = [{"id": t["name"], "nodeCount": t["nodes"]}
             for t in tag_manager.get_all_tags()]
    edges = tag_manager.get_all_conc_edges()
    return {"nodes": nodes, "edges": edges}


@app.post("/tags")
async def create_tag(body: TagCreate):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    try:
        ok = tag_manager.add_tag(body.name, aliases=body.aliases if body.aliases else None)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not ok:
        return JSONResponse({"error": f"tag '{body.name}' already exists"}, status_code=409)
    return {"ok": True, "name": body.name}


@app.delete("/tags/{name}")
async def delete_tag(name: str):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.remove_tag(name)
    if not ok:
        return JSONResponse({"error": f"tag '{name}' not found"}, status_code=404)
    return {"ok": True}


@app.put("/tags/{name}")
async def rename_tag(name: str, body: TagRename):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.rename_tag(name, body.name)
    if not ok:
        return JSONResponse({"error": f"cannot rename '{name}' to '{body.name}'"},
                            status_code=409)
    return {"ok": True, "name": body.name}


# ── Aliases ────────────────────────────────────────

@app.post("/tags/{name}/aliases")
async def add_alias(name: str, body: TagAliasAdd):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.add_alias(name, body.alias)
    if not ok:
        return JSONResponse({"error": f"cannot add alias '{body.alias}' to '{name}'"},
                            status_code=400)
    return {"ok": True}


@app.delete("/tags/{name}/aliases/{alias}")
async def remove_alias(name: str, alias: str):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.remove_alias(name, alias)
    if not ok:
        return JSONResponse({"error": f"alias '{alias}' not found on '{name}'"},
                            status_code=404)
    return {"ok": True}


# ── Node ↔ Tag linkage ─────────────────────────────

@app.post("/tags/{name}/link")
async def link_node(name: str, body: TagLink):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.link_node(name, body.node)
    if not ok:
        return JSONResponse({"error": f"cannot link node '{body.node}' to tag '{name}'"},
                            status_code=400)
    return {"ok": True}


@app.delete("/tags/{name}/link/{node}")
async def unlink_node(name: str, node: str):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.unlink_node(name, node)
    if not ok:
        return JSONResponse({"error": f"cannot unlink node '{node}' from tag '{name}'"},
                            status_code=400)
    return {"ok": True}


# ── Concept tags (tag ↔ tag) ───────────────────────

@app.post("/tags/{name}/conc")
async def add_conc_tag(name: str, body: TagConc):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.add_conc_tag(name, body.target, weight=body.weight)
    if not ok:
        return JSONResponse(
            {"error": f"cannot link concept '{name}' <-> '{body.target}'"},
            status_code=400,
        )
    return {"ok": True}


@app.delete("/tags/{name}/conc/{target}")
async def remove_conc_tag(name: str, target: str):
    if tag_manager is None:
        return JSONResponse({"error": "tag_manager not ready"}, status_code=503)
    ok = tag_manager.remove_conc_tag(name, target)
    if not ok:
        return JSONResponse(
            {"error": f"concept link '{name}' <-> '{target}' not found"},
            status_code=404,
        )
    return {"ok": True}


# ── Tags management page ───────────────────────────

TAGS_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M-Grammaton — 标签管理</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'SF Mono','Cascadia Code','Consolas',monospace;background:#0d1117;color:#c9d1d9;padding:24px}
  h1{font-size:18px;margin-bottom:4px;color:#58a6ff}
  .subtitle{font-size:12px;color:#8b949e;margin-bottom:20px}
  .layout{display:flex;gap:20px}
  .left{width:380px;flex-shrink:0}
  .right{flex:1;min-height:500px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
  .card h2{font-size:14px;color:#8b949e;margin-bottom:12px}
  .form-row{display:flex;gap:8px;margin-bottom:8px}
  .form-row input,.form-row select{flex:1;background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:6px 8px;color:#c9d1d9;font-size:13px;font-family:inherit}
  .form-row input:focus{border-color:#58a6ff;outline:none}
  .btn{padding:6px 12px;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-family:inherit;font-weight:600}
  .btn-primary{background:#238636;color:#fff}.btn-primary:hover{background:#2ea043}
  .btn-danger{background:#da3633;color:#fff}.btn-danger:hover{background:#f85149}
  .btn-sm{padding:3px 8px;font-size:11px}
  .tag-row{display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border-bottom:1px solid #21262d;cursor:pointer;font-size:13px}
  .tag-row:hover{background:#1c2333}
  .tag-row.active{background:#1f2937}
  .tag-name{color:#f0f6fc;font-weight:600}
  .tag-meta{color:#8b949e;font-size:11px}
  .detail-section{margin-bottom:16px}
  .detail-section h3{font-size:12px;color:#8b949e;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
  .detail-items{display:flex;flex-wrap:wrap;gap:6px}
  .detail-items .item{background:#1f2937;border-radius:4px;padding:3px 8px;font-size:12px;color:#c9d1d9}
  .detail-items .item .del{color:#da3633;margin-left:4px;cursor:pointer;font-weight:700}
  .detail-items .item .del:hover{color:#f85149}
  .detail-items .item .tag-link{color:#58a6ff;margin-left:4px;cursor:pointer}
  .detail-items .item .tag-link:hover{color:#79c0ff}
  .empty-hint{color:#484f58;font-style:italic;font-size:12px}
  #graph-container{background:#161b22;border:1px solid #30363d;border-radius:8px;width:100%;height:100%;min-height:500px;overflow:hidden}
  #graph-container svg{display:block;width:100%;height:100%}
  .graph-tooltip{position:absolute;background:#1f2937;border:1px solid #30363d;border-radius:6px;padding:8px 12px;font-size:12px;pointer-events:none;opacity:0;transition:opacity .15s;color:#c9d1d9}
  .nav-bar{margin-bottom:20px;font-size:12px}
  .nav-bar a{color:#58a6ff;text-decoration:none}
  .nav-bar a:hover{text-decoration:underline}
  .nav-bar .sep{color:#30363d;margin:0 8px}
  .toast{position:fixed;top:20px;right:20px;background:#238636;color:#fff;padding:10px 16px;border-radius:6px;font-size:13px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:999}
  .toast.error{background:#da3633}
  .toast.show{opacity:1}
</style>
</head>
<body>

<div class="nav-bar">
  <a href="/">◀ 监控面板</a><span class="sep">/</span>标签管理
</div>

<h1>标签管理</h1>
<p class="subtitle">创建标签、管理别名、关联节点、建立概念关系</p>

<div class="layout">
  <div class="left">
    <div class="card">
      <h2>所有标签</h2>
      <div id="tag-list"><div class="empty-hint">加载中...</div></div>
    </div>
    <div class="card">
      <h2>创建标签</h2>
      <div class="form-row">
        <input id="new-tag-name" placeholder="标签名" />
      </div>
      <div class="form-row">
        <input id="new-tag-aliases" placeholder="别名（逗号分隔，可选）" />
      </div>
      <button class="btn btn-primary" onclick="createTag()">创建</button>
    </div>
  </div>

  <div class="right">
    <div id="detail-panel">
      <div class="card" id="detail-card" style="display:none">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <h2 style="margin:0">详情: <span id="detail-name" style="color:#f0f6fc"></span></h2>
          <div style="display:flex;gap:6px">
            <button class="btn btn-sm btn-primary" onclick="showRename()">重命名</button>
            <button class="btn btn-sm btn-danger" onclick="deleteCurrentTag()">删除</button>
          </div>
        </div>

        <div class="detail-section" id="rename-section" style="display:none">
          <h3>重命名</h3>
          <div class="form-row">
            <input id="rename-input" placeholder="新名称" />
            <button class="btn btn-sm btn-primary" onclick="renameCurrentTag()">确认</button>
            <button class="btn btn-sm" style="background:#30363d;color:#c9d1d9" onclick="hideRename()">取消</button>
          </div>
        </div>

        <div class="detail-section">
          <h3>别名</h3>
          <div class="detail-items" id="alias-list"><span class="empty-hint">无别名</span></div>
          <div class="form-row" style="margin-top:8px">
            <input id="new-alias" placeholder="添加别名..." />
            <button class="btn btn-sm btn-primary" onclick="addAlias()">添加</button>
          </div>
        </div>

        <div class="detail-section">
          <h3>关联节点</h3>
          <div class="detail-items" id="node-list"><span class="empty-hint">无关联节点</span></div>
          <div class="form-row" style="margin-top:8px">
            <input id="link-node" placeholder="节点名..." />
            <button class="btn btn-sm btn-primary" onclick="linkNode()">关联</button>
          </div>
        </div>

        <div class="detail-section">
          <h3>概念关联</h3>
          <div class="detail-items" id="conc-list"><span class="empty-hint">无概念关联</span></div>
          <div class="form-row" style="margin-top:8px">
            <input id="conc-tag" placeholder="关联的标签名..." />
            <input id="conc-weight" type="number" value="1" min="1" max="10" style="width:60px" />
            <button class="btn btn-sm btn-primary" onclick="addConc()">关联</button>
          </div>
        </div>
      </div>

      <div id="graph-container"></div>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
let selectedTag = null;
let graphData = {nodes:[], edges:[]};

// ── Toast ────────────────────────────────────────
function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError?' error':'');
  setTimeout(() => el.className = 'toast', 2000);
}

// ── API helper ───────────────────────────────────
async function api(method, path, body) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ── Load tags ────────────────────────────────────
async function loadTags() {
  try {
    const data = await api('GET', '/tags');
    renderTagList(data.tags);
    renderGraph();
  } catch(e) { toast(e.message, true); }
}

function renderTagList(tags) {
  const el = document.getElementById('tag-list');
  if (!tags.length) {
    el.innerHTML = '<div class="empty-hint">暂无标签</div>';
    return;
  }
  el.innerHTML = tags.map(t => `<div class="tag-row${selectedTag===t.name?' active':''}" onclick="selectTag('${t.name}')">
    <span class="tag-name">${esc(t.name)}</span>
    <span class="tag-meta">${t.nodes} 节点${t.aliases?' · '+esc(t.aliases):''}${t.conc_tags?' · '+esc(t.conc_tags):''}</span>
  </div>`).join('');
}

function esc(s) { return s.replace(/[&<>"]/g, function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m];}); }

// ── Tag CRUD ─────────────────────────────────────
async function createTag() {
  const name = document.getElementById('new-tag-name').value.trim();
  if (!name) { toast('标签名不能为空', true); return; }
  const aliasesStr = document.getElementById('new-tag-aliases').value.trim();
  const aliases = aliasesStr ? aliasesStr.split(',').map(s=>s.trim()).filter(Boolean) : [];
  try {
    await api('POST', '/tags', {name, aliases});
    document.getElementById('new-tag-name').value = '';
    document.getElementById('new-tag-aliases').value = '';
    toast(`标签 "${name}" 已创建`);
    selectTag(name);
    await loadTags();
  } catch(e) { toast(e.message, true); }
}

async function deleteCurrentTag() {
  if (!selectedTag) return;
  if (!confirm(`确定删除标签 "${selectedTag}"？`)) return;
  try {
    await api('DELETE', `/tags/${encodeURIComponent(selectedTag)}`);
    toast(`标签 "${selectedTag}" 已删除`);
    selectedTag = null;
    document.getElementById('detail-card').style.display = 'none';
    await loadTags();
  } catch(e) { toast(e.message, true); }
}

function showRename() {
  document.getElementById('rename-section').style.display = 'block';
  document.getElementById('rename-input').value = selectedTag;
}

function hideRename() {
  document.getElementById('rename-section').style.display = 'none';
}

async function renameCurrentTag() {
  const newName = document.getElementById('rename-input').value.trim();
  if (!newName) { toast('名称不能为空', true); return; }
  try {
    await api('PUT', `/tags/${encodeURIComponent(selectedTag)}`, {name: newName});
    toast(`已重命名为 "${newName}"`);
    hideRename();
    selectedTag = newName;
    await loadTags();
    await loadDetail(newName);
  } catch(e) { toast(e.message, true); }
}

// ── Select & Detail ──────────────────────────────
async function selectTag(name) {
  selectedTag = name;
  await loadTags();
  await loadDetail(name);
}

async function loadDetail(name) {
  try {
    const data = await api('GET', '/tags');
    const tag = data.tags.find(t => t.name === name);
    if (!tag) { document.getElementById('detail-card').style.display = 'none'; return; }

    document.getElementById('detail-card').style.display = 'block';
    document.getElementById('detail-name').textContent = tag.name;

    // Aliases
    const aliasList = document.getElementById('alias-list');
    const aliases = tag.aliases ? tag.aliases.split(', ').filter(Boolean) : [];
    aliasList.innerHTML = aliases.length
      ? aliases.map(a => `<span class="item">${esc(a)}<span class="del" onclick="removeAlias('${esc(a)}')">×</span></span>`).join('')
      : '<span class="empty-hint">无别名</span>';

    // Nodes
    const nodeList = document.getElementById('node-list');
    const nodes = tag.node_list || [];
    nodeList.innerHTML = nodes.length
      ? nodes.map(n => `<span class="item">${esc(n)}<span class="del" onclick="unlinkNode('${esc(n)}')">×</span></span>`).join('')
      : '<span class="empty-hint">无关联节点</span>';

    // Concept tags
    const concList = document.getElementById('conc-list');
    const concs = tag.conc_tags ? tag.conc_tags.split(', ').filter(Boolean) : [];
    concList.innerHTML = concs.length
      ? concs.map(c => {
          const m = c.match(/(.+)\((\d+)\)/);
          const ct = m ? m[1] : c;
          return `<span class="item">${esc(c)}<span class="tag-link" onclick="selectTag('${esc(ct)}')">→</span><span class="del" onclick="removeConc('${esc(ct)}')">×</span></span>`;
        }).join('')
      : '<span class="empty-hint">无概念关联</span>';
  } catch(e) { toast(e.message, true); }
}

// ── Alias ops ────────────────────────────────────
async function addAlias() {
  const alias = document.getElementById('new-alias').value.trim();
  if (!alias) return;
  try {
    await api('POST', `/tags/${encodeURIComponent(selectedTag)}/aliases`, {alias});
    document.getElementById('new-alias').value = '';
    await loadDetail(selectedTag);
    await loadTags();
    toast(`别名 "${alias}" 已添加`);
  } catch(e) { toast(e.message, true); }
}

async function removeAlias(alias) {
  try {
    await api('DELETE', `/tags/${encodeURIComponent(selectedTag)}/aliases/${encodeURIComponent(alias)}`);
    await loadDetail(selectedTag);
    await loadTags();
  } catch(e) { toast(e.message, true); }
}

// ── Node link ops ─────────────────────────────────
async function linkNode() {
  const node = document.getElementById('link-node').value.trim();
  if (!node) return;
  try {
    await api('POST', `/tags/${encodeURIComponent(selectedTag)}/link`, {node});
    document.getElementById('link-node').value = '';
    await loadDetail(selectedTag);
    await loadTags();
    toast(`节点 "${node}" 已关联`);
  } catch(e) { toast(e.message, true); }
}

async function unlinkNode(node) {
  try {
    await api('DELETE', `/tags/${encodeURIComponent(selectedTag)}/link/${encodeURIComponent(node)}`);
    await loadDetail(selectedTag);
    await loadTags();
  } catch(e) { toast(e.message, true); }
}

// ── Concept ops ──────────────────────────────────
async function addConc() {
  const target = document.getElementById('conc-tag').value.trim();
  const weight = parseInt(document.getElementById('conc-weight').value) || 1;
  if (!target) return;
  try {
    await api('POST', `/tags/${encodeURIComponent(selectedTag)}/conc`, {target, weight});
    document.getElementById('conc-tag').value = '';
    await loadDetail(selectedTag);
    await loadTags();
    await renderGraph();
    toast(`概念关联 "${selectedTag} ↔ ${target}" 已建立`);
  } catch(e) { toast(e.message, true); }
}

async function removeConc(target) {
  try {
    await api('DELETE', `/tags/${encodeURIComponent(selectedTag)}/conc/${encodeURIComponent(target)}`);
    await loadDetail(selectedTag);
    await loadTags();
    await renderGraph();
  } catch(e) { toast(e.message, true); }
}

// ── D3 Force-Directed Graph ──────────────────────
async function renderGraph() {
  const container = document.getElementById('graph-container');
  const width = container.clientWidth || 800;
  const height = container.clientHeight || 500;

  // Remove old svg
  container.innerHTML = '';

  try {
    const data = await api('GET', '/tags/graph');
    if (!data.nodes.length) {
      container.innerHTML = '<div style="padding:40px;text-align:center;color:#484f58">无标签数据，创建标签后这里将展示概念关系图</div>';
      return;
    }

    const svg = d3.select(container).append('svg')
        .attr('width', width).attr('height', height);

    // Tooltip
    const tooltip = d3.select(container).append('div')
        .attr('class', 'graph-tooltip')
        .style('position', 'absolute');

    const g = svg.append('g');

    // Zoom & pan
    svg.call(d3.zoom().scaleExtent([0.2, 5]).on('zoom', (event) => {
      g.attr('transform', event.transform);
    }));

    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2));

    const link = g.append('g')
        .selectAll('line')
        .data(data.edges)
        .join('line')
        .attr('stroke', '#30363d')
        .attr('stroke-width', d => Math.max(1, d.weight || 1))
        .attr('stroke-opacity', 0.6);

    const node = g.append('g')
        .selectAll('circle')
        .data(data.nodes)
        .join('circle')
        .attr('r', d => Math.max(8, Math.min(20, 5 + (d.nodeCount || 0) * 3)))
        .attr('fill', '#58a6ff')
        .attr('stroke', '#1f2937')
        .attr('stroke-width', 2)
        .style('cursor', 'pointer')
        .on('mouseover', function(event, d) {
          tooltip.style('opacity', 1)
              .html(`<strong>${d.id}</strong> (${d.nodeCount} 节点)`);
        })
        .on('mousemove', function(event) {
          tooltip.style('left', (event.offsetX + 12) + 'px')
              .style('top', (event.offsetY - 10) + 'px');
        })
        .on('mouseout', function() {
          tooltip.style('opacity', 0);
        })
        .on('click', function(event, d) {
          selectTag(d.id);
        })
        .call(d3.drag()
            .on('start', (event, d) => {
              if (!event.active) simulation.alphaTarget(0.3).restart();
              d.fx = d.x; d.fy = d.y;
            })
            .on('drag', (event, d) => {
              d.fx = event.x; d.fy = event.y;
            })
            .on('end', (event, d) => {
              if (!event.active) simulation.alphaTarget(0);
              d.fx = null; d.fy = null;
            }));

    const label = g.append('g')
        .selectAll('text')
        .data(data.nodes)
        .join('text')
        .text(d => d.id)
        .attr('font-size', 10)
        .attr('dx', 12)
        .attr('dy', 4)
        .attr('fill', '#8b949e')
        .style('pointer-events', 'none');

    simulation.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('cx', d => d.x).attr('cy', d => d.y);
      label.attr('x', d => d.x).attr('y', d => d.y);
    });
  } catch(e) { toast(e.message, true); }
}

// ── Init ─────────────────────────────────────────
loadTags();

// Handle resize
window.addEventListener('resize', renderGraph);
</script>
</body>
</html>
"""


@app.get("/tags/ui")
async def tags_page():
    return HTMLResponse(TAGS_HTML)


# ── 辅助启动 ──────────────────────────────────────

async def run_server(
    monitor_instance: RuntimeMonitor,
    host: str = "127.0.0.1",
    port: int = 8765,
    tag_manager_instance: TagManager | None = None,
    runtime_instance=None,
):
    """在已有事件循环中启动 uvicorn 服务器。"""
    import uvicorn

    global monitor, tag_manager, runtime_ref
    monitor = monitor_instance
    tag_manager = tag_manager_instance
    runtime_ref = runtime_instance

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="asyncio",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
