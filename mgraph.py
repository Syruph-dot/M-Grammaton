from dataclasses import dataclass, field
from heapq import heappop, heappush
from math import atan2, cos, sin
from time import time
from random import gauss, random
import weakref

class Edge:
    __slots__ = ("source", "target", "_value")

    def __init__(self, source, target, value: float = 0.0):
        self.source = source
        self.target = target
        self._value = float(value)

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, value: float):
        self._set_value(value)

    def set_raw_value(self, value: float):
        self._set_value(value)

    def _set_value(self, value: float):
        value = float(value)
        if value < 0:
            raise ValueError("weight value must be non-negative")
        self._value = value
    def __repr__(self):
        return f"edge({self.source} -> {self.target}, value={self.value})"


class Node:
    __slots__ = (
        "name",
        "kind",
        "content",
        "parent",
        "children",
        "tags",
        "title",
        "metadata",
        "outlinks",
        "inlinks",
        "t_read",
        "t_write",
        "t_lp",
        "stk",
        "_mg",
        "__weakref__",
    )

    def __init__(
        self,
        name: str,
        kind: str = "document",
        content: str = "",
        parent=None,
        tags=None,
        metadata=None,
        mg=None,
    ):
        if not name:
            raise ValueError("node name cannot be empty")
        self.name = str(name)
        self.kind = str(kind)
        self.content = content
        self.parent = None
        self.children = {}
        self.tags = set() if tags is None else set(tags)
        self.title = self.name
        self.metadata = {} if metadata is None else dict(metadata)
        self.outlinks = []
        self.inlinks = []
        self.t_read = 0.0
        self.t_write = 0.0
        self.t_lp = 0.0
        self.stk: list[binResponse] = []
        self._mg = None
        if parent is not None:
            parent.add_child(self)
        if mg is not None:
            mg.add_node(self)

    @property
    def mg(self):
        return self._mg

    def _bind_mg(self, graph):
        if self._mg is not None and self._mg is not graph:
            raise ValueError("node already belongs to another mg")
        self._mg = graph

    @property
    def path(self) -> str:
        parts = []
        seen = {}
        current = self
        while current is not None:
            marker = id(current)
            if marker in seen:
                cycle_start = seen[marker]
                cycle_forward = parts[cycle_start:] + [current.name]
                prefix = parts[:cycle_start]
                cycle_text = "[" + "/".join(reversed(cycle_forward)) + "]"
                if prefix:
                    return "/" + "/".join([cycle_text, *reversed(prefix)])
                return "/" + cycle_text
            seen[marker] = len(parts)
            parts.append(current.name)
            current = current.parent
        return "/" + "/".join(reversed(parts))

    @property
    def is_container(self) -> bool:
        return self.kind in {"directory", "folder", "collection"}

    def add_child(self, child):
        if child.name in self.children and self.children[child.name] is not child:
            raise ValueError(f"duplicate child name: {child.name}")
        if child.parent is not None and child.parent is not self:
            child.parent.remove_child(child.name)
        child.parent = self
        self.children[child.name] = child
        return child

    def remove_child(self, name: str):
        if name not in self.children:
            raise KeyError(f"child not found: {name}")
        child = self.children.pop(name)
        child.parent = None
        return child

    def link_to(self, target, value: float = 1.0):
        graph = self.mg
        if graph is None or target.mg is None:
            raise ValueError("both nodes must belong to the same mg")
        if target.mg is not graph:
            raise ValueError("both nodes must belong to the same mg")
        link = Edge(self, target, value)
        self.outlinks.append(link)
        target.inlinks.append(link)
        graph._register_edge(link)
        return link

    def unlink(self, link):
        if link not in self.outlinks:
            raise ValueError("link is not registered in outlinks")
        if link not in link.target.inlinks:
            raise ValueError("link target is not registered in inlinks")
        self.outlinks.remove(link)
        link.target.inlinks.remove(link)
        graph = self.mg
        if graph is not None:
            graph._unregister_edge(link)

    def access(self, mode: str, content=None, t_now: float | None = None):
        t_now = time() if t_now is None else float(t_now)
        if mode == "read":
            self.t_read = t_now
            self.t_lp = (self.t_lp + 2.0 * t_now) / 3.0
            return self.content
        if mode == "write":
            if content is not None:
                self.content = content
            self.t_write = t_now
            self.t_lp = (self.t_lp * 2.0 + t_now) / 3.0
            return self.content
        raise ValueError("mode must be 'read' or 'write'")

    def read(self, t_now: float | None = None):
        return self.access("read", t_now=t_now)

    def write(self, content, t_now: float | None = None):
        return self.access("write", content=content, t_now=t_now)

    def sample_l1(self):
        if not self.outlinks:
            return self, None
        total = sum(link.value for link in self.outlinks)
        threshold = random() * total
        walked = 0.0
        selected = self.outlinks[-1]
        for link in self.outlinks:
            walked += link.value
            selected = link
            if walked >= threshold:
                break
        return selected.target, selected

    def sample_l2(self):
        if not self.outlinks:
            return self, None
        weights = [link.value * link.value for link in self.outlinks]
        total = sum(weights)
        threshold = random() * total
        walked = 0.0
        selected = self.outlinks[-1]
        for link, weight in zip(self.outlinks, weights):
            walked += weight
            selected = link
            if walked >= threshold:
                break
        return selected.target, selected
    def __repr__(self):
        return f"node({self.name})"

