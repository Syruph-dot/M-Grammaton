from mgraph import MGraph, Node


def test_force_normalize_skips_zero_outgoing_total():
    graph = MGraph()
    source = graph.add_node(Node("source", mg=graph))
    target = graph.add_node(Node("target", mg=graph))
    source.link_to(target, 0.0)

    graph.force_normalize()

    assert source.outlinks[0].value == 0.0
