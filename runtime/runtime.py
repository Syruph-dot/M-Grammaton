"""异步 Operator Runtime —— 调度器 / 生命周期管理 / CLI 入口。"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from async_llm_client import AsyncLLMClient
from config import Config
from mgraph import MGraph, Node
from quest_board import QuestBoard
from questnode import AnswerNode, QuestNode

from runtime.async_operator import AsyncOperator
from runtime.decision import RandomDecider
from runtime.message_bus import MessageBus
from runtime.messages import ClockTick
from runtime.monitor import RuntimeMonitor

logger = logging.getLogger(__name__)

DEFAULT_OPERATOR_NAMES = ["Alice", "Bob", "Carol"]


class OperatorRuntime:
    STK_DECAY_TICKS = 4  # stk >= 100% 后等 N 个 tick 再重检确认

    def __init__(self, data_dir: str, model: str, operator_names: list[str] | None = None):
        self.running = False
        self.round = 0
        self._stk_decay_counter = 0

        self.config = Config()
        self.config.model = model
        if not self.config.validate():
            logger.warning("未配置 API Key，Operator 将使用降级模式（无 LLM 调用）")

        self.llm_client = AsyncLLMClient(self.config) if self.config.api_key else None

        self.graph = self._init_graph(data_dir)
        self.board = QuestBoard()

        operator_names = operator_names or DEFAULT_OPERATOR_NAMES
        self.bus = MessageBus(operator_names)

        self.operators: dict[str, AsyncOperator] = {}
        content_nodes = [
            n for n in self.graph.V
            if not isinstance(n, (QuestNode, AnswerNode))
        ]
        for name in operator_names:
            op = AsyncOperator(
                operator_id=name,
                runtime=self,
                decider=RandomDecider(),
                llm_client=self.llm_client,
            )
            if content_nodes:
                op.bind(content_nodes[0])
            self.operators[name] = op

    def _init_graph(self, data_dir: str) -> MGraph:
        from persistence import _md_to_node

        root = Path(data_dir)
        graph = MGraph()
        if not root.is_dir():
            logger.warning("data 目录不存在: %s，创建空图", data_dir)
            root.mkdir(parents=True, exist_ok=True)
            return graph

        md_files = sorted(root.glob("*.md"))
        if not md_files:
            logger.warning("data 目录无 .md 文件: %s，创建空图", data_dir)
            return graph

        node_map: dict[str, Node] = {}
        pending_parent: dict[str, str | None] = {}

        for md_file in md_files:
            try:
                md_text = md_file.read_text(encoding="utf-8")
                node, parent_name, _stk_raw = _md_to_node(md_text, graph)
                node_map[node.name] = node
                pending_parent[node.name] = parent_name
            except Exception:
                logger.exception("加载文件失败: %s", md_file)

        for node_name, parent_name in pending_parent.items():
            if parent_name and parent_name in node_map:
                child = node_map[node_name]
                parent = node_map[parent_name]
                parent.add_child(child)

        content_nodes = [n for n in graph.V if not isinstance(n, (QuestNode, AnswerNode))]
        for u in content_nodes:
            for v in content_nodes:
                if u is not v and v.name not in [e.target.name for e in u.outlinks]:
                    u.link_to(v, 1.0)

        graph.force_normalize()
        logger.info("图加载完成: %d 节点, %d 边", len(graph.V), len(graph.E))
        return graph

    async def start(self):
        self.running = True
        logger.info(
            "[Runtime] 启动 — %d Operators: %s",
            len(self.operators),
            ", ".join(self.operators.keys()),
        )

        tasks = [op.run() for op in self.operators.values()]
        tasks.append(self._clock())
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("[Runtime] 所有任务被取消")

    async def shutdown(self, sig=None):
        logger.info("[Runtime] 正在关闭...")
        self.running = False
        if self.llm_client is not None:
            await self.llm_client.close()
        logger.info("[Runtime] 所有 Operator 已停止")

    async def broadcast(self, msg):
        await self.bus.broadcast(msg)

    async def _clock(self):
        while self.running:
            await asyncio.sleep(5.0)
            self.round += 1
            await self.bus.broadcast(ClockTick(round=self.round))
            logger.debug("[Clock] tick round=%d", self.round)
            await self._check_stk_decay()

    async def _check_stk_decay(self):
        """延迟重检 stk 栈满载情况。每 tick 调用一次。"""
        if not self.graph.V:
            self._stk_decay_counter = 0
            return

        ratio = len(self.graph.stk) / len(self.graph.V)

        if ratio < 1.0:
            self._stk_decay_counter = 0
            return

        # ratio >= 1.0 —— stk 栈满了
        if self._stk_decay_counter == 0:
            self._stk_decay_counter = self.STK_DECAY_TICKS
            logger.info("[Decay] stk 满载 (%.1f%%), %d tick 后重检",
                        ratio * 100, self.STK_DECAY_TICKS)
            return

        self._stk_decay_counter -= 1

        if self._stk_decay_counter > 0:
            return

        # 倒计时归零，执行最终判定
        ratio = len(self.graph.stk) / len(self.graph.V)
        if ratio >= 1.0:
            removed = self.graph.decay_stk()
            logger.info("[Decay] 触发腐烂: 移除 %d 条 stk 条目", removed)
        else:
            logger.debug("[Decay] 重检时 stk 已回落 (%.1f%%), 跳过", ratio * 100)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    import argparse

    parser = argparse.ArgumentParser(description="M-Grammaton Async Runtime")
    parser.add_argument("--data-dir", default="data", help="知识图谱数据目录")
    parser.add_argument("--model", default="deepseek-chat", help="LLM 模型名称")
    parser.add_argument("--operators", nargs="+", default=DEFAULT_OPERATOR_NAMES, help="Operator 名称列表")
    parser.add_argument("--timeout", type=int, default=60, help="运行时间（秒），0=无限")
    parser.add_argument("--web", action="store_true", help="启动 FastAPI 监控面板")
    parser.add_argument("--port", type=int, default=8763, help="监控面板端口")
    args = parser.parse_args()

    monitor = RuntimeMonitor()
    runtime = OperatorRuntime(
        data_dir=args.data_dir,
        model=args.model,
        operator_names=args.operators,
    )
    runtime.monitor = monitor

    # 预填充 monitor 初始状态
    for op_id, op in runtime.operators.items():
        monitor.update_mbti(op_id, str(op.persona.mbti))
        if op.current:
            node = op.current.get()
            monitor.update_node(op_id, node.name if node else "")

    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("[Runtime] 收到关闭信号")
        shutdown_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    else:
        logger.info("Windows 平台：按 Ctrl+C 关闭")

    runtime_task = asyncio.create_task(runtime.start())

    server_task = None
    if args.web:
        from runtime.server import run_server

        logger.info("[Runtime] 启动监控面板 → http://127.0.0.1:%d", args.port)
        server_task = asyncio.create_task(run_server(monitor, port=args.port))

    timeout_task = None
    if args.timeout > 0:
        async def _timeout_waiter():
            await asyncio.sleep(args.timeout)
            logger.info("[Runtime] 达到超时时间 %d 秒", args.timeout)
            shutdown_event.set()
        timeout_task = asyncio.create_task(_timeout_waiter())

    try:
        await shutdown_event.wait()
    except KeyboardInterrupt:
        logger.info("[Runtime] 收到 KeyboardInterrupt")
    finally:
        await runtime.shutdown()
        runtime_task.cancel()
        try:
            await runtime_task
        except asyncio.CancelledError:
            pass
        if server_task is not None:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
        if timeout_task is not None:
            timeout_task.cancel()

    logger.info("[Runtime] 退出")


if __name__ == "__main__":
    asyncio.run(main())