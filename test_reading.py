"""Phase 3: Operator 阅读路径测试（直接测试 operator_core）。"""
from mgraph import MGraph, Node
from operator_core import read_context


def _chain_graph(size=4):
    """创建一条链式图: node_0 -> node_1 -> node_2 -> ..."""
    g = MGraph()
    nodes = []
    for i in range(size):
        n = Node(f"node_{i}", content=f"content_{i}", mg=g)
        nodes.append(n)
    for i in range(size - 1):
        nodes[i].link_to(nodes[i + 1], 1.0)
    return g, nodes


def test_read_respects_node_limit():
    g, nodes = _chain_graph(5)
    names, edges, ctx = read_context(nodes[0], node_limit=3)

    assert len(names) == 3
    assert names == ["node_0", "node_1", "node_2"]
    assert len(edges) == 2
    assert edges[0] == ("node_0", "node_1")
    assert edges[1] == ("node_1", "node_2")


def test_read_single_node_when_no_outlinks():
    n = Node("lonely", content="alone")
    names, edges, ctx = read_context(n, node_limit=5)

    assert names == ["lonely"]
    assert edges == []


def test_read_collects_context():
    g, nodes = _chain_graph(3)
    names, edges, ctx = read_context(nodes[0], node_limit=3)

    assert "content_0" in ctx
    assert "content_1" in ctx
    assert "content_2" in ctx


def test_read_empty_content_nodes():
    """节点 content 为空时，context_text 应跳过空片段。"""
    g = MGraph()
    n0 = Node("n0", mg=g)
    n1 = Node("n1", mg=g)
    n0.link_to(n1, 1.0)
    names, edges, ctx = read_context(n0, node_limit=2)

    assert names == ["n0", "n1"]
    assert ctx == ""


def test_read_node_limit_one():
    g, nodes = _chain_graph(5)
    names, edges, ctx = read_context(nodes[0], node_limit=1)

    assert names == ["node_0"]
    assert edges == []
