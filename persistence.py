"""持久化层 —— data/ 目录：节点 .md 文件 + meta/ 拓扑。

格式对齐 `01-概念/持久化设计.md`。
"""

import json
import os
import time
import yaml
from pathlib import Path

from mgraph import MGraph, Node, Edge, binResponse, compress_stk, serialize_stk
from persona import Persona
from questnode import AnswerNode, QuestNode, AnswerTrace
from quest_board import QuestBoard
from operators import Operator
from tag_manager import TagManager

VERSION = "0.3"


# ── 公开 API ──────────────────────────────────────

def save_graph(graph: MGraph, board: QuestBoard,
               operators: dict[str, Operator],
               data_dir: str = "data",
               metadata: dict | None = None,
               tag_manager: TagManager | None = None) -> None:
    """全量保存到 data/ 目录。"""
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    human_dir = root / "human"
    operator_dir = root / "operator"
    meta_dir = root / "meta"
    human_dir.mkdir(parents=True, exist_ok=True)
    operator_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 分离人类原文与 Operator 产物 ──
    node_index = {}
    operator_artifacts = {}
    for node in graph.V:
        if not node.name:
            continue
        fm = _node_frontmatter(node)
        if _is_operator_node(node):
            node_index[node.name] = {
                "storage": "operator",
                "frontmatter": fm,
            }
            operator_artifacts[node.name] = {
                "frontmatter": fm,
                "content": node.content or "",
            }
        else:
            node_index[node.name] = {
                "storage": "human",
                "content_ref": f"human/{node.name}.md",
                "frontmatter": fm,
            }
            _save_human_source_once(node, human_dir)

    # 节点索引连接图节点与真实内容存储。
    _write_meta(meta_dir, "nodes.json", {"nodes": node_index})
    _write_json_file(
        operator_dir / "artifacts.json",
        {"artifacts": operator_artifacts},
    )

    # ── 2. meta/edges.json ──
    _write_meta(meta_dir, "edges.json", {"edges": graph.serialize_edges()})

    # ── 3. meta/tags.json ──
    if tag_manager is None:
        tag_manager = TagManager()
        tag_manager.rebuild_from_graph(graph)
    _write_meta(meta_dir, "tags.json", tag_manager.to_dict())

    # ── 4. meta/quest_board.json ──
    _write_meta(meta_dir, "quest_board.json", board.to_dict())

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


def load_graph(data_dir: str = "data") -> tuple[MGraph, QuestBoard, dict[str, Operator], dict | None, TagManager]:
    """全量加载 data/ 目录。返回 (graph, board, operators, metadata, tag_manager)。"""
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
    nodes_data = _read_meta(meta_dir, "nodes.json")
    if nodes_data is not None:
        _load_indexed_nodes(root, nodes_data, graph, node_map,
                            pending_parent, pending_stk)
    else:
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
    graph.deserialize_edges(edges_data.get("edges", []), node_map)

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
    board = QuestBoard.from_dict(board_data, node_map)

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

    # ── 7. 加载标签索引 ──
    tags_data = _read_meta(meta_dir, "tags.json") or {}
    tag_manager = TagManager.from_dict(tags_data)

    # ── 8. 提取 metadata ──
    metadata = graph_meta.get("user_metadata")

    return graph, board, operators, metadata, tag_manager


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

def _is_operator_node(node: Node) -> bool:
    return isinstance(node, (QuestNode, AnswerNode))


def _node_frontmatter(node: Node) -> dict:
    fm = node.to_dict()
    fm["stk"] = compress_stk(serialize_stk(node.stk))
    return fm


def _save_human_source_once(node: Node, human_dir: Path) -> None:
    file_path = human_dir / f"{node.name}.md"
    if file_path.exists():
        return
    _write_text_file(file_path, _node_to_md(node))


def _write_text_file(file_path: Path, text: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(str(tmp_path), str(file_path))


def _write_json_file(file_path: Path, data: dict) -> None:
    _write_text_file(
        file_path,
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def _load_indexed_nodes(
    root: Path,
    nodes_data: dict,
    graph: MGraph,
    node_map: dict[str, Node],
    pending_parent: dict[str, str | None],
    pending_stk: dict[str, list[list]],
) -> None:
    artifacts = _read_json_file(root / "operator" / "artifacts.json").get(
        "artifacts",
        {},
    )
    for node_name, entry in nodes_data.get("nodes", {}).items():
        if entry.get("storage") == "operator":
            artifact = artifacts.get(node_name, {})
            fm = artifact.get("frontmatter") or entry.get("frontmatter") or {}
            body = artifact.get("content", "")
            node, parent_name, stk_raw = _dict_to_node(fm, body, graph)
        else:
            content_ref = entry.get("content_ref") or f"human/{node_name}.md"
            md_text = (root / content_ref).read_text(encoding="utf-8")
            _source_fm, body = _parse_frontmatter(md_text)
            fm = entry.get("frontmatter") or _source_fm
            node, parent_name, stk_raw = _dict_to_node(fm, body, graph)
        node_map[node.name] = node
        pending_parent[node.name] = parent_name
        if stk_raw:
            pending_stk[node.name] = stk_raw


def _dict_to_node(fm: dict, body: str, graph: MGraph) -> tuple[Node, str | None, list[list]]:
    parent_name = fm.get("parent")
    stk_raw = fm.get("stk", [])
    kind = fm.get("kind", "document")
    node_map = {
        "quest": QuestNode.from_dict,
        "answer": AnswerNode.from_dict,
    }
    factory = node_map.get(kind, Node.from_dict)
    node = factory(fm, body, graph)
    return node, parent_name, stk_raw


def _read_json_file(file_path: Path) -> dict:
    if not file_path.is_file():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    fm = node.to_dict()
    # stk 不在 to_dict（避免循环），额外补充
    fm["stk"] = compress_stk(serialize_stk(node.stk))

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
    parent_name = fm.get("parent")
    stk_raw = fm.get("stk", [])
    kind = fm.get("kind", "document")

    node_map = {
        "quest": QuestNode.from_dict,
        "answer": AnswerNode.from_dict,
    }
    factory = node_map.get(kind, Node.from_dict)
    node = factory(fm, body, graph)
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


def _find_edge(source: Node, target_name: str) -> Edge | None:
    """在 source.outlinks 中查找指向 target_name 的边。"""
    for link in source.outlinks:
        if link.target.name == target_name:
            return link
    return None
