"""持久化层 —— data/ 目录：节点 .md 文件 + meta/ 拓扑。

格式对齐 `01-概念/持久化设计.md`。
"""

import json
import os
import time
import yaml
from pathlib import Path

from mgraph import MGraph, Node, Edge, binResponse
from persona import Persona
from questnode import AnswerNode, QuestNode, AnswerTrace
from quest_board import QuestBoard
from operators import Operator

VERSION = "0.3"


# ── 公开 API ──────────────────────────────────────

def save_graph(graph: MGraph, board: QuestBoard,
               operators: dict[str, Operator],
               data_dir: str = "data",
               metadata: dict | None = None) -> None:
    """全量保存到 data/ 目录。"""
    root = Path(data_dir)
    meta_dir = root / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 每个节点写 .md（原子写入） ──
    saved_names: set[str] = set()
    for node in graph.V:
        if not node.name:
            continue
        md_text = _node_to_md(node)
        file_path = root / f"{node.name}.md"
        tmp_path = root / f"{node.name}.md.tmp"
        tmp_path.write_text(md_text, encoding="utf-8")
        os.replace(str(tmp_path), str(file_path))
        saved_names.add(node.name)

    # 清理不再属于图的 .md 文件
    for existing in root.glob("*.md"):
        if existing.stem not in saved_names:
            try:
                existing.unlink()
            except OSError:
                pass

    # ── 2. meta/edges.json ──
    edges_data = _serialize_edges(graph)
    _write_meta(meta_dir, "edges.json", {"edges": edges_data})

    # ── 3. meta/tags.json（预留） ──
    _write_meta(meta_dir, "tags.json", {"tags": []})

    # ── 4. meta/quest_board.json ──
    _write_meta(meta_dir, "quest_board.json", {
        "active": [q.name for q in board.active],
        "completed": [q.name for q in board.completed],
    })

    # ── 5. meta/operators.json ──
    ops_data = {}
    for op_id, op in operators.items():
        cur = None
        try:
            cur = op.current.get().name
        except Exception:
            pass
        ops_data[op_id] = {
            "current_node": cur,
            "submitted_quests": [q.name for q in op.submitted_quests],
            "persona_mbti": op.persona.mbti if op.persona else None,
        }
    _write_meta(meta_dir, "operators.json", {"operators": ops_data})

    # ── 6. meta/graph.json（最后写入，作为保存完成信号） ──
    graph_meta = {
        "version": VERSION,
        "last_save": time.time(),
        "node_count": len(graph.V),
        "edge_count": len(graph.E),
        "operator_count": len(operators),
    }
    if metadata:
        graph_meta["user_metadata"] = metadata
    _write_meta(meta_dir, "graph.json", graph_meta)