class NodePtr:
    __slots__ = ("_ref",)

    def __init__(self, node=None):
        object.__setattr__(self, "_ref", None)
        if node is not None:
            self.bind(node)

    def bind(self, node):
        if node is None:
            object.__setattr__(self, "_ref", None)
            return self
        if not isinstance(node, Node):
            raise TypeError("NodePtr can only bind to Node")
        object.__setattr__(self, "_ref", weakref.ref(node))
        return self

    def get(self):
        ref = self._ref
        if ref is None:
            raise ReferenceError("NodePtr is empty")
        node = ref()
        if node is None:
            raise ReferenceError("referenced Node no longer exists")
        return node

    @property
    def node(self):
        return self.get()

    def __bool__(self):
        return self._ref is not None and self._ref() is not None

    def __getattr__(self, name):
        return getattr(self.get(), name)

    def __setattr__(self, name, value):
        if name == "_ref":
            object.__setattr__(self, name, value)
            return
        setattr(self.get(), name, value)

    def __delattr__(self, name):
        if name == "_ref":
            raise AttributeError("cannot delete NodePtr internals")
        delattr(self.get(), name)

    def __repr__(self):
        try:
            return f"NodePtr({self.get()!r})"
        except ReferenceError:
            return "NodePtr(<dangling>)"

    def __copy__(self):
        return type(self)(self._ref() if self._ref is not None else None)

    def __deepcopy__(self, memo):
        return self.__copy__()


def insert_response(reaction,target):
    response=binResponse(reaction, target)
    stk = response.target.source.stk
    if not stk:
        stk.append(response)
    elif stk[-1].reaction == response.reaction:
        stk.append(response)
    else:
        top = stk[-1]
        if response.reaction:
            positive, negative = response.target, top.target
        else:
            positive, negative = top.target, response.target
        new_positive, new_negative = polar_redist(positive.value, negative.value)
        positive.set_raw_value(new_positive)
        negative.set_raw_value(new_negative)
        stk.pop()

@dataclass
class binResponse:
    reaction: bool
    target: Edge
    weight: float = field(init=False)

    def __post_init__(self):
        self.weight = float(self.target.value)


def polar_redist(positive: float, negative: float):
    theta = atan2(negative, positive) / 2
    amp = (positive**2 + negative**2) ** 0.5
    return amp * cos(theta), amp * sin(theta)


