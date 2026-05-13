"""Web Dashboard — FastAPI 后端 + WebSocket 实时推送"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import webbrowser
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cli_anything.core.models import TaskStatus, TaskType, ReviewStatus
from cli_anything.core.task_manager import TaskManager, TaskManagerError
from cli_anything.storage.database import Database
from cli_anything.utils.config import Config


# ── 全局状态 ────────────────────────────────────────────────

_db: Database | None = None
_tm: TaskManager | None = None
_config: Config | None = None
_ws_clients: set[WebSocket] = set()
_ws_tokens: set[str] = set()


def _init_web():
    global _db, _tm, _config
    if _db is not None:
        return
    _config = Config()
    _config.load()
    _db = Database(_config.get("database.path"))
    _db.connect()
    _tm = TaskManager(_db, terminal_id="dashboard")


def _get_tm() -> TaskManager:
    _init_web()
    assert _tm is not None
    return _tm


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_web()
    yield
    if _db:
        _db.close()


web_app = FastAPI(title="CLI-Anything Dashboard", lifespan=lifespan)


# ── Basic Auth 中间件 ───────────────────────────────────────

_REALM = "CLI-Anything Dashboard"
_AUTH_DENY = Response(
    status_code=401,
    headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
    content="Unauthorized",
)


@web_app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """可选的 HTTP Basic Auth 认证中间件"""
    if _config is None or not _config.get("dashboard.auth.enabled", False):
        return await call_next(request)
    # WebSocket 升级请求跳过（浏览器不发 Basic Auth header）
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return _AUTH_DENY
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return _AUTH_DENY
    expected_user = _config.get("dashboard.auth.username", "admin")
    expected_pass = _config.get("dashboard.auth.password", "")
    if not (secrets.compare_digest(username, expected_user)
            and secrets.compare_digest(password, expected_pass)):
        return _AUTH_DENY
    return await call_next(request)


# ── WebSocket 广播 ──────────────────────────────────────────

async def broadcast(event: str, data: dict):
    """向所有连接的客户端广播事件"""
    msg = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


@web_app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if _config is not None and _config.get("dashboard.auth.enabled", False):
        token = ws.query_params.get("token", "")
        if not token or token not in _ws_tokens:
            await ws.close(code=1008)
            return
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(ws)


# ── REST API ────────────────────────────────────────────────

@web_app.get("/api/tasks")
def api_list_tasks(
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(100),
):
    tm = _get_tm()
    tasks = tm.list_tasks(
        status=status, task_type=task_type,
        parent_id=parent_id, tag=tag, limit=limit,
    )
    return [t.to_api_dict() for t in tasks]


@web_app.get("/api/tasks/{task_id}")
def api_get_task(task_id: str):
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, 404)
    result = task.to_api_dict()
    subtasks = tm.list_subtasks(task_id)
    if subtasks:
        result["subtasks"] = [s.to_api_dict() for s in subtasks]
        result["progress"] = tm.get_progress(task_id)
    return result


@web_app.get("/api/tasks/{task_id}/logs")
def api_task_logs(task_id: str, limit: int = Query(30)):
    tm = _get_tm()
    logs = tm.get_logs(task_id, limit=limit)
    return [l.to_dict() for l in logs]


@web_app.get("/api/terminals")
def api_list_terminals():
    tm = _get_tm()
    return [t.to_api_dict() for t in tm.list_terminals()]


@web_app.get("/api/dashboard/summary")
def api_summary():
    tm = _get_tm()
    all_tasks = tm.list_tasks(limit=9999)
    masters = [t for t in all_tasks if t.task_type == TaskType.MASTER]
    subtasks = [t for t in all_tasks if t.task_type == TaskType.SUBTASK]

    status_counts = {}
    for t in all_tasks:
        sv = t.status.value
        status_counts[sv] = status_counts.get(sv, 0) + 1

    terminals = tm.list_terminals()
    return {
        "total_tasks": len(all_tasks),
        "master_tasks": len(masters),
        "subtasks": len(subtasks),
        "status_counts": status_counts,
        "terminals": len(terminals),
    }


@web_app.get("/api/ws-token")
def api_ws_token():
    """签发 WebSocket 连接 token（HTTP Basic Auth 开启时由中间件保护）"""
    token = secrets.token_urlsafe(32)
    _ws_tokens.add(token)
    return {"token": token}


# ── 任务操作 API ─────────────────────────────────────────────

@web_app.post("/api/tasks/{task_id}/claim")
async def api_claim_task(task_id: str):
    """领取任务"""
    tm = _get_tm()
    try:
        task = tm.claim_task(task_id)
        await broadcast("task_updated", task.to_api_dict())
        return task.to_api_dict()
    except TaskManagerError as e:
        return JSONResponse({"error": str(e)}, 400)


@web_app.post("/api/tasks/{task_id}/submit")
async def api_submit_task(task_id: str):
    """提交任务"""
    tm = _get_tm()
    try:
        task = tm.submit_task(task_id)
        await broadcast("task_updated", task.to_api_dict())
        return task.to_api_dict()
    except TaskManagerError as e:
        return JSONResponse({"error": str(e)}, 400)


@web_app.post("/api/tasks/{task_id}/verify")
async def api_verify_task(
    task_id: str,
    approved: bool = Body(...),
    comment: str = Body(""),
):
    """验收任务"""
    tm = _get_tm()
    try:
        task = tm.verify_task(task_id, approved=approved, comment=comment)
        await broadcast("task_updated", task.to_api_dict())
        return task.to_api_dict()
    except TaskManagerError as e:
        return JSONResponse({"error": str(e)}, 400)


# ── 审阅 API ────────────────────────────────────────────────

@web_app.post("/api/tasks/{task_id}/review")
async def api_review_task(
    task_id: str,
    approved: bool = Body(...),
    comment: str = Body(""),
):
    """审阅任务：通过或驳回"""
    tm = _get_tm()
    try:
        task = tm.review_task(task_id, approved=approved, comment=comment)
        await broadcast("task_updated", task.to_api_dict())
        return task.to_api_dict()
    except TaskManagerError as e:
        return JSONResponse({"error": str(e)}, 400)


@web_app.post("/api/tasks/{task_id}/resubmit-review")
async def api_resubmit_review(task_id: str):
    """重新提交审阅"""
    tm = _get_tm()
    try:
        task = tm.resubmit_for_review(task_id)
        await broadcast("task_updated", task.to_api_dict())
        return task.to_api_dict()
    except TaskManagerError as e:
        return JSONResponse({"error": str(e)}, 400)


# ── 前端页面 ────────────────────────────────────────────────

@web_app.get("/", response_class=HTMLResponse)
def index():
    return _DASHBOARD_HTML


# ── 启动函数 ────────────────────────────────────────────────

def run_dashboard(host: str = "127.0.0.1", port: int = 8080, auto_open: bool = True):
    """启动 Web Dashboard"""
    import uvicorn

    if auto_open:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    uvicorn.run(web_app, host=host, port=port, log_level="info")


# ── 内嵌 HTML ───────────────────────────────────────────────

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CLI-Anything Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#e2e8f0;--muted:#94a3b8;
--green:#22c55e;--yellow:#eab308;--blue:#3b82f6;--cyan:#06b6d4;--red:#ef4444;
--magenta:#a855f7;--orange:#f97316}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;gap:16px}
header h1{font-size:20px;font-weight:600}
header .badge{background:var(--blue);color:#fff;padding:2px 10px;border-radius:12px;font-size:12px}
.container{max-width:1400px;margin:0 auto;padding:20px}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}
.summary-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;text-align:center}
.summary-card .num{font-size:32px;font-weight:700;margin:4px 0}
.summary-card .label{color:var(--muted);font-size:13px}
.kanban{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-bottom:24px}
.column{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;min-height:200px}
.column h3{font-size:14px;color:var(--muted);margin-bottom:10px;display:flex;align-items:center;gap:6px}
.column h3 .dot{width:8px;height:8px;border-radius:50%}
.task-card{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px;cursor:pointer;transition:border-color .2s}
.task-card:hover{border-color:var(--blue)}
.task-card .title{font-size:13px;font-weight:500;margin-bottom:4px}
.task-card .meta{font-size:11px;color:var(--muted);display:flex;gap:8px}
.task-card .tag{background:var(--border);padding:1px 6px;border-radius:4px;font-size:10px}
.priority-1{border-left:3px solid var(--red)}
.priority-2{border-left:3px solid var(--orange)}
.priority-3{border-left:3px solid var(--yellow)}
.priority-4{border-left:3px solid var(--green)}
.priority-5{border-left:3px solid var(--muted)}
.logs{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.logs h3{font-size:14px;margin-bottom:10px}
.log-item{font-size:12px;padding:4px 0;border-bottom:1px solid var(--border);display:flex;gap:12px}
.log-item .time{color:var(--muted);min-width:130px}
.log-item .action{color:var(--cyan);min-width:100px}
.progress-bar{height:6px;background:var(--border);border-radius:3px;overflow:hidden;margin:6px 0}
.progress-fill{height:100%;background:var(--green);border-radius:3px;transition:width .3s}
.section-title{font-size:16px;font-weight:600;margin:20px 0 12px}
#ws-status{width:8px;height:8px;border-radius:50%;background:var(--red)}
#ws-status.connected{background:var(--green)}
</style>
</head>
<body>
<header>
  <h1>📋 CLI-Anything</h1>
  <span class="badge">Dashboard</span>
  <div style="flex:1"></div>
  <div id="ws-status" title="WebSocket 未连接"></div>
</header>
<div class="container">
  <div class="summary" id="summary"></div>
  <div class="section-title">📌 任务看板</div>
  <div class="kanban" id="kanban"></div>
  <div class="section-title">📝 操作日志</div>
  <div class="logs" id="logs"></div>
</div>
<script>
const STATUS_COLORS={draft:'var(--orange)',pending:'var(--yellow)',claimed:'var(--cyan)',in_progress:'var(--blue)',
submitted:'var(--magenta)',done:'var(--green)',rejected:'var(--red)',blocked:'var(--muted)',cancelled:'#666'};
const STATUS_LABELS={draft:'草稿',pending:'待处理',claimed:'已领取',in_progress:'进行中',
submitted:'已提交',done:'已完成',rejected:'已驳回',blocked:'已阻塞',cancelled:'已取消'};
const PRIORITY_LABELS={1:'🔴',2:'🟠',3:'🟡',4:'🟢',5:'⚪'};
const KANBAN_ORDER=['draft','pending','claimed','in_progress','submitted','done','rejected'];

async function fetchJSON(url){const r=await fetch(url);return r.json()}

async function loadSummary(){
  const d=await fetchJSON('/api/dashboard/summary');
  document.getElementById('summary').innerHTML=`
    <div class="summary-card"><div class="num">${d.total_tasks}</div><div class="label">总任务</div></div>
    <div class="summary-card"><div class="num">${d.master_tasks}</div><div class="label">主任务</div></div>
    <div class="summary-card"><div class="num">${d.subtasks}</div><div class="label">子任务</div></div>
    <div class="summary-card"><div class="num">${d.status_counts.draft||0}</div><div class="label">草稿/审阅中</div></div>
    <div class="summary-card"><div class="num">${d.status_counts.done||0}</div><div class="label">已完成</div></div>
    <div class="summary-card"><div class="num">${d.terminals}</div><div class="label">终端</div></div>
  `;
}

async function loadKanban(){
  const tasks=await fetchJSON('/api/tasks');
  const cols={};
  KANBAN_ORDER.forEach(s=>cols[s]=[]);
  tasks.forEach(t=>{if(cols[t.status])cols[t.status].push(t)});
  let html='';
  KANBAN_ORDER.forEach(s=>{
    const color=STATUS_COLORS[s];
    html+=`<div class="column"><h3><span class="dot" style="background:${color}"></span>${STATUS_LABELS[s]} (${cols[s].length})</h3>`;
    cols[s].forEach(t=>{
      const tags=(t.tags||[]).map(g=>`<span class="tag">${g}</span>`).join('');
      const reviewer=t.reviewer?`<span class="tag">🔍${t.reviewer}</span>`:'';
      html+=`<div class="task-card priority-${t.priority}">
        <div class="title">${PRIORITY_LABELS[t.priority]||''} ${t.title}</div>
        <div class="meta"><span>${t.id}</span><span>${t.task_type}</span>${reviewer}${tags}</div>
      </div>`;
    });
    html+='</div>';
  });
  document.getElementById('kanban').innerHTML=html;
}

async function loadLogs(){
  const logs=await fetchJSON('/api/tasks/'+encodeURIComponent('')+'/logs?limit=20').catch(()=>[]);
  let allLogs=[];
  try{const r=await fetch('/api/tasks');const tasks=await r.json();
    for(const t of tasks.slice(0,10)){
      const l=await fetchJSON(`/api/tasks/${t.id}/logs?limit=5`);allLogs.push(...l);
    }
  }catch(e){}
  allLogs.sort((a,b)=>b.timestamp.localeCompare(a.timestamp));
  allLogs=allLogs.slice(0,20);
  const html=allLogs.map(l=>
    `<div class="log-item"><span class="time">${l.timestamp}</span><span class="action">${l.action}</span><span>${l.task_id}</span><span>${l.detail}</span></div>`
  ).join('');
  document.getElementById('logs').innerHTML=html||'<div style="color:var(--muted)">暂无日志</div>';
}

async function connectWS(){
  let token='';
  try{const t=await fetchJSON('/api/ws-token');token=t.token||''}catch(e){}
  const scheme=location.protocol==='https:'?'wss':'ws';
  const suffix=token?`?token=${encodeURIComponent(token)}`:'';
  const ws=new WebSocket(`${scheme}://${location.host}/ws${suffix}`);
  const dot=document.getElementById('ws-status');
  ws.onopen=()=>{dot.className='connected';dot.title='WebSocket 已连接'};
  ws.onclose=()=>{dot.className='';dot.title='WebSocket 未连接';setTimeout(connectWS,3000)};
  ws.onmessage=(e)=>{const d=JSON.parse(e.data);if(d.event)refresh()};
}

async function refresh(){await Promise.all([loadSummary(),loadKanban(),loadLogs()])}
refresh();
connectWS();
setInterval(refresh,5000);
</script>
</body>
</html>"""
