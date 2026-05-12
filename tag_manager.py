"""标签管理器 —— 轻量本体层：标签 CRUD、别名、概念关联、节点映射。

标签是"一等实体"——可独立创建、重命名、删除，不受节点生命周期约束。
Node.tags 仍是节点侧来源，但 TagManager 维护标签的完整元数据。
"""

from __future__ import annotations

from mgraph import MGraph


class TagManager:
    """维护标签 ↔ 节点映射、别名系统、概念关联。

    用法
    ----
    mgr = TagManager()
    mgr.add_tag("认识论", aliases=["epistemology"])
    mgr.link_node("认识论", "node_01")
    mgr.add_conc_tag("认识论", "哲学", weight=3)
    """

    def __init__(self):
        # tag_name -> set of node_names
        self._tag_to_nodes: dict[str, set[str]] = {}
        # primary_tag -> set of alias names
        self._aliases: dict[str, set[str]] = {}
        # primary_tag -> {related_tag: weight}
        self._conc_tags: dict[str, dict[str, int]] = {}

    # ── 标签 CRUD ─────────────────────────────────

    def add_tag(self, name: str, aliases: list[str] | None = None) -> bool:
        """添加标签。返回 False 表示标签已存在（不做任何事）。"""
        if not name:
            raise ValueError("tag name cannot be empty")
        if name in self._tag_to_nodes:
            return False
        self._tag_to_nodes[name] = set()
        self._aliases[name] = set()
        self._conc_tags[name] = {}
        if aliases:
            for alias in aliases:
                if alias and alias != name:
                    self._aliases[name].add(alias)
        return True

    def remove_tag(self, name: str) -> bool:
        """删除标签及其所有别名和概念关联。"""
        if name not in self._tag_to_nodes:
            return False
        # 从其他标签的概念关联中移除
        for other in list(self._conc_tags.keys()):
            self._conc_tags[other].pop(name, None)
        del self._tag_to_nodes[name]
        self._aliases.pop(name, None)
        self._conc_tags.pop(name, None)
        return True

    def rename_tag(self, old_name: str, new_name: str) -> bool:
        """重命名标签，保留所有关联。"""
        if old_name not in self._tag_to_nodes or new_name in self._tag_to_nodes:
            return False
        self._tag_to_nodes[new_name] = self._tag_to_nodes.pop(old_name)
        self._aliases[new_name] = self._aliases.pop(old_name)
        self._conc_tags[new_name] = self._conc_tags.pop(old_name)
        # 更新其他标签的概念关联
        for other in self._conc_tags:
            if old_name in self._conc_tags[other]:
                self._conc_tags[other][new_name] = self._conc_tags[other].pop(old_name)
        return True

    def tag_exists(self, name: str) -> bool:
        """检查标签是否存在（含别名解析）。"""
        return self._resolve(name) is not None

    def get_all_tags(self) -> list[dict]:
        """获取所有标签的完整信息列表，用于 UI 展示。"""
        result = []
        for name in sorted(self._tag_to_nodes.keys()):
            result.append({
                "name": name,
                "nodes": len(self._tag_to_nodes[name]),
                "node_list": sorted(self._tag_to_nodes[name]),
                "aliases": ", ".join(sorted(self._aliases[name])) or "",
                "conc_tags": ", ".join(
                    f"{t}({w})" for t, w in
                    sorted(self._conc_tags[name].items(), key=lambda x: -x[1])
                ) or "",
            })
        return result

    # ── 别名 ──────────────────────────────────────

    def add_alias(self, tag_name: str, alias: str) -> bool:
        """给标签添加别名。"""
        primary = self._resolve(tag_name)
        if primary is None or not alias or alias == primary:
            return False
        self._aliases[primary].add(alias)
        return True

    def remove_alias(self, tag_name: str, alias: str) -> bool:
        """移除标签的某个别名。"""
        primary = self._resolve(tag_name)
        if primary is None:
            return False
        self._aliases[primary].discard(alias)
        return True

    def get_aliases(self, tag_name: str) -> set[str]:
        """获取标签所有别名。"""
        primary = self._resolve(tag_name)
        if primary is None:
            return set()
        return self._aliases[primary].copy()

    def _resolve(self, name: str) -> str | None:
        """别名解析：返回对应的主标签名，不存在返回 None。"""
        if name in self._tag_to_nodes:
            return name
        for primary, aliases in self._aliases.items():
            if name in aliases:
                return primary
        return None

    # ── 节点-标签关联 ────────────────────────────

    def link_node(self, tag_name: str, node_name: str) -> bool:
        """将节点链接到标签。"""
        primary = self._resolve(tag_name)
        if primary is None:
            return False
        self._tag_to_nodes[primary].add(node_name)
        return True

    def unlink_node(self, tag_name: str, node_name: str) -> bool:
        """解除节点与标签的链接。"""
        primary = self._resolve(tag_name)
        if primary is None:
            return False
        self._tag_to_nodes[primary].discard(node_name)
        return True

    def get_nodes_for_tag(self, tag_name: str) -> list[str]:
        """获取某标签关联的所有节点名（含别名解析）。"""
        primary = self._resolve(tag_name)
        if primary is None:
            return []
        return sorted(self._tag_to_nodes[primary])

    def get_node_tags(self, node_name: str) -> list[str]:
        """获取某节点关联的所有标签名。"""
        return sorted(
            t for t, nodes in self._tag_to_nodes.items()
            if node_name in nodes
        )

    # ── 概念关联（标签⇄标签） ─────────────────────

    def add_conc_tag(self, tag_a: str, tag_b: str, weight: int = 1) -> bool:
        """在两个标签之间建立概念关联（双向）。"""
        pa = self._resolve(tag_a)
        pb = self._resolve(tag_b)
        if pa is None or pb is None or pa == pb:
            return False
        self._conc_tags[pa][pb] = weight
        self._conc_tags[pb][pa] = weight
        return True

    def remove_conc_tag(self, tag_a: str, tag_b: str) -> bool:
        """移除标签间的概念关联。"""
        pa = self._resolve(tag_a)
        pb = self._resolve(tag_b)
        if pa is None or pb is None:
            return False
        self._conc_tags[pa].pop(pb, None)
        self._conc_tags[pb].pop(pa, None)
        return True

    def get_conc_tags(self, tag_name: str) -> dict[str, int]:
        """获取某标签关联的所有概念标签及权重。"""
        primary = self._resolve(tag_name)
        if primary is None:
            return {}
        return dict(self._conc_tags[primary])

    def get_all_conc_edges(self) -> list[dict]:
        """获取所有概念关联边，供 D3 力导向图渲染。

        每条边格式: {"source": name, "target": name, "weight": int}
        返回无重复边（A↔B 只含一条）。
        """
        seen: set[tuple[str, str]] = set()
        edges = []
        for tag, related in self._conc_tags.items():
            for other, weight in related.items():
                key = tuple(sorted((tag, other)))
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": tag, "target": other, "weight": weight})
        return edges

    # ── 扫描图重建 ──────────────────────────────

    def rebuild_from_graph(self, graph: MGraph) -> None:
        """扫描图中所有 Node.tags，重建 TagManager 节点映射。

        注意：此操作只更新节点映射，不影响标签本身（别名、概念关联保留）。
        """
        for tag_name in self._tag_to_nodes:
            self._tag_to_nodes[tag_name] = set()

        for node in graph.V:
            for tag in node.tags:
                self.add_tag(tag)
                self.link_node(tag, node.name)

    # ── 统计 ──────────────────────────────────────

    @property
    def all_tags(self) -> list[str]:
        return sorted(self._tag_to_nodes)

    @property
    def tag_counts(self) -> dict[str, int]:
        return {tag: len(nodes) for tag, nodes in sorted(self._tag_to_nodes.items())}

    @property
    def total_tag_entries(self) -> int:
        return sum(len(nodes) for nodes in self._tag_to_nodes.values())

    # ── 序列化 ─────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为 JSON 可序列化的 entry-list 格式。"""
        tags_list = []
        for name in sorted(self._tag_to_nodes.keys()):
            entry: dict = {
                "name": name,
                "outlinks": sorted(self._tag_to_nodes[name]),
            }
            if self._aliases[name]:
                entry["aliases"] = sorted(self._aliases[name])
            if self._conc_tags[name]:
                entry["conc_tags"] = dict(self._conc_tags[name])
            tags_list.append(entry)
        return {"tags": tags_list}

    @classmethod
    def from_dict(cls, data: dict) -> "TagManager":
        """从 entry-list 格式反序列化。"""
        mgr = cls()
        for entry in data.get("tags", []):
            name = entry.get("name", "")
            if not name:
                continue
            mgr._tag_to_nodes[name] = set(entry.get("outlinks", []))
            mgr._aliases[name] = set(entry.get("aliases", []))
            mgr._conc_tags[name] = dict(entry.get("conc_tags", {}))
        return mgr
