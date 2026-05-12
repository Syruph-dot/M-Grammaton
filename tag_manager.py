"""标签管理器 —— 全局 tag ↔ node 关联索引。"""

from mgraph import MGraph


class TagManager:
    """维护标签到节点集合的映射，提供聚合统计和重建功能。"""

    def __init__(self):
        self._tag_nodes: dict[str, set[str]] = {}

    def add_tag(self, node_name: str, tag: str):
        if tag not in self._tag_nodes:
            self._tag_nodes[tag] = set()
        self._tag_nodes[tag].add(node_name)

    def remove_tag(self, node_name: str, tag: str):
        s = self._tag_nodes.get(tag)
        if s is None:
            return
        s.discard(node_name)
        if not s:
            del self._tag_nodes[tag]

    def get_node_tags(self, node_name: str) -> list[str]:
        return sorted(t for t, nodes in self._tag_nodes.items() if node_name in nodes)

    def get_tag_nodes(self, tag: str) -> set[str]:
        return set(self._tag_nodes.get(tag, set()))

    @property
    def all_tags(self) -> list[str]:
        return sorted(self._tag_nodes)

    @property
    def tag_counts(self) -> dict[str, int]:
        return {tag: len(nodes) for tag, nodes in sorted(self._tag_nodes.items())}

    @property
    def total_tag_entries(self) -> int:
        return sum(len(nodes) for nodes in self._tag_nodes.values())

    def rebuild_from_graph(self, graph: MGraph):
        self._tag_nodes.clear()
        for node in graph.V:
            for tag in node.tags:
                self.add_tag(node.name, tag)

    def to_dict(self) -> dict[str, list[str]]:
        return {tag: sorted(nodes) for tag, nodes in self._tag_nodes.items()}

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> "TagManager":
        tm = cls()
        for tag, nodes in data.items():
            tm._tag_nodes[tag] = set(nodes)
        return tm
