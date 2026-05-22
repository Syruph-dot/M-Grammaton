"""Actor Panel —— 同构操作面板状态协议。

为 User 和 Operator 提供统一的 panel state 结构。
供 runtime/server.py 及 dashboard 消费。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mgraph import MGraph, Node, NodePtr
from questnode import AnswerNode, QuestNode


# ── 收藏夹条目（Actor-local runtime state） ─────


@dataclass
class StashItem:
    node_id: str = ""
    title: str = ""
    added_at: float = 0.0
    expires_at: float = 0.0
    reason: str = ""


# ── 消息信封 ──────────────────────────────


@dataclass
class MessageEnvelope:
    id: str = ""
    recipient: str = ""
    type: str = ""
    payload: dict = field(default_factory=dict)
    summary: str = ""
    created_at: float = 0.0
    status: str = "active"  # active | done | deleted | blocked


# ── 统一面板状态 ─────────────────────────


@dataclass
class ActorPanelState:
    """统一面板状态 —— User 和 Operator 共用同一结构。"""
    actor_id: str = ""
    actor_kind: str = ""  # "user" | "operator"
    current_node: str = ""
    current_node_kind: str = ""
    current_node_title: str = ""
    current_node_content_preview: str = ""
    is_readonly: bool = False
    out_edges: list[dict] = field(default_factory=list)
    in_edges: list[dict] = field(default_factory=list)
    stash: list[dict] = field(default_factory=list)
    selected_message: str = ""
    active_messages: list[dict] = field(default_factory=list)
    blocked_messages: list[dict] = field(default_factory=list)
    timestamp: float = 0.0
    search_cooldown_until: float = 0.0

    def to_dict(self) -> dict:
        return {
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "current_node": self.current_node,
            "current_node_kind": self.current_node_kind,
            "current_node_title": self.current_node_title,
            "current_node_content_preview": self.current_node_content_preview,
            "is_readonly": self.is_readonly,
            "out_edges": list(self.out_edges),
            "in_edges": list(self.in_edges),
            "stash": list(self.stash),
            "selected_message": self.selected_message,
            "active_messages": list(self.active_messages),
            "blocked_messages": list(self.blocked_messages),
            "timestamp": self.timestamp,
            "search_cooldown_until": self.search_cooldown_until,
        }


# ── 共享 ActorPanel ─────────────────────────


STASH_DEFAULT_TTL = 300  # 5 分钟


class ActorPanel:
    """共享 Actor 面板 —— UserActor 和 AsyncOperator 各持一个实例。"""

    def __init__(self, actor_id: str = "", actor_kind: str = ""):
        self.id = actor_id
        self.kind = actor_kind
        self.current = NodePtr()
        self.stash: list[StashItem] = []
        self.selected_message: str = ""
        self.active_messages: list[MessageEnvelope] = []
        self.blocked_messages: list[MessageEnvelope] = []
        self._selected_out_edge_target: str = ""
        self._panel_events: list[dict] = []
        self._message_counter = 0
        self.search_cooldown_until: float = 0.0

    # ── 基础操作 ────────────────────────────

    def bind(self, node):
        self.current.bind(node)
        self._selected_out_edge_target = ""
        return self

    @property
    def current_node(self) -> str:
        try:
            return self.current.get().name
        except ReferenceError:
            return ""

    # ── 面板事件 ──────────────────────────

    def _add_event(self, action: str, detail: str = ""):
        self._panel_events.append({
            "actor_id": self.id,
            "action": action,
            "detail": detail,
            "timestamp": time.time(),
        })
        if len(self._panel_events) > 200:
            self._panel_events = self._panel_events[-100:]

    def pop_events(self) -> list[dict]:
        events = list(self._panel_events)
        self._panel_events = []
        return events

    # ── Cursor 命令 ───────────────────────

    def select_out_edge(self, target_node_name: str) -> bool:
        try:
            node = self.current.get()
        except ReferenceError:
            return False
        for e in node.outlinks:
            if e.target.name == target_node_name:
                self._selected_out_edge_target = target_node_name
                self._add_event("select_out_edge", target_node_name)
                return True
        return False

    def nav_selected_edge(self, graph: MGraph | None = None) -> tuple[bool, str]:
        target = self._selected_out_edge_target
        if not target:
            return False, "no_selected_edge"
        try:
            node = self.current.get()
        except ReferenceError:
            return False, "no_current_node"
        valid = any(e.target.name == target for e in node.outlinks)
        if not valid:
            self._selected_out_edge_target = ""
            return False, "stale_edge"
        if graph is None:
            return False, "no_graph"
        for n in graph.V:
            if n.name == target:
                self.bind(n)
                self._add_event("nav_selected_edge", target)
                return True, target
        self._selected_out_edge_target = ""
        return False, "target_not_found"

    def random_select_out_edge(self, graph: MGraph | None = None) -> tuple[bool, str]:
        try:
            node = self.current.get()
        except ReferenceError:
            return False, "no_current_node"
        if not node.outlinks:
            self._selected_out_edge_target = ""
            return False, "no_out_edges"
        total = sum(e.value for e in node.outlinks)
        if total <= 0:
            import random
            edge = random.choice(node.outlinks)
        else:
            import random
            r = random.random() * total
            walked = 0.0
            edge = node.outlinks[-1]
            for e in node.outlinks:
                walked += e.value
                if walked >= r:
                    edge = e
                    break
        self._selected_out_edge_target = edge.target.name
        self._add_event("random_select_out_edge", edge.target.name)
        return True, edge.target.name

    def random_reset_cursor(self, graph: MGraph | None = None) -> tuple[bool, str]:
        if graph is None or not graph.V:
            return False, "empty_graph"
        import random
        node = random.choice(list(graph.V))
        self.bind(node)
        self._add_event("random_reset_cursor", node.name)
        return True, node.name

    # ── Stash ─────────────────────────────

    def add_to_stash(self, node, reason: str = "", ttl: int | None = None) -> bool:
        try:
            node_name = node.name
            title = getattr(node, "title", node_name) or node_name
        except Exception:
            return False
        for item in self.stash:
            if item.node_id == node_name:
                return False
        now = time.time()
        item = StashItem(
            node_id=node_name,
            title=title,
            added_at=now,
            expires_at=now + (ttl if ttl is not None else STASH_DEFAULT_TTL),
            reason=reason,
        )
        self.stash.append(item)
        self._add_event("add_to_stash", node_name)
        return True

    def remove_from_stash(self, node_id: str) -> bool:
        for i, item in enumerate(self.stash):
            if item.node_id == node_id:
                self.stash.pop(i)
                self._add_event("remove_from_stash", node_id)
                return True
        return False

    def get_stash_context(self, max_items: int = 5) -> list[dict]:
        now = time.time()
        valid = [s for s in self.stash if s.expires_at <= 0 or s.expires_at > now]
        return [
            {"node_id": s.node_id, "title": s.title, "reason": s.reason,
             "added_at": s.added_at}
            for s in valid[-max_items:]
        ]

    # ── Stash 持久化 ───────────────────────

    def save_stash(self, data_dir: str) -> None:
        if not self.id or self.kind != "operator":
            return
        operator_dir = Path(data_dir) / "operator"
        operator_dir.mkdir(parents=True, exist_ok=True)
        path = operator_dir / f"stash-{self.id}.json"
        data = [
            {
                "node_id": item.node_id,
                "title": item.title,
                "added_at": item.added_at,
                "expires_at": item.expires_at,
                "reason": item.reason,
            }
            for item in self.stash
        ]
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if path.exists():
            path.unlink()
        tmp.rename(path)

    def load_stash(self, data_dir: str) -> None:
        if not self.id or self.kind != "operator":
            return
        path = Path(data_dir) / "operator" / f"stash-{self.id}.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.stash = []
        for item in data:
            self.stash.append(StashItem(
                node_id=item.get("node_id", ""),
                title=item.get("title", ""),
                added_at=item.get("added_at", 0.0),
                expires_at=item.get("expires_at", 0.0),
                reason=item.get("reason", ""),
            ))

    # ── Message Queue ─────────────────────

    def _next_message_id(self) -> str:
        self._message_counter += 1
        return f"msg_{self.id}_{self._message_counter}"

    def add_message(self, type: str, summary: str = "", payload: dict | None = None) -> str:
        msg_id = self._next_message_id()
        env = MessageEnvelope(
            id=msg_id,
            recipient=self.id,
            type=type,
            payload=payload or {},
            summary=summary,
            created_at=time.time(),
            status="active",
        )
        self.active_messages.append(env)
        return msg_id

    def select_message_next(self) -> bool:
        if not self.active_messages:
            return False
        ids = [m.id for m in self.active_messages if m.status == "active"]
        if not ids:
            return False
        if not self.selected_message or self.selected_message not in ids:
            self.selected_message = ids[0]
        else:
            idx = ids.index(self.selected_message)
            self.selected_message = ids[(idx + 1) % len(ids)]
        return True

    def select_message_prev(self) -> bool:
        if not self.active_messages:
            return False
        ids = [m.id for m in self.active_messages if m.status == "active"]
        if not ids:
            return False
        if not self.selected_message or self.selected_message not in ids:
            self.selected_message = ids[-1]
        else:
            idx = ids.index(self.selected_message)
            self.selected_message = ids[(idx - 1) % len(ids)]
        return True

    def set_message_done(self) -> bool:
        if not self.selected_message:
            return False
        for m in self.active_messages:
            if m.id == self.selected_message:
                m.status = "done"
                self.active_messages.remove(m)
                self.selected_message = ""
                self._add_event("set_message_done", m.id)
                return True
        self.selected_message = ""
        return False

    def delete_message(self) -> bool:
        if not self.selected_message:
            return False
        for m in self.active_messages:
            if m.id == self.selected_message:
                m.status = "deleted"
                self.active_messages.remove(m)
                self.selected_message = ""
                self._add_event("delete_message", m.id)
                return True
        self.selected_message = ""
        return False

    def block_message(self, msg_id: str, reason: str = "unsupported") -> bool:
        for m in self.active_messages:
            if m.id == msg_id:
                m.status = "blocked"
                self.active_messages.remove(m)
                self.blocked_messages.append(m)
                if self.selected_message == msg_id:
                    self.selected_message = ""
                self._add_event("block_message", msg_id)
                return True
        return False

    # ── Note / Reply Commit ────────────────

    def _next_artifact_id(self, prefix: str = "note") -> str:
        self._message_counter += 1
        return f"{prefix}_{self.id}_{int(time.time())}_{self._message_counter}"

    def commit_note(self, content: str, graph: MGraph | None = None) -> tuple[bool, str]:
        if not content.strip():
            return False, "empty_content"
        if graph is None:
            return False, "no_graph"
        try:
            source = self.current.get()
        except ReferenceError:
            return False, "no_current_node"
        note_id = self._next_artifact_id("note")
        note = Node(note_id, kind="note", content=content.strip(), mg=graph)
        note.title = f"Note: {content[:40]}"
        source.link_to(note, 1.0)
        self._add_event("commit_note", note_id)
        return True, note_id

    def commit_reply(self, content: str, quest_name: str | None = None,
                     graph: MGraph | None = None) -> tuple[bool, str]:
        if not content.strip():
            return False, "empty_content"
        if graph is None:
            return False, "no_graph"
        if quest_name:
            for node in graph.V:
                if isinstance(node, QuestNode) and node.name == quest_name:
                    ans_id = self._next_artifact_id("answer")
                    ans = AnswerNode(
                        ans_id,
                        content=content.strip(),
                        answerer_id=self.id,
                        quest_name=quest_name,
                    )
                    graph.add_node(ans)
                    node.link_to(ans, 1.0)
                    self._add_event("commit_reply", ans_id)
                    return True, ans_id
            return False, "quest_not_found"
        return self.commit_note(content, graph)

    # ── Panel State 构建 ────────────────────

    def build_panel_state(self, graph: MGraph | None = None) -> ActorPanelState:
        state = ActorPanelState(
            actor_id=self.id,
            actor_kind=self.kind,
            current_node=self.current_node,
            timestamp=time.time(),
            search_cooldown_until=self.search_cooldown_until,
        )
        if not self.current and graph is not None and graph.V:
            content_nodes = [
                n for n in graph.V
                if not isinstance(n, (QuestNode, AnswerNode))
            ]
            if content_nodes:
                self.bind(content_nodes[0])
                state.current_node = content_nodes[0].name

        try:
            node = self.current.get()
            state.current_node = node.name
            state.current_node_kind = _node_kind(node)
            state.current_node_title = getattr(node, "title", node.name) or node.name
            state.is_readonly = _is_human_source(node)
            content = getattr(node, "content", "")
            state.current_node_content_preview = content[:200] if content else ""
            sel = self._selected_out_edge_target
            state.out_edges = [
                {"target": e.target.name, "target_kind": _node_kind(e.target),
                 "weight": e.value, "selected": e.target.name == sel}
                for e in node.outlinks
            ]
            state.in_edges = [
                {"source": e.source.name, "source_kind": _node_kind(e.source),
                 "weight": e.value}
                for e in node.inlinks
            ]
        except ReferenceError:
            pass

        now = time.time()
        state.stash = [
            {
                "node_id": item.node_id,
                "title": item.title,
                "added_at": item.added_at,
                "expires_at": item.expires_at,
                "reason": item.reason,
            }
            for item in self.stash
            if item.expires_at <= 0 or item.expires_at > now
        ]
        state.selected_message = self.selected_message
        state.active_messages = [
            {"id": m.id, "type": m.type, "summary": m.summary,
             "created_at": m.created_at, "status": m.status}
            for m in self.active_messages
        ]
        state.blocked_messages = [
            {"id": m.id, "type": m.type, "summary": m.summary,
             "created_at": m.created_at, "status": m.status}
            for m in self.blocked_messages
        ]
        return state

    def to_actor_summary(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "current_node": self.current_node,
        }


# ── User Actor（组合 ActorPanel）─────────────


class UserActor:
    """User Actor —— 人类用户的图游标。"""

    def __init__(self):
        self.panel = ActorPanel(actor_id="user", actor_kind="user")

    @property
    def id(self): return self.panel.id
    @property
    def kind(self): return self.panel.kind
    @property
    def current(self): return self.panel.current
    @current.setter
    def current(self, val): self.panel.current = val
    @property
    def stash(self): return self.panel.stash
    @stash.setter
    def stash(self, val): self.panel.stash = val
    @property
    def selected_message(self): return self.panel.selected_message
    @selected_message.setter
    def selected_message(self, val): self.panel.selected_message = val
    @property
    def active_messages(self): return self.panel.active_messages
    @active_messages.setter
    def active_messages(self, val): self.panel.active_messages = val
    @property
    def blocked_messages(self): return self.panel.blocked_messages
    @blocked_messages.setter
    def blocked_messages(self, val): self.panel.blocked_messages = val

    @property
    def current_node(self) -> str:
        return self.panel.current_node

    def bind(self, node):
        return self.panel.bind(node)

    def _add_event(self, action: str, detail: str = ""):
        self.panel._add_event(action, detail)

    def select_out_edge(self, target_node_name: str) -> bool:
        return self.panel.select_out_edge(target_node_name)

    def nav_selected_edge(self, graph: MGraph | None = None) -> tuple[bool, str]:
        return self.panel.nav_selected_edge(graph)

    def random_select_out_edge(self, graph: MGraph | None = None) -> tuple[bool, str]:
        return self.panel.random_select_out_edge(graph)

    def random_reset_cursor(self, graph: MGraph | None = None) -> tuple[bool, str]:
        return self.panel.random_reset_cursor(graph)

    def add_to_stash(self, node, reason: str = "", ttl: int | None = None) -> bool:
        return self.panel.add_to_stash(node, reason, ttl)

    def remove_from_stash(self, node_id: str) -> bool:
        return self.panel.remove_from_stash(node_id)

    def _next_message_id(self) -> str:
        return self.panel._next_message_id()

    def add_message(self, type: str, summary: str = "", payload: dict | None = None) -> str:
        return self.panel.add_message(type, summary, payload)

    def select_message_next(self) -> bool:
        return self.panel.select_message_next()

    def select_message_prev(self) -> bool:
        return self.panel.select_message_prev()

    def set_message_done(self) -> bool:
        return self.panel.set_message_done()

    def delete_message(self) -> bool:
        return self.panel.delete_message()

    def block_message(self, msg_id: str, reason: str = "unsupported") -> bool:
        return self.panel.block_message(msg_id, reason)

    def commit_note(self, content: str, graph: MGraph | None = None) -> tuple[bool, str]:
        return self.panel.commit_note(content, graph)

    def commit_reply(self, content: str, quest_name: str | None = None,
                     graph: MGraph | None = None) -> tuple[bool, str]:
        return self.panel.commit_reply(content, quest_name, graph)

    def build_panel_state(self, graph: MGraph | None = None) -> ActorPanelState:
        return self.panel.build_panel_state(graph)

    def to_actor_summary(self) -> dict:
        return self.panel.to_actor_summary()

    def pop_events(self) -> list[dict]:
        return self.panel.pop_events()


# ── 辅助函数 ─────────────────────────────


def _node_kind(node) -> str:
    if isinstance(node, QuestNode):
        return "quest"
    if isinstance(node, AnswerNode):
        return "answer"
    return getattr(node, "kind", "document")


def _is_human_source(node) -> bool:
    if isinstance(node, (QuestNode, AnswerNode)):
        return False
    return getattr(node, "kind", "document") == "document"


# ── 向后兼容 ─────────────────────────────


def build_operator_panel_state(
    operator_id: str,
    current_node_name: str,
    mbti: str = "",
    active_quests: int = 0,
    last_action: str = "",
    graph: MGraph | None = None,
    timestamp: float = 0.0,
) -> ActorPanelState:
    """从 Operator 快照构建同构 panel state。

    注：新代码请直接使用 operator.panel.build_panel_state(graph)。
    """
    panel = ActorPanel(actor_id=operator_id, actor_kind="operator")
    panel.current = NodePtr()
    state = ActorPanelState(
        actor_id=operator_id,
        actor_kind="operator",
        current_node=current_node_name,
        timestamp=timestamp or time.time(),
    )
    if graph and current_node_name:
        for node in graph.V:
            if node.name == current_node_name:
                state.current_node_kind = _node_kind(node)
                state.current_node_title = (
                    getattr(node, "title", node.name) or node.name
                )
                state.is_readonly = _is_human_source(node)
                content = getattr(node, "content", "")
                state.current_node_content_preview = content[:200] if content else ""
                state.out_edges = [
                    {"target": e.target.name, "target_kind": _node_kind(e.target),
                     "weight": e.value, "selected": False}
                    for e in node.outlinks
                ]
                state.in_edges = [
                    {"source": e.source.name, "source_kind": _node_kind(e.source),
                     "weight": e.value}
                    for e in node.inlinks
                ]
                break
    return state