def load_graph(data_dir: str = "data") -> tuple[MGraph, QuestBoard, dict[str, Operator], dict | None]:
    """全量加载 data/ 目录。返回 (graph, board, operators, metadata)。"""
    root = Path(data_dir)
    meta_dir = root / "meta"

    graph_meta = _read_meta(meta_dir, "graph.json")
    if graph_meta is None:
        raise FileNotFoundError(f"meta/graph.json 不存在，无法加载: {data_dir}")
    if graph_meta.get("version", "") != VERSION:
        raise ValueError(f"版本不匹配: 文件={graph_meta.get('version')}, 代码={VERSION}")

    graph = MGraph()
    node_map: dict[str, Node] = {}

    # ── 1. 加载所有节点 ──
    pending_parent: dict[str, str | None] = {}
    pending_stk: dict[str, list[list]] = {}
    for md_file in sorted(root.glob("*.md")):
        md_text = md_file.read_text(encoding="utf-8")
        node, parent_name, stk_raw = _md_to_node(md_text, graph)
        node_map[node.name] = node
        pending_parent[node.name] = parent_name
        if stk_raw:
            pending_stk[node.name] = stk_raw

    # ── 2. 重建父子关系 ──
    for node_name, parent_name in pending_parent.items():
        if parent_name and parent_name in node_map:
            child = node_map[node_name]
            parent = node_map[parent_name]
            parent.add_child(child)

    # ── 3. 加载边 ──
    edges_data = _read_meta(meta_dir, "edges.json") or {}
    _load_edges(edges_data.get("edges", []), node_map)

    # ── 4. 重建 stk ──
    for node_name, entries in pending_stk.items():
        node = node_map[node_name]
        for reaction, target_name in entries:
            # 查找 source→target 的边
            edge = _find_edge(node, target_name)
            if edge is not None:
                br = binResponse(bool(reaction), edge)
                node.stk.append(br)

    # ── 5. 加载问答板 ──
    board_data = _read_meta(meta_dir, "quest_board.json") or {}
    board = QuestBoard()
    for qname in board_data.get("active", []):
        qnode = node_map.get(qname)
        if isinstance(qnode, QuestNode):
            board.active.append(qnode)
    for qname in board_data.get("completed", []):
        qnode = node_map.get(qname)
        if isinstance(qnode, QuestNode):
            board.completed.append(qnode)

    # ── 6. 加载 Operators ──
    ops_data = _read_meta(meta_dir, "operators.json") or {}
    operators: dict[str, Operator] = {}
    for op_id, odata in ops_data.get("operators", {}).items():
        persona_mbti = odata.get("persona_mbti")
        persona = Persona(mbti=persona_mbti) if persona_mbti else None
        op = Operator(str(op_id), persona=persona)
        cur_name = odata.get("current_node")
        if cur_name and cur_name in node_map:
            op.bind(node_map[cur_name])
        for qname in odata.get("submitted_quests", []):
            qnode = node_map.get(qname)
            if isinstance(qnode, QuestNode):
                op.submitted_quests.append(qnode)
        operators[op_id] = op

    # ── 7. 提取 metadata ──
    metadata = graph_meta.get("user_metadata")

    return graph, board, operators, metadata


def save_node(node: Node, data_dir: str = "data") -> None:
    """单节点增量保存。"""
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)

    md_text = _node_to_md(node)
    file_path = root / f"{node.name}.md"
    tmp_path = root / f"{node.name}.md.tmp"
    tmp_path.write_text(md_text, encoding="utf-8")
    os.replace(str(tmp_path), str(file_path))


# ── 序列化辅助 ─────────────────────────────────────

def _write_meta(meta_dir: Path, filename: str, data: dict) -> None:
    """原子写入 meta 文件。"""
    file_path = meta_dir / filename
    tmp_path = meta_dir / f"{filename}.tmp"
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(str(tmp_path), str(file_path))


def _read_meta(meta_dir: Path, filename: str) -> dict | None:
    """读取 meta 文件，不存在时返回 None。"""
    file_path = meta_dir / filename
    if not file_path.is_file():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Node → Markdown ──────────────────────────────

def _node_to_md(node: Node) -> str:
    """Node → .md 字符串（YAML frontmatter + body）。"""
    fm = {
        "name": node.name,
        "kind": node.kind,
        "title": getattr(node, "title", node.name),
        "tags": sorted(node.tags) if node.tags else [],
        "t_read": node.t_read,
        "t_write": node.t_write,
        "t_lp": node.t_lp,
        "parent": node.parent.name if node.parent else None,
        "metadata": dict(getattr(node, "metadata", {})),
        "stk": _compress_stk(_serialize_stk_raw(node.stk)),
    }

    if isinstance(node, QuestNode):
        fm["kind"] = "quest"
        fm["quester_id"] = node.quester_id

    if isinstance(node, AnswerNode):
        fm["kind"] = "answer"
        fm["answerer_id"] = node.answerer_id
        fm["quest_name"] = node.quest_name
        fm["match_score"] = node.match_score
        fm["novelty_score"] = node.novelty_score
        fm["trace"] = _serialize_trace(node.trace) if node.trace else None

    yaml_str = yaml.safe_dump(fm, allow_unicode=True, default_flow_style=False,
                               sort_keys=False).strip()
    content = node.content or ""
    # 防止 body 以 --- 开头被误认为 frontmatter
    if content.lstrip().startswith("---"):
        content = "\n" + content

    return f"---\n{yaml_str}\n---\n\n{content}"


# ── Markdown → Node ──────────────────────────────

