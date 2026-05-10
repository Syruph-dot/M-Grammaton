"""Phase 7: 持久化补齐 —— 全量 JSON 保存/加载。"""

import json
from mgraph import MGraph, Node, Edge, binResponse
from questnode import QuestNode, AnswerTrace
from quest_board import QuestBoard
from operators import Operator

VERSION = "0.2"


def save_state(path: str, graph: MGraph, board: QuestBoard,
               operators: dict[str, Operator]) -> None:
    """Save full system state to a JSON file."""
    data = {
        "version": VERSION,
        "nodes": [_serialize_node(n) for n in graph.V],
        "edges": [_serialize_edge(e) for e in graph.E],
        "quest_board": _serialize_board(board),
        "operators": _serialize_operators(operators),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state(path: str) -> tuple[MGraph, QuestBoard, dict[str, Operator]]:
    """Load full system state from a JSON file.

    Returns (graph, board, operators).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    graph = MGraph()

    # ── 1. 重建节点 ──────────────────────────────
    node_map = {}
    stk_pending: dict[str, list[dict]] = {}  # node_name → raw stk entries
    for ndata in data["nodes"]:
        node = _deserialize_node(ndata, graph)
        node_map[node.name] = node
        raw_stk = ndata.get("stk", [])
        if raw_stk:
            stk_pending[node.name] = raw_stk

    # ── 2. 重建父节点引用 ──────────────────────────
    for ndata in data["nodes"]:
        parent_name = ndata.get("parent")
        if parent_name:
            child = node_map[ndata["name"]]
            parent = node_map.get(parent_name)
            if parent is not None:
                parent.add_child(child)

    # ── 3. 重建边 ────────────────────────────────
    edge_map: dict[tuple[str, str], Edge] = {}
    for edata in data.get("edges", []):
        src = node_map[edata["source"]]
        tgt = node_map[edata["target"]]
        edge = src.link_to(tgt, edata["value"])
        edge_map[(src.name, tgt.name)] = edge

    # ── 4. 重建 stk（需要边已存在）──────────────────
    for node_name, raw_entries in stk_pending.items():
        node = node_map[node_name]
        for sdata in raw_entries:
            key = (sdata["source"], sdata["target"])
            edge = edge_map.get(key)
            if edge is not None:
                br = binResponse(sdata["reaction"], edge)
                br.weight = sdata.get("weight", edge.value)
                node.stk.append(br)

    # ── 5. 重建问答板 ─────────────────────────────
    board = QuestBoard()
    qb_data = data.get("quest_board", {"active": [], "completed": []})
    for qname in qb_data.get("active", []):
        qnode = node_map.get(qname)
        if isinstance(qnode, QuestNode):
            board.active.append(qnode)
    for qname in qb_data.get("completed", []):
        qnode = node_map.get(qname)
        if isinstance(qnode, QuestNode):
            board.completed.append(qnode)

    # ── 6. 重建 Operator ─────────────────────────
    operators: dict[str, Operator] = {}
    op_data = data.get("operators", {})
    for op_id, odata in op_data.items():
        op = Operator(op_id)
        current_node = node_map.get(odata.get("current"))
        if current_node is not None:
            op.bind(current_node)
        for qname in odata.get("submitted_quests", []):
            qnode = node_map.get(qname)
            if isinstance(qnode, QuestNode):
                op.submitted_quests.append(qnode)
        operators[op_id] = op

    return graph, board, operators


# ── 序列化辅助 ─────────────────────────────────────


def _serialize_node(node: Node) -> dict:
    """Node → dict（含 QuestNode 扩展字段）。"""
    data = {
        "name": node.name,
        "kind": node.kind,
        "content": node.content,
        "title": getattr(node, "title", node.name),
        "tags": sorted(node.tags) if node.tags else [],
        "parent": node.parent.name if node.parent else None,
        "metadata": getattr(node, "metadata", {}),
        "t_read": node.t_read,
        "t_write": node.t_write,
        "t_lp": node.t_lp,
        "stk": [_serialize_stk(br) for br in node.stk],
    }

    if isinstance(node, QuestNode):
        traces = []
        for trace in node.answer_traces:
            if trace is not None:
                traces.append({
                    "quest_name": trace.quest_name,
                    "answer_index": trace.answer_index,
                    "answerer_id": trace.answerer_id,
                    "node_names": trace.node_names,
                    "edge_refs": trace.edge_refs,
                    "score": trace.score,
                    "feedback_applied": trace.feedback_applied,
                })
            else:
                traces.append(None)

        data["quest_data"] = {
            "quester_id": node.quester_id,
            "answers": node.answers,
            "from_ids": node.from_ids,
            "scores": node.scores,
            "answer_traces": traces,
        }

    return data


def _serialize_edge(edge: Edge) -> dict:
    return {
        "source": edge.source.name,
        "target": edge.target.name,
        "value": edge.value,
    }


def _serialize_stk(br: binResponse) -> dict:
    return {
        "reaction": br.reaction,
        "source": br.target.source.name,
        "target": br.target.target.name,
        "weight": br.weight,
    }


def _serialize_board(board: QuestBoard) -> dict:
    return {
        "active": [q.name for q in board.active],
        "completed": [q.name for q in board.completed],
    }


def _serialize_operators(
    operators: dict[str, Operator],
) -> dict:
    result = {}
    for op_id, op in operators.items():
        cur = None
        try:
            cur = op.current.get().name
        except ReferenceError:
            pass
        result[op_id] = {
            "current": cur,
            "submitted_quests": [q.name for q in op.submitted_quests],
        }
    return result


# ── 反序列化辅助 ───────────────────────────────────


def _deserialize_node(ndata: dict, graph: MGraph) -> Node | QuestNode:
    """dict → Node/QuestNode 并加入 graph。"""
    quest_data = ndata.pop("quest_data", None)

    if quest_data is not None:
        node = QuestNode(
            name=ndata["name"],
            quester_id=quest_data["quester_id"],
            content=ndata.get("content", ""),
        )

        answers = quest_data.get("answers", [])
        from_ids = quest_data.get("from_ids", [])
        raw_scores = quest_data.get("scores", [])
        raw_traces = quest_data.get("answer_traces", [])

        node.answers = list(answers)
        node.from_ids = list(from_ids)
        node.scores = [
            None if s is None else tuple(s) for s in raw_scores
        ]

        for rt in raw_traces:
            if rt is not None:
                trace = AnswerTrace(
                    quest_name=rt["quest_name"],
                    answer_index=rt["answer_index"],
                    answerer_id=rt["answerer_id"],
                    node_names=list(rt.get("node_names", [])),
                    edge_refs=[tuple(p) for p in rt.get("edge_refs", [])],
                    score=rt.get("score"),
                    feedback_applied=rt.get("feedback_applied", False),
                )
                node.answer_traces.append(trace)
            else:
                node.answer_traces.append(None)

        # 对齐长度（补全 None 占位直到与 answers 一致）
        while len(node.answer_traces) < len(node.answers):
            node.answer_traces.append(None)
        while len(node.scores) < len(node.answers):
            node.scores.append(None)
        while len(node.from_ids) < len(node.answers):
            node.from_ids.append(None)
    else:
        node = Node(
            name=ndata["name"],
            kind=ndata.get("kind", "document"),
            content=ndata.get("content", ""),
            tags=ndata.get("tags", []),
            metadata=ndata.get("metadata", {}),
        )

    # 公共 Node 字段
    node.title = ndata.get("title", node.name)
    node.t_read = ndata.get("t_read", 0.0)
    node.t_write = ndata.get("t_write", 0.0)
    node.t_lp = ndata.get("t_lp", 0.0)

    graph.add_node(node)
    return node
