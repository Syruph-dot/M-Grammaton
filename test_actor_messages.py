"""测试 Actor Message 两层协议 + send/reply。"""

import asyncio
import time

from mgraph import MGraph, Node
from quest_board import QuestBoard
from runtime.async_operator import AsyncOperator
from runtime.actor_panel import ActorPanel
from runtime.decision import RandomDecider
from runtime.message_bus import MessageBus
from runtime.monitor import RuntimeMonitor
from runtime.search_service import FakeSearchService


def _make_graph():
    graph = MGraph()
    src = Node("source", content="消息测试节点", mg=graph)
    tgt = Node("target", content="目标节点", mg=graph)
    src.link_to(tgt, 1.0)
    return graph


def _make_operator(op_id="Alice", graph=None, message_router=None):
    graph = graph or _make_graph()
    board = QuestBoard()
    bus = MessageBus([op_id])
    op = AsyncOperator(
        operator_id=op_id,
        graph=graph,
        board=board,
        bus=bus,
        running_ref=[True],
        decider=RandomDecider(),
        search_service=FakeSearchService(),
        message_router=message_router,
    )
    src = next(n for n in graph.V if n.name == "source")
    op.bind(src)
    return op, graph


class TestActorMessages:

    def test_send_message_creates_artifact(self):
        """send_message 创建 actor_message artifact 节点。"""
        router_calls = []

        def router(sender_id, body, msg_type="info", recipients=None, in_reply_to=""):
            router_calls.append((sender_id, body, msg_type, recipients))

        op, graph = _make_operator(message_router=router)
        asyncio.run(op._send_message())

        assert len(router_calls) == 1
        assert router_calls[0][0] == "Alice"
        assert router_calls[0][2] == "info"
        assert "user" in (router_calls[0][3] or [])

    def test_reply_to_message_marks_done(self):
        """回复后原消息标记为 done。"""
        op, graph = _make_operator()

        # 模拟收到一条消息
        op.panel.add_message("info", "你好 Alice",
                             {"sender": "user", "msg_id": "test_msg_1"})
        op.panel.select_message_next()

        router_calls = []

        def router(sender_id, body, msg_type="info", recipients=None, in_reply_to=""):
            router_calls.append(in_reply_to)

        op.message_router = router
        asyncio.run(op._reply_to_message())

        assert len(router_calls) == 1
        assert router_calls[0] == "test_msg_1"
        # 原消息已标记 done
        active = [m for m in op.panel.active_messages if m.status == "active"]
        assert len(active) == 0

    def test_actor_message_node_metadata(self):
        """路由创建的消息节点 metadata 符合协议。"""
        graph = _make_graph()
        board = QuestBoard()
        bus = MessageBus(["Alice"])

        router_calls = []

        def router(sender_id, body, msg_type="info", recipients=None, in_reply_to=""):
            router_calls.append(True)

        op = AsyncOperator(
            operator_id="Alice",
            graph=graph,
            board=board,
            bus=bus,
            running_ref=[True],
            decider=RandomDecider(),
            message_router=router,
        )

        from runtime.runtime import OperatorRuntime
        import types

        # 直接测试路由创建
        rt = types.SimpleNamespace(
            graph=graph,
            operators={"Alice": op},
            user_actor=types.SimpleNamespace(
                add_message=lambda t, s, p: None),
        )

        runtime = OperatorRuntime.__new__(OperatorRuntime)
        runtime.graph = graph
        runtime.operators = {"Alice": op}
        runtime.user_actor = type('UA', (), {
            'add_message': lambda self, t, s, p: None})()

        runtime._route_actor_message(
            sender_id="Bob",
            body="这是一条测试消息正文",
            msg_type="info",
            recipients=["Alice"],
        )

        # 验证 artifact 节点
        msgs = [n for n in graph.V
                if n.metadata.get("artifact_type") == "actor_message"]
        assert len(msgs) == 1
        msg_node = msgs[0]
        assert msg_node.metadata["sender"] == "Bob"
        assert msg_node.metadata["msg_type"] == "info"
        assert "Alice" in msg_node.metadata["recipients"]
        assert msg_node.content == "这是一条测试消息正文"

    def test_message_envelope_in_recipient_panel(self):
        """收件人的 panel 中有对应的 envelope。"""
        graph = _make_graph()
        op, _ = _make_operator(op_id="Alice", graph=graph)
        from runtime.runtime import OperatorRuntime

        # 模拟收件人 Bob
        bob, _ = _make_operator(op_id="Bob", graph=graph)

        runtime = OperatorRuntime.__new__(OperatorRuntime)
        runtime.graph = graph
        runtime.operators = {"Alice": op, "Bob": bob}
        runtime.user_actor = type('UA', (), {
            'add_message': lambda self, t, s, p: None})()

        runtime._route_actor_message(
            sender_id="Alice",
            body="Bob 请查阅",
            msg_type="info",
            recipients=["Bob"],
        )

        assert len(bob.panel.active_messages) == 1
        env = bob.panel.active_messages[0]
        assert env.payload.get("sender") == "Alice"
        assert env.type == "info"

    def test_message_context_formatting(self):
        """format_messages_for_context 返回期望格式。"""
        op, _ = _make_operator()
        op.panel.add_message("info", "测试消息1", {"sender": "user"})
        op.panel.add_message("alert", "测试消息2", {"sender": "Bob"})

        ctx = op.panel.format_messages_for_context()
        assert "待处理消息" in ctx
        assert "测试消息1" in ctx
        assert "测试消息2" in ctx

    def test_empty_message_context(self):
        op, _ = _make_operator()
        ctx = op.panel.format_messages_for_context()
        assert ctx == ""

    def test_operator_send_to_user_via_router(self):
        """_send_message 调用 router 时 recipients 含 user。"""
        router_calls = []

        def router(sender_id, body, msg_type="info", recipients=None, in_reply_to=""):
            router_calls.append((recipients, body))

        op, graph = _make_operator(message_router=router)
        asyncio.run(op._send_message())

        assert len(router_calls) == 1
        recipients, body = router_calls[0]
        assert "user" in (recipients or [])
        assert len(body) > 0

    def test_reply_without_active_message_returns(self):
        """无 active message 时 reply 安全返回。"""
        op, _ = _make_operator()
        asyncio.run(op._reply_to_message())
        # 不应崩溃