class MGraph():
    def __init__(self):
        self.V: set[Node] = set()
        self.E: set[Edge] = set()
        self.debug_node=None
    def random_node(self):
        if not self.V:
            raise ValueError("graph has no nodes")
        return next(iter(self.V))

    def add_node(self, item: Node):
        item._bind_mg(self)
        self.V.add(item)
        return item

    def _register_edge(self, link: Edge):
        self.E.add(link)

    def _unregister_edge(self, link: Edge):
        self.E.discard(link)

    def add_edge(self, u, v, weight, directed=True):
        self.add_node(u)
        self.add_node(v)
        if directed:
            return u.link_to(v, weight)
        else:
            link1 = u.link_to(v, weight)
            link2 = v.link_to(u, weight)
            return (link1, link2)

    def force_normalize(self):
        for node in self.V:
            total = sum(link.value**2 for link in node.outlinks)**0.5
            for link in node.outlinks:
                link.set_raw_value(link.value / total)

    def decay_stk(self, decay_fraction: float = 0.15,
                  min_nodes_ratio: float = 1.0) -> int:
        """腐烂 stk 栈底条目 —— 模拟长期遗忘。

        当所有节点的 stk 条目总数 > |V| * min_nodes_ratio 时触发，
        按每个节点 stk 长度比例分配腐烂额度（含随机扰动），
        从栈底（最早）开始 FIFO 删除。

        返回腐烂的条目总数。
        """
        total = sum(len(n.stk) for n in self.V)
        if total <= len(self.V) * min_nodes_ratio:
            return 0

        target = max(1, int(total * decay_fraction))
        candidates = [n for n in self.V if n.stk]
        if not candidates:
            return 0

        weights = [len(n.stk) for n in candidates]
        total_weight = sum(weights)
        removed = 0

        for node, w in zip(candidates, weights):
            exact = target * w / total_weight
            share = int(exact)
            # 随机扰动处理小数部分
            if random() < (exact - share):
                share += 1
            if share > 0:
                node.stk = node.stk[share:]
                removed += share

        return removed

    def clear_edges(self):
        for item in self.V:
            item.outlinks.clear()
            item.inlinks.clear()
        self.E.clear()

    def init_graph_full_random(self, nodes, avg, var):
        self.clear_edges()
        self.V.clear()
        for i in range(nodes):
            self.add_node(Node(f"node_{i}", mg=self))
        self.full_random_weights(avg,var)
        self.debug_node=self.random_node()

    def full_random_weights(self, avg, var):
        self.clear_edges()
        for node in self.V:
            for target in self.V:
                if node is not target:
                    weight = min(1.0,max(0.0, avg + var * gauss(0.0, 1.0)))
                    node.link_to(target, weight)
        self.force_normalize()
    def decay_stk(self, decay_fraction: float = 0.15,
                  min_nodes_ratio: float = 1.0) -> int:
        """腐烂 stk 栈底条目 —— 模拟长期遗忘。

        当所有节点的 stk 条目总数 > |V| * min_nodes_ratio 时触发，
        按每个节点 stk 长度比例分配腐烂额度，
        再用最大余数法补齐到精确目标值，从栈底（最早）开始 FIFO 删除。

        返回腐烂的条目总数。
        """
        total = sum(len(n.stk) for n in self.V)
        if total <= len(self.V) * min_nodes_ratio:
            return 0

        target = max(1, int(total * decay_fraction))
        if decay_fraction <= 0:
            return 0
        target = min(total, target)

        candidates = [n for n in self.V if n.stk]
        if not candidates:
            return 0

        weights = [len(n.stk) for n in candidates]
        total_weight = sum(weights)
        if target >= total_weight:
            for node in candidates:
                node.stk = []
            return total_weight

        shares = []
        remainders = []
        removed = 0

        for index, (node, w) in enumerate(zip(candidates, weights)):
            exact = target * w / total_weight
            share = int(exact)
            shares.append(share)
            remainders.append((exact - share, index))
            removed += share

        leftover = target - removed
        if leftover > 0:
            order = sorted(
                range(len(candidates)),
                key=lambda index: (remainders[index][0], random()),
                reverse=True,
            )
            for index in order[:leftover]:
                shares[index] += 1

        removed = 0
        for node, share in zip(candidates, shares):
            if share > 0:
                node.stk = node.stk[share:]
                removed += share

        return removed

    def display(self):
        for node in self.V:
            print(f"{node}: {self.V[node]}")



class node_activity_leaderboard:
    __slots__ = ("_heap", "_scores", "_seq")

    def __init__(self, nodes=()):
        self._heap = []
        self._scores = {}
        self._seq = 0
        for item in nodes:
            self.update(item)

    def update(self, item: Node):
        score = float(item.t_lp)
        self._scores[item] = score
        self._seq += 1
        heappush(self._heap, (-score, self._seq, item))
        return score

    def discard(self, item: Node):
        self._scores.pop(item, None)

    def top(self, k: int = 1):
        if k <= 0:
            return []
        result = []
        keep = []
        while self._heap and len(result) < k:
            neg_score, seq, item = heappop(self._heap)
            score = self._scores.get(item)
            if score is None or score != -neg_score:
                continue
            actual = float(item.t_lp)
            if actual != score:
                self.update(item)
                continue
            result.append(item)
            keep.append((neg_score, seq, item))
        for entry in keep:
            heappush(self._heap, entry)
        return result[0] if k == 1 and result else result
