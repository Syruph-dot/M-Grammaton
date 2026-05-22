"""RuntimeMonitor — 在 AsyncOperator 和监控面板之间搭桥。

同事件循环内直接共享状态，无需线程安全快照。
Monitor 是 Runtime 的一等公民，不是外部观察者。
"""

import asyncio
import copy
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class OperatorSnapshot:
    """Operator 在某时刻的可见状态。"""
    operator_id: str
    current_node: str = ""
    mbti: str = ""
    active_quests: int = 0
    last_action: str = "init"
    last_detail: str = ""
    timestamp: float = 0.0


@dataclass
class DecisionTraceEvent:
    """决策 trace 事件。"""
    operator_id: str
    chosen: str
    temperature: float
    raw_scores: dict
    probabilities: dict
    top_signals: list
    timestamp: float = 0.0


@dataclass
class TokenUsageEvent:
    operator_id: str
    action: str
    tokens: int
    source: str = "estimated"
    timestamp: float = 0.0


class RuntimeMonitor:
    """状态采集 + 双模消费（轮询 & 推送）。

    用法
    ----
    monitor = RuntimeMonitor()
    runtime.monitor = monitor  # AsyncOperator 自动报告

    # TUI 消费
    ops = monitor.snapshot()

    # SSE 消费
    queue = monitor.subscribe()
    snap = await queue.get()
    """

    def __init__(self):
        self._states: dict[str, OperatorSnapshot] = {}
        self._subscribers: list[asyncio.Queue[OperatorSnapshot]] = []
        self._event_subscribers: list[asyncio.Queue[dict]] = []
        self._token_events = deque(maxlen=8192)
        self._total_tokens = 0
        self._reported_requests = 0
        self._estimated_requests = 0
        self._decision_traces: deque[DecisionTraceEvent] = deque(maxlen=100)
        self._event_store: deque[dict] = deque(maxlen=200)

    # ── 被 AsyncOperator 调用 ─────────────────────

    def report_action(self, op_id: str, action: str, detail: str = ""):
        snap = OperatorSnapshot(
            operator_id=op_id,
            last_action=action,
            last_detail=detail,
            timestamp=time.time(),
        )
        # 携带前一轮的静态字段
        if prev := self._states.get(op_id):
            snap.current_node = prev.current_node
            snap.mbti = prev.mbti
            snap.active_quests = prev.active_quests
        self._states[op_id] = snap
        self._push(snap)
        self._push_event({
            "type": "operator_update",
            "operator": self._snapshot_to_dict(snap),
        })

    def update_node(self, op_id: str, node_name: str):
        s = self._states.setdefault(op_id, OperatorSnapshot(operator_id=op_id))
        s.current_node = node_name

    def update_mbti(self, op_id: str, mbti: str):
        s = self._states.setdefault(op_id, OperatorSnapshot(operator_id=op_id))
        s.mbti = mbti

    def update_quests(self, op_id: str, count: int):
        s = self._states.setdefault(op_id, OperatorSnapshot(operator_id=op_id))
        s.active_quests = count

    # ── 被面板消费 ────────────────────────────────

    def snapshot(self) -> dict[str, OperatorSnapshot]:
        return {k: copy.copy(v) for k, v in self._states.items()}

    def subscribe(self) -> asyncio.Queue[OperatorSnapshot]:
        q: asyncio.Queue[OperatorSnapshot] = asyncio.Queue(maxsize=64)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _push(self, snap: OperatorSnapshot):
        stale = []
        for q in self._subscribers:
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                stale.append(q)
        for q in stale:
            self._subscribers.remove(q)

    def subscribe_events(self) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=128)
        self._event_subscribers.append(q)
        return q

    def unsubscribe_events(self, q: asyncio.Queue[dict]):
        if q in self._event_subscribers:
            self._event_subscribers.remove(q)

    def report_tokens(
        self,
        operator_id: str,
        action: str,
        tokens: int,
        source: str = "estimated",
        timestamp: float | None = None,
    ):
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
            "tokens": self._token_event_to_dict(event),
        })

    def token_snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        last_minute = sum(
            event.tokens
            for event in self._token_events
            if now - event.timestamp <= 60.0
        )
        # 5s 分桶，覆盖最近 120s，用于前端吞吐率图表
        bucket_size = 5.0
        num_buckets = 24  # 120 / 5
        bucket_tokens = [0.0] * num_buckets
        for event in self._token_events:
            age = now - event.timestamp
            if 0 <= age < num_buckets * bucket_size:
                idx = int(age / bucket_size)
                bucket_tokens[num_buckets - 1 - idx] += event.tokens
        tps_series = [round(t / bucket_size, 1) for t in bucket_tokens]

        return {
            "total": self._total_tokens,
            "last_minute": last_minute,
            "tokens_per_sec": round(last_minute / 60.0, 1),
            "requests": self._reported_requests + self._estimated_requests,
            "reported": self._reported_requests,
            "estimated": self._estimated_requests,
            "series": [
                self._token_event_to_dict(event)
                for event in self._token_events
            ],
            "tps_series": tps_series,
        }

    # ── 决策 trace ────────────────────────────

    def report_decision(self, trace_event: DecisionTraceEvent):
        self._decision_traces.append(trace_event)
        self._push_event({
            "type": "decision_trace",
            "trace": {
                "operator_id": trace_event.operator_id,
                "chosen": trace_event.chosen,
                "temperature": trace_event.temperature,
                "raw_scores": trace_event.raw_scores,
                "probabilities": trace_event.probabilities,
                "top_signals": trace_event.top_signals,
                "timestamp": trace_event.timestamp,
            },
        })

    def recent_decision_traces(self, limit: int = 5) -> list[dict]:
        return [
            {
                "operator_id": t.operator_id,
                "chosen": t.chosen,
                "temperature": t.temperature,
                "raw_scores": t.raw_scores,
                "probabilities": t.probabilities,
                "top_signals": t.top_signals,
                "timestamp": t.timestamp,
            }
            for t in list(self._decision_traces)[-limit:]
        ]

    # ── 最近事件 ──────────────────────────────

    def recent_events(self, limit: int = 50) -> list[dict]:
        return list(self._event_store)[-limit:]

    def _push_event(self, event: dict):
        self._event_store.append(event)
        stale = []
        for q in self._event_subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(q)
        for q in stale:
            self._event_subscribers.remove(q)

    @staticmethod
    def _snapshot_to_dict(snap: OperatorSnapshot) -> dict:
        return {
            "id": snap.operator_id,
            "node": snap.current_node,
            "mbti": snap.mbti,
            "quests": snap.active_quests,
            "action": snap.last_action,
            "detail": snap.last_detail,
            "timestamp": snap.timestamp,
        }

    @staticmethod
    def _token_event_to_dict(event: TokenUsageEvent) -> dict:
        return {
            "t": event.timestamp,
            "operator_id": event.operator_id,
            "action": event.action,
            "tokens": event.tokens,
            "source": event.source,
            "timestamp": event.timestamp,
        }
