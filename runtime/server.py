"""FastAPI + SSE 监控面板 —— 与 Runtime 共享事件循环。"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，以便直接运行 runtime/server.py 时能导入 questnode 等顶层模块
_PROJ_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from questnode import AnswerNode, QuestNode
from runtime.actor_panel import (
    UserActor,
    build_operator_panel_state,
)
from runtime.monitor import RuntimeMonitor
from tag_manager import TagManager

# ── FastAPI App ────────────────────────────────────

app = FastAPI(title="M-Grammaton Runtime Monitor")
monitor: RuntimeMonitor | None = None
tag_manager: TagManager | None = None
runtime_ref = None
user_actor_ref: UserActor | None = None


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


@app.get("/api/dashboard/events/recent")
async def dashboard_events_recent():
    if monitor is None:
        return {"events": []}
    return {"events": monitor.recent_events(limit=50)}


@app.get("/api/dashboard/traces")
async def dashboard_traces():
    if monitor is None:
        return {"traces": []}
    return {"traces": monitor.recent_decision_traces(limit=10)}


# ── Actor Panel API ───────────────────────────────────


@app.get("/api/actors")
async def list_actors():
    """返回所有 Actor（含 User 和 Operator）的摘要列表。"""
    result: list[dict] = []
    if user_actor_ref is not None:
        result.append(user_actor_ref.to_actor_summary())
    if monitor is not None:
        for snap in sorted(monitor.snapshot().values(), key=lambda s: s.operator_id):
            result.append({
                "id": snap.operator_id,
                "kind": "operator",
                "current_node": snap.current_node,
            })
    return {"actors": result, "count": len(result)}


@app.get("/api/actors/{actor_id}/panel")
async def actor_panel(actor_id: str):
    """返回指定 Actor 的面板快照。"""
    if monitor is None:
        return {"error": "monitor not ready", "ready": False}

    # User Actor
    if user_actor_ref is not None and actor_id == user_actor_ref.id:
        graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
        state = user_actor_ref.build_panel_state(graph)
        return {"ready": True, "panel": state.to_dict()}

    # Operator Actor
    ops = monitor.snapshot()
    if actor_id in ops:
        snap = ops[actor_id]
        graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
        state = build_operator_panel_state(
            operator_id=snap.operator_id,
            current_node_name=snap.current_node,
            mbti=snap.mbti,
            active_quests=snap.active_quests,
            last_action=snap.last_action,
            graph=graph,
            timestamp=snap.timestamp,
        )
        return {"ready": True, "panel": state.to_dict()}

    return {"ready": False, "error": f"actor '{actor_id}' not found"}


@app.post("/api/actors/user/select_node")
async def user_select_node(node_id: str):
    """切换 User Actor 的 current node（点击全局图节点时调用）。"""
    if user_actor_ref is None:
        return {"error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    if graph is None:
        return {"error": "graph not ready"}
    for node in graph.V:
        if node.name == node_id:
            user_actor_ref.bind(node)
            state = user_actor_ref.build_panel_state(graph)
            return {"ok": True, "panel": state.to_dict()}
    return {"ok": False, "error": f"node '{node_id}' not found"}


# ── Actor Panel Commands ─────────────────────────────


@app.post("/api/actors/user/select_out_edge")
async def api_select_out_edge(target: str):
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    ok = user_actor_ref.select_out_edge(target)
    if not ok:
        return {"ok": False, "error": f"out edge to '{target}' not found"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": True, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/nav_selected_edge")
async def api_nav_selected_edge():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    ok, detail = user_actor_ref.nav_selected_edge(graph)
    if not ok:
        return {"ok": False, "error": detail}
    return {"ok": True, "detail": detail, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/random_select_out_edge")
async def api_random_select_out_edge():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    ok, detail = user_actor_ref.random_select_out_edge(graph)
    if not ok:
        return {"ok": False, "error": detail}
    return {"ok": True, "detail": detail, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/random_reset_cursor")
async def api_random_reset_cursor():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    ok, detail = user_actor_ref.random_reset_cursor(graph)
    if not ok:
        return {"ok": False, "error": detail}
    return {"ok": True, "detail": detail, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/add_to_stash")
async def api_add_to_stash(node_id: str, reason: str = "", ttl: int | None = 300):
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    if graph is None:
        return {"ok": False, "error": "graph not ready"}
    for node in graph.V:
        if node.name == node_id:
            ok = user_actor_ref.add_to_stash(node, reason, ttl)
            return {"ok": ok, "panel": user_actor_ref.build_panel_state(graph).to_dict()}
    return {"ok": False, "error": f"node '{node_id}' not found"}


@app.post("/api/actors/user/remove_from_stash")
async def api_remove_from_stash(node_id: str):
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    ok = user_actor_ref.remove_from_stash(node_id)
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": ok, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/select_message_next")
async def api_select_message_next():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    ok = user_actor_ref.select_message_next()
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": ok, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/select_message_prev")
async def api_select_message_prev():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    ok = user_actor_ref.select_message_prev()
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": ok, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/set_message_done")
async def api_set_message_done():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    ok = user_actor_ref.set_message_done()
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": ok, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/delete_message")
async def api_delete_message():
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    ok = user_actor_ref.delete_message()
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": ok, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/add_message")
async def api_add_message(type: str, summary: str = ""):
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    msg_id = user_actor_ref.add_message(type, summary)
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    return {"ok": True, "message_id": msg_id, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.get("/api/actors/user/events")
async def api_user_events():
    if user_actor_ref is None:
        return {"events": []}
    return {"events": user_actor_ref.pop_events()}


@app.post("/api/actors/user/commit_note")
async def api_commit_note(content: str):
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    ok, detail = user_actor_ref.commit_note(content, graph)
    return {"ok": ok, "detail": detail, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


@app.post("/api/actors/user/commit_reply")
async def api_commit_reply(content: str, quest_name: str | None = None):
    if user_actor_ref is None:
        return {"ok": False, "error": "user actor not ready"}
    graph = getattr(runtime_ref, "graph", None) if runtime_ref else None
    ok, detail = user_actor_ref.commit_reply(content, quest_name, graph)
    return {"ok": ok, "detail": detail, "panel": user_actor_ref.build_panel_state(graph).to_dict()}


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
        "actors": [],
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
        "actors": _actor_list(user_actor_ref, monitor_obj),
        "events": monitor_obj.recent_events(limit=30) if monitor_obj else [],
        "decision_traces": monitor_obj.recent_decision_traces(limit=10) if monitor_obj else [],
    }


def _actor_list(user_actor, monitor_obj) -> list[dict]:
    actors: list[dict] = []
    if user_actor is not None:
        actors.append(user_actor.to_actor_summary())
    if monitor_obj is not None:
        for snap in sorted(monitor_obj.snapshot().values(), key=lambda s: s.operator_id):
            actors.append({
                "id": snap.operator_id,
                "kind": "operator",
                "current_node": snap.current_node,
            })
    return actors


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


def _load_dashboard_html() -> str:
    return (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")


DASHBOARD_HTML = _load_dashboard_html()


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

    global monitor, tag_manager, runtime_ref, user_actor_ref
    monitor = monitor_instance
    tag_manager = tag_manager_instance
    runtime_ref = runtime_instance
    if runtime_instance is not None:
        user_actor_ref = getattr(runtime_instance, "user_actor", None)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="asyncio",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
