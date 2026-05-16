"""Operator 核心遍历与上下文构建 —— 同步/异步 Operator 共享。"""

import random
import string

from mgraph import Node, NodePtr


def read_path(start_node: Node, node_limit: int = 3):
    node_names: list[str] = [start_node.name]
    path_edges: list[tuple[str, str]] = []
    visited: list[Node] = [start_node]

    current = start_node
    for _ in range(node_limit - 1):
        nxt, edge = current.sample_l2()
        if edge is None:
            break
        path_edges.append((current.name, nxt.name))
        node_names.append(nxt.name)
        visited.append(nxt)
        current = nxt

    return node_names, path_edges, visited


def read_context(start_node: Node, node_limit: int = 3):
    """从 start_node 出发，沿 sample_l2 行走并记录阅读路径。

    返回:
        node_names: list[str]          — 访问过的节点名
        path_edges: list[tuple[str, str]] — (source, target) 边列表
        context_text: str              — 节点内容拼接（含临时标签【材料A/B/C…】）
    """
    context_parts: list[str] = []
    node_names, path_edges, visited = read_path(start_node, node_limit)

    for i, node in enumerate(visited):
        if node.content:
            tag = f"【材料{string.ascii_uppercase[i]}】" if i < 26 else f"【材料{i+1}】"
            context_parts.append(f"{tag}「{node.title}」：\n{node.content}")

    context_text = "\n\n---\n\n".join(context_parts)
    return node_names, path_edges, context_text


def navigate(ptr: NodePtr, target: Node, steps: int = 3) -> Node:
    """从 ptr 当前位置向 target 导航，沿途绑定 ptr，返回最终到达的节点。

    每走一步都更新 ptr，使 monitor 可见中间位置。
    """
    current = ptr.get()
    for _ in range(steps):
        if current is target:
            ptr.bind(target)
            return target
        for edge in current.outlinks:
            if edge.target is target:
                ptr.bind(target)
                return target
        nxt, _ = current.sample_l1()
        if nxt is current:
            break
        ptr.bind(nxt)
        current = nxt
    try:
        current.link_to(target, random.uniform(0.2, 0.5))
    except ValueError:
        pass
    ptr.bind(target)
    return target
