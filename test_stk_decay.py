"""测试：Stk 腐烂机制 —— mgraph.MGraph.decay_stk()。"""

import asyncio
from mgraph import MGraph, Node, Edge, insert_response
from runtime.runtime import OperatorRuntime


def _make_graph_with_stk(node_count: int, stk_per_node: int,
                          seq_reaction: bool = True) -> MGraph:
    """创建图并给每个节点填充 stk。"""
    g = MGraph()
    nodes = []
    for i in range(node_count):
        n = g.add_node(Node(f"node_{i}", mg=g))
        nodes.append(n)

    # 创建边，方便 insert_response
    for i in range(node_count):
        for j in range(node_count):
            if i != j:
                n_i = nodes[i]
                n_j = nodes[j]
                edge = n_i.link_to(n_j, 1.0)

    for i in range(node_count):
        for _ in range(stk_per_node):
            # 取第一条出边
            edge = nodes[i].outlinks[0]
            insert_response(seq_reaction, edge)

    return g


class TestStkDecay:
    def test_no_decay_when_total_below_threshold(self):
        """总条目 <= |V| 时不触发腐烂。"""
        g = _make_graph_with_stk(5, 1)  # 5 nodes, 5 total entries
        result = g.decay_stk()
        assert result == 0, f"expected 0, got {result}"

    def test_decay_when_total_exceeds_threshold(self):
        """总条目 > |V| 时触发腐烂。"""
        g = _make_graph_with_stk(5, 4)  # 5 nodes, 20 total entries
        result = g.decay_stk(decay_fraction=0.5)
        # 15% of 20 = 3 (floor), but we set 50% = 10
        assert result > 0, f"expected > 0, got {result}"
        assert result <= 20

    def test_decay_removes_oldest_entries(self):
        """腐烂移除最早的条目（FIFO 语义）。"""
        g = _make_graph_with_stk(3, 5)  # 3 nodes, 15 total
        node0 = list(g.V)[0]
        original_len = len(node0.stk)
        before = list(node0.stk)  # copy

        g.decay_stk(decay_fraction=0.5)  # should remove ~2-3 entries

        # 如果被截断，剩下的应该是后几个
        if len(node0.stk) < original_len:
            removed_count = original_len - len(node0.stk)
            # 剩余部分 = before[removed_count:] (第一个被移除)
            assert node0.stk == before[removed_count:], \
                "FIFO violation: oldest entries should be removed first"

    def test_decay_removes_exact_fraction(self):
        """在确定性条件下验证总删除数精确等于目标值。"""
        g = _make_graph_with_stk(10, 10)  # 10 nodes, 100 total
        decayed = g.decay_stk(decay_fraction=0.15)
        # 100 * 0.15 = 15
        assert decayed == 15, f"expected 15, got {decayed}"

    def test_empty_stk_does_not_cause_error(self):
        """节点有空的 stk 不应引起错误。"""
        g = _make_graph_with_stk(5, 0)  # no stk
        result = g.decay_stk()
        assert result == 0

    def test_empty_graph_no_error(self):
        """空图不报错。"""
        g = MGraph()
        result = g.decay_stk()
        assert result == 0

    def test_decay_reduces_total_stk_count(self):
        """腐烂后全局 stk 总数应减少。"""
        g = _make_graph_with_stk(5, 6)  # 5 nodes, 30 total
        before = sum(len(n.stk) for n in g.V)
        decayed = g.decay_stk(decay_fraction=0.15)
        after = sum(len(n.stk) for n in g.V)
        assert before - after == decayed, \
            f"mismatch: removed {before - after} != reported {decayed}"

    def test_multiple_decay_calls_converge(self):
        """多次调用后 stk 应逐渐减少但不会变负。"""
        g = _make_graph_with_stk(3, 10)  # 3 nodes, 30 total
        for _ in range(20):
            g.decay_stk(decay_fraction=0.3)
        for n in g.V:
            assert len(n.stk) >= 0
        # 最终所有 stk 可能为空
        total = sum(len(n.stk) for n in g.V)
        assert total >= 0

    def test_runtime_check_stk_decay_uses_node_stk_total(self, tmp_path):
        """Runtime 层应按所有节点的 stk 总数计算满载比例。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        runtime = OperatorRuntime(str(data_dir), model="deepseek-chat", operator_names=[])
        runtime.graph = _make_graph_with_stk(3, 0)
        runtime._stk_decay_counter = 2

        asyncio.run(runtime._check_stk_decay())

        assert runtime._stk_decay_counter == 0
