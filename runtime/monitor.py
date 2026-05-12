"""RuntimeMonitor — 在 AsyncOperator 和监控面板之间搭桥。

同事件循环内直接共享状态，无需线程安全快照。
Monitor 是 Runtime 的一等公民，不是外部观察者。
"""

import asyncio
import copy
import time
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
