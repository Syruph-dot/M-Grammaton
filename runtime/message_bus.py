"""消息总线 —— 基于 asyncio.Queue 的 Operator 间消息路由。"""

import asyncio
from typing import Any


class MessageBus:
    def __init__(self, operator_ids: list[str]):
        self._queues = {oid: asyncio.Queue() for oid in operator_ids}

    async def send(self, to: str, msg):
        await self._queues[to].put(msg)

    async def broadcast(self, msg):
        for q in self._queues.values():
            await q.put(msg)

    def drain(self, operator_id: str) -> list:
        q = self._queues[operator_id]
        msgs = []
        while not q.empty():
            msgs.append(q.get_nowait())
        return msgs