def _md_to_node(md_text: str, graph: MGraph) -> tuple[Node, str | None, list[list]]:
    """解析 .md → (node, parent_name, stk_raw)。node 已加入 graph。"""
    fm, body = _parse_frontmatter(md_text)
    name = fm.get("name", "")
    kind = fm.get("kind", "document")
    parent_name = fm.get("parent")
    stk_raw = fm.get("stk", [])

    if kind == "quest":
        node = QuestNode(
            name=name,
            quester_id=fm.get("quester_id", ""),
            content="",
        )
    elif kind == "answer":
        node = AnswerNode(
            name=name,
            answerer_id=fm.get("answerer_id", ""),
            quest_name=fm.get("quest_name", ""),
            content="",
        )
        node.match_score = fm.get("match_score")
        node.novelty_score = fm.get("novelty_score")
        node.trace = _deserialize_trace(fm.get("trace"))
    else:
        node = Node(name=name, kind=kind, content="")

    node.content = body.strip()
    node.title = fm.get("title", name)
    node.tags = set(fm.get("tags", []))
    node.t_read = float(fm.get("t_read", 0.0))
    node.t_write = float(fm.get("t_write", 0.0))
    node.t_lp = float(fm.get("t_lp", 0.0))
    node.metadata = fm.get("metadata", {})

    graph.add_node(node)
    return node, parent_name, stk_raw


def _parse_frontmatter(md_text: str) -> tuple[dict, str]:
    """从 .md 字符串解析 YAML frontmatter → (dict, body)。"""
    text = md_text.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1]) or {}
            body = parts[2]
            return fm, body
    return {}, text


# ── 边序列化 ──────────────────────────────────────

def _serialize_edges(graph: MGraph) -> list[dict]:
    result = []
    for e in graph.E:
        result.append({
            "s": e.source.name,
            "t": e.target.name,
            "v": e.value,
        })
    return result


def _load_edges(edges_data: list[dict], node_map: dict[str, Node]) -> None:
    """从边数据重建所有 Edge（通过 src.link_to 自动注册到图）。"""
    for edata in edges_data:
        src = node_map.get(edata["s"])
        tgt = node_map.get(edata["t"])
        if src is not None and tgt is not None:
            src.link_to(tgt, float(edata["v"]))


def _find_edge(source: Node, target_name: str) -> Edge | None:
    """在 source.outlinks 中查找指向 target_name 的边。"""
    for link in source.outlinks:
        if link.target.name == target_name:
            return link
    return None


# ── stk 序列化/压缩 ──────────────────────────────

def _serialize_stk_raw(stk: list[binResponse]) -> list[list]:
    """stk → [[reaction, target_name], ...] 原始列表。"""
    result = []
    for br in stk:
        result.append([br.reaction, br.target.target.name])
    return result


def _compress_stk(stk_data: list[list]) -> list[list]:
    """压缩 stk：相邻同符号只保留最近 20，总长超 100 截断尾部 50。"""
    if not stk_data:
        return []

    result = []
    run_start = stk_data[0][0]
    run = [stk_data[0]]
    for entry in stk_data[1:]:
        if entry[0] == run_start:
            run.append(entry)
        else:
            result.extend(run[-20:])
            run_start = entry[0]
            run = [entry]
    result.extend(run[-20:])

    if len(result) > 100:
        result = result[-50:]
    return result


# ── AnswerTrace 序列化 ────────────────────────────

def _serialize_trace(t: AnswerTrace) -> dict:
    return {
        "quest_name": t.quest_name,
        "answer_index": t.answer_index,
        "answerer_id": t.answerer_id,
        "node_names": t.node_names,
        "edge_refs": t.edge_refs,
        "score": t.score,
        "feedback_applied": t.feedback_applied,
    }


def _deserialize_trace(raw: dict | None) -> AnswerTrace | None:
    if raw is None:
        return None
    return AnswerTrace(
        quest_name=raw.get("quest_name", ""),
        answer_index=raw.get("answer_index", -1),
        answerer_id=raw.get("answerer_id", ""),
        node_names=raw.get("node_names", []),
        edge_refs=[tuple(p) for p in raw.get("edge_refs", [])],
        score=raw.get("score"),
        feedback_applied=raw.get("feedback_applied", False),
    )
