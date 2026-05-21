"""Actor Panel —— 同构操作面板状态协议。

为 User 和 Operator 提供统一的 panel state 结构。
供 runtime/server.py 及 dashboard 消费。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from mgraph import MGraph, Node, NodePtr
from questnode import AnswerNode, QuestNode


# ── 收藏夹条目（Actor-local runtime state，Issue 004 落地） ─────


@dataclass
class StashItem:
    node_id: str = ""
    title: str = ""
    added_at: float = 0.0
    expires_at: float = 0.0
    reason: str = ""


# ── 消息信封（Issue 006 落地） ──────────────────────────────


@dataclass
class MessageEnvelope:
    id: str = ""
    recipient: str = ""
    type: str = ""
    payload: dict = field(default_factory=dict)
    summary: str = ""
    created_at: float = 0.0
    status: str = "active"  # active | done | deleted | blocked


# ── 统一面板状态 ─────────────────────────────────────────


@dataclass
class ActorPanelState:
    """统一面板状态 —— User 和 Operator 共用同一结构。"""
    actor_id: str = ""
    actor_kind: str = ""  # "user" | "operator"
    current_node: str = ""
    current_node_kind: str = ""
    current_node_title: str = ""
    current_node_content_preview: str = ""
    out_edges: list[dict] = field(default_factory=list)
    in_edges: list[dict] = field(default_factory=list)
    stash: list[dict] = field(default_factory=list)
    selected_message: str = ""
    active_messages: list[dict] = field(default_factory=list)
    blocked_messages: list[dict] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "current_node": self.current_node,
            "current_node_kind": self.current_node_kind,
            "current_node_title": self.current_node_title,
            "current_node_content_preview": self.current_node_content_preview,
            "out_edges": list(self.out_edges),
            "in_edges": list(self.in_edges),
            "stash": list(self.stash),
            "selected_message": self.selected_message,
            "active_messages": list(self.active_messages),
            "blocked_messages": list(self.blocked_messages),
            "timestamp": self.timestamp,
        }


# ── User Actor ─────────────────────────────────────────────


class UserActor:
    """User Actor —— 人类用户的图游标。

    User 拥有可手动控制的 current node、stash、selected message。
    Operator 的对应状态由其 AsyncOperator 实例管理。
    """

    def __init__(self):
        self.id = "user"
        self.kind = "user"
        self.current = NodePtr()
        self.stash: list[StashItem] = []
        self.selected_message: str = ""
        self.active_messages: list[MessageEnvelope] = []
        self.blocked_messages: list[MessageEnvelope] = []

    def bind(self, node):
        self.current.bind(node)
        return self

    @property
    def current_node(self) -> str:
        try:
            return self.current.get().name
        except ReferenceError:
            return ""

    def build_panel_state(self, graph: MGraph | None = None) -> ActorPanelState:
        """构建当前 User 的面板快照。"""
        state = ActorPanelState(
            actor_id=self.id,
            actor_kind=self.kind,
            current_node=self.current_node,
            timestamp=time.time(),
        )

        # 如果指针空但图非空，自动绑定到第一个内容节点
        if not self.current and graph is not None and graph.V:
            content_nodes = [
                n for n in graph.V
                if not isinstance(n, (QuestNode, AnswerNode))
            ]
            if content_nodes:
                self.bind(content_nodes[0])
                state.current_node = content_nodes[0].name

        # 填充当前节点详情
        try:
            node = self.current.get()
            state.current_node = node.name
            state.current_node_kind = _node_kind(node)
            state.current_node_title = getattr(node, "title", node.name) or node.name
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
        except ReferenceError:
            pass

        # 收藏夹（按需过期过滤）
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


# ── Operator Panel 构建 ──────────────────────────────────


def build_operator_panel_state(
    operator_id: str,
    current_node_name: str,
    mbti: str = "",
    active_quests: int = 0,
    last_action: str = "",
    graph: MGraph | None = None,
    timestamp: float = 0.0,
) -> ActorPanelState:
    """从 Operator 快照构建同构 panel state。"""
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


def _node_kind(node) -> str:
    if isinstance(node, QuestNode):
        return "quest"
    if isinstance(node, AnswerNode):
        return "answer"
    return getattr(node, "kind", "document")
