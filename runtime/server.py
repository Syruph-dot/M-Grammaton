"""FastAPI + SSE 监控面板 —— 与 Runtime 共享事件循环。"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from runtime.monitor import RuntimeMonitor

# ── HTML 面板 ──────────────────────────────────────

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M-Grammaton Runtime</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'SF Mono','Cascadia Code','Consolas',monospace;background:#0d1117;color:#c9d1d9;padding:24px}
  h1{font-size:18px;margin-bottom:20px;color:#58a6ff}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:24px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
  .card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
  .card-name{font-size:16px;font-weight:700;color:#f0f6fc}
  .card-mbti{font-size:12px;background:#1f2937;padding:2px 8px;border-radius:4px;color:#8b949e}
  .card-body{font-size:13px;line-height:1.8}
  .label{color:#8b949e}.value{color:#f0f6fc}
  .badge{display:inline-block;padding:1px 8px;border-radius:4px;font-size:12px;font-weight:600}
  .badge-wander{background:#0e4429;color:#3fb950}
  .badge-ask{background:#3d1f00;color:#d29922}
  .badge-answer{background:#0e4429;color:#3fb950}
  .badge-score{background:#271052;color:#a371f7}
  .badge-idle,.badge-sleep{background:#1f2937;color:#8b949e}
  .badge-init{background:#1f2937;color:#58a6ff}
  .log{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
  .log h2{font-size:14px;color:#8b949e;margin-bottom:8px}
  .log table{width:100%;border-collapse:collapse;font-size:12px}
  .log td{padding:2px 8px;border-bottom:1px solid #21262d}
  .log .time{color:#484f58}
  .status-bar{display:flex;gap:16px;margin-bottom:16px;font-size:12px;color:#8b949e}
  .status-bar .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
  .dot.on{background:#3fb950}.dot.off{background:#484f58}
  .empty{color:#484f58;font-style:italic}
</style>
</head>
<body>
  <h1>M-Grammaton Runtime Monitor</h1>
  <div class="status-bar" id="status-bar">
    <span><span class="dot on" id="dot"></span> SSE <span id="sse-status">connecting</span></span>
    <span>Operators: <strong id="op-count">0</strong></span>
    <span>Round: <strong id="round">0</strong></span>
  </div>
  <div class="grid" id="card-grid"></div>
  <div class="log">
    <h2>= Recent Actions =</h2>
    <table><tbody id="log-body"><tr><td class="empty">等待 Operator 行动...</td></tr></tbody></table>
  </div>
  <script>
    const cardGrid=document.getElementById('card-grid');
    const logBody=document.getElementById('log-body');
    const opCount=document.getElementById('op-count');
    const roundEl=document.getElementById('round');
    const dot=document.getElementById('dot');
    const sseStatus=document.getElementById('sse-status');
    let round=0, logs=[];
    function badge(a){return '<span class="badge badge-'+a+'">'+a+'</span>'}
    function render(d){
      if(!d||!d.operators)return;
      opCount.textContent=d.operators.length;
      cardGrid.innerHTML=d.operators.map(function(o){
        return '<div class="card">'
          +'<div class="card-header"><span class="card-name">'+o.id+'</span><span class="card-mbti">'+(o.mbti||'—')+'</span></div>'
          +'<div class="card-body">'
          +'<div><span class="label">Node</span> <span class="value">'+(o.node||'—')+'</span></div>'
          +'<div><span class="label">Action</span> '+badge(o.action)+(o.detail?' — '+(o.detail.length>50?o.detail.slice(0,50)+'…':o.detail):'')+'</div>'
          +'<div><span class="label">Quests</span> <span class="value">'+o.quests+'</span></div>'
          +'</div></div>'}).
        join('');
    }
    function addLog(o){
      var now=new Date().toLocaleTimeString('zh-CN',{hour12:false});
      logs.push({time:now,op:o.id,action:o.action,detail:(o.detail||'').slice(0,60)});
      if(logs.length>50)logs.shift();
      round++;
      roundEl.textContent=round;
      logBody.innerHTML=logs.slice(-20).reverse().map(function(r){
        return '<tr><td class="time">'+r.time+'</td><td><strong>'+r.op+'</strong></td><td>'+badge(r.action)+'</td><td>'+(r.detail||'—')+'</td></tr>'}).
        join('');
    }
    var es=new EventSource('/stream');
    es.addEventListener('operator_update',function(e){
      dot.className='dot on';sseStatus.textContent='live';
      var o=JSON.parse(e.data);
      fetch('/snapshot').then(function(r){return r.json()}).then(function(d){render(d)});
      addLog(o);
    });
    es.addEventListener('ping',function(){dot.className='dot on';sseStatus.textContent='connected'});
    es.onerror=function(){dot.className='dot off';sseStatus.textContent='disconnected'};
    fetch('/snapshot').then(function(r){return r.json()}).then(function(d){render(d)});
  </script>
</body>
</html>
"""

# ── FastAPI App ────────────────────────────────────

app = FastAPI(title="M-Grammaton Runtime Monitor")
monitor: RuntimeMonitor | None = None


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


# ── 辅助启动 ──────────────────────────────────────

async def run_server(
    monitor_instance: RuntimeMonitor,
    host: str = "127.0.0.1",
    port: int = 8765,
):
    """在已有事件循环中启动 uvicorn 服务器。"""
    import uvicorn

    global monitor
    monitor = monitor_instance

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="asyncio",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
