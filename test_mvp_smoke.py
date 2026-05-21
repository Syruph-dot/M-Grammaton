#!/usr/bin/env python3
"""MVP 端到端验收脚本 (OPANEL-MVP-008)。

启动短时 runtime → 验证 Actor Panel 完整路径。

用法:
  python test_mvp_smoke.py               # 短时运行（5 秒）
  python test_mvp_smoke.py --duration 10  # 自定义运行秒数
  python test_mvp_smoke.py --verbose      # 详细日志

依赖: pip install httpx
"""

import argparse
import asyncio
import logging
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

# ensure project root
_PROJ_ROOT = Path(__file__).resolve().parent
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from mgraph import MGraph, Node
from runtime.runtime import OperatorRuntime
from runtime.monitor import RuntimeMonitor


logger = logging.getLogger("mvp_smoke")
pass_count = 0
fail_count = 0


def check(label: str, condition: bool, detail: str = ""):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        logger.info("  ✅ %s", label)
    else:
        fail_count += 1
        logger.error("  ❌ %s — %s", label, detail)


async def run_smoke(data_dir: str, duration: int, verbose: bool):
    global pass_count, fail_count
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    logger.info("=" * 60)
    logger.info("M-Grammaton Actor Panel MVP — 验收脚本")
    logger.info("=" * 60)

    # ── Bootstrap ─────────────────────────────────────
    logger.info("\n[1/5] 启动 Runtime…")
    monitor = RuntimeMonitor()
    runtime = OperatorRuntime(
        data_dir=data_dir,
        model="deepseek-chat",
        operator_names=["Alice", "Bob"],
        monitor=monitor,
    )
    # pre-fill monitor
    for op_id, op in runtime.operators.items():
        monitor.update_mbti(op_id, str(op.persona.mbti))
        if op.current:
            node = op.current.get()
            monitor.update_node(op_id, node.name if node else "")

    runtime_task = asyncio.create_task(runtime.start())
    await asyncio.sleep(2.0)  # let runtime boot

    # ── 1. Runtime 和图 ───────────────────────────────
    logger.info("\n[2/5] 验证 Runtime 就绪和图状态…")
    check("Runtime 正在运行", runtime.running)
    check("图非空", len(runtime.graph.V) > 0)
    check("至少一个 Operator", len(runtime.operators) >= 1)

    # 找一个文档节点
    doc_nodes = [n for n in runtime.graph.V if n.kind == "document"]
    check("有文档节点", len(doc_nodes) > 0)
    doc = doc_nodes[0] if doc_nodes else None

    # ── 2. Actor 列表和 panel ─────────────────────────
    logger.info("\n[3/5] 验证 Actor Panel 协议…")
    from runtime.server import _actor_list
    actors = _actor_list(runtime.user_actor, monitor)
    actor_ids = {a["id"] for a in actors}
    check("User Actor 在列表中", "user" in actor_ids)
    check("Operator 在列表中", len(actor_ids - {"user"}) >= 1)
    check("至少 2 个 actor", len(actors) >= 2)

    # User Actor panel
    if doc:
        runtime.user_actor.bind(doc)
    state = runtime.user_actor.build_panel_state(runtime.graph)
    check("User panel 有 actor_id", bool(state.actor_id))
    check("User panel 有 current_node", bool(state.current_node))
    check("User panel 有 out_edges 列表", isinstance(state.out_edges, list))
    check("User panel 有 in_edges 列表", isinstance(state.in_edges, list))
    check("is_readonly 标记存在", isinstance(state.is_readonly, bool))

    # Operator panel
    for snap in monitor.snapshot().values():
        from runtime.actor_panel import build_operator_panel_state
        op_state = build_operator_panel_state(
            operator_id=snap.operator_id,
            current_node_name=snap.current_node,
            graph=runtime.graph,
        )
        check(f"Operator {snap.operator_id} panel 有 actor_id",
              op_state.actor_id == snap.operator_id)
        break

    # ── 3. Cursor 命令 ────────────────────────────────
    logger.info("\n[4/5] 验证 Cursor / Stash / Message / Note 命令…")

    # random_reset_cursor
    if runtime.graph.V:
        ok, detail = runtime.user_actor.random_reset_cursor(runtime.graph)
        check(f"random_reset_cursor 成功: {detail}", ok)

    # select_out_edge / nav
    try:
        node = runtime.user_actor.current.get()
        if node.outlinks:
            ok = runtime.user_actor.select_out_edge(node.outlinks[0].target.name)
            check("select_out_edge 选中出边", ok)
            ok, detail = runtime.user_actor.nav_selected_edge(runtime.graph)
            check(f"nav_selected_edge 移动 cursor: {detail}", ok)
    except ReferenceError:
        check("cursor 导航", False, "current node 不存在")

    # stash
    if doc:
        ok = runtime.user_actor.add_to_stash(doc, reason="验收测试")
        check("add_to_stash 成功", ok)
        state = runtime.user_actor.build_panel_state(runtime.graph)
        stash_ids = [s["node_id"] for s in state.stash]
        check(f"stash 包含 {doc.name}", doc.name in stash_ids)
        ok = runtime.user_actor.remove_from_stash(doc.name)
        check("remove_from_stash 成功", ok)

    # message queue
    msg_id = runtime.user_actor.add_message("test", "验收消息")
    check("add_message 成功", msg_id.startswith("msg_"))
    ok = runtime.user_actor.select_message_next()
    check("select_message_next 成功", ok)
    ok = runtime.user_actor.set_message_done()
    check("set_message_done 成功", ok)
    msg_id2 = runtime.user_actor.add_message("test2", "待删除")
    runtime.user_actor.selected_message = msg_id2
    ok = runtime.user_actor.delete_message()
    check("delete_message 成功", ok)

    # note commit
    if doc:
        runtime.user_actor.bind(doc)
        before = {n.name for n in runtime.graph.V}
        ok, note_id = runtime.user_actor.commit_note("验收笔记内容", runtime.graph)
        check("commit_note 成功", ok)
        after = {n.name for n in runtime.graph.V}
        new_nodes = after - before
        check(f"note artifact {note_id} 在图中", note_id in new_nodes)
        if note_id in new_nodes:
            artifact = next(n for n in runtime.graph.V if n.name == note_id)
            check("artifact kind=note", artifact.kind == "note")
            check("artifact 内容正确", "验收笔记内容" in artifact.content)
            check("artifact 不是 document → 不入 human/",
                  artifact.kind != "document")

    # ── 4. API 端点 ──────────────────────────────────
    logger.info("\n[5/5] 验证 API 端点…")
    import runtime.server as srv
    srv.runtime_ref = runtime
    srv.monitor = monitor
    srv.user_actor_ref = runtime.user_actor

    actors_resp = await srv.list_actors()
    check("GET /api/actors 返回列表", "actors" in actors_resp)
    check("GET /api/actors count >= 2", actors_resp["count"] >= 2)

    user_panel = await srv.actor_panel("user")
    check("GET /api/actors/user/panel 就绪", user_panel["ready"] is True)
    check("panel actor_id=user", user_panel["panel"]["actor_id"] == "user")

    # operator panel
    for a in actors_resp["actors"]:
        if a["kind"] == "operator":
            op_panel = await srv.actor_panel(a["id"])
            check(f"GET /api/actors/{a['id']}/panel 就绪",
                  op_panel["ready"] is True)
            break

    # Human Source 不可被 artifact 改写
    human_md = Path(data_dir) / "human"
    if human_md.exists():
        for f in human_md.glob("*.md"):
            content = f.read_text(encoding="utf-8")
            check(f"human/ 不含 artifact: {f.name}",
                  "验收笔记内容" not in content)
    else:
        # 触发存盘以创建 human/ 目录
        runtime.tag_manager.rebuild_from_graph(runtime.graph)
        from persistence import save_graph
        save_graph(runtime.graph, runtime.board, runtime.operators,
                   data_dir=data_dir, tag_manager=runtime.tag_manager)
        if human_md.exists():
            for f in human_md.glob("*.md"):
                content = f.read_text(encoding="utf-8")
                check(f"存盘后 human/ 不含 artifact: {f.name}",
                      "验收笔记内容" not in content)

    # ── Cleanup ───────────────────────────────────────
    await runtime.shutdown()
    runtime_task.cancel()
    try:
        await runtime_task
    except (asyncio.CancelledError, Exception):
        pass

    # ── Summary ───────────────────────────────────────
    logger.info("\n" + "=" * 60)
    total = pass_count + fail_count
    logger.info("MVP 验收结果: %d / %d 通过 (%d 失败)",
                pass_count, total, fail_count)
    if fail_count == 0:
        logger.info("🎉 全部通过！")
    else:
        logger.error("❌ 存在失败项，请检查上述 ❌ 标记。")
    logger.info("=" * 60)
    return fail_count == 0


def main():
    parser = argparse.ArgumentParser(
        description="M-Grammaton Actor Panel MVP 验收脚本"
    )
    parser.add_argument("--duration", type=int, default=5,
                        help="Runtime 运行秒数（默认 5）")
    parser.add_argument("--data-dir", default=None,
                        help="数据目录（默认临时目录）")
    parser.add_argument("--verbose", action="store_true",
                        help="详细日志")
    parser.add_argument("--keep-data", action="store_true",
                        help="保留临时数据（调试用）")
    args = parser.parse_args()

    if args.data_dir:
        data_dir = args.data_dir
        temp_cleanup = None
    else:
        tmp = tempfile.mkdtemp(prefix="mvp_smoke_")
        data_dir = os.path.join(tmp, "data")
        os.makedirs(data_dir, exist_ok=True)
        # create a test .md file
        md_path = os.path.join(data_dir, "smoke_doc.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("---\nname: smoke_doc\nkind: document\ntitle: 验收材料\ntags: []\n---\n这是验收测试材料。")
        temp_cleanup = tmp

    success = asyncio.run(run_smoke(data_dir, args.duration, args.verbose))

    if temp_cleanup and not args.keep_data:
        import shutil
        shutil.rmtree(temp_cleanup, ignore_errors=True)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
