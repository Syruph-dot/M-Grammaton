"""多 Operator 问答模拟演示 —— Q&A 循环驱动图权重自组织。"""

from mgraph import mg, Node
from operators import Operator
from quest_board import QuestBoard
import matplotlib.pyplot as plt
import networkx as nx

QUEST_POOL = [
    "如何定义 consciousness？",
    "机器能否创造艺术？",
    "知识图谱的最佳实践是什么？",
    "RLHF 的局限性在哪里？",
    "什么是 good AGI 治理框架？",
]

SCORE_STRATEGIES = {
    "Alice": {"Bob": 0.85, "Carol": 0.40, "Dave": 0.70},
    "Bob": {"Alice": 0.75, "Carol": 0.60, "Dave": 0.90},
    "Carol": {"Alice": 0.30, "Bob": 0.80, "Dave": 0.55},
    "Dave": {"Alice": 0.65, "Bob": 0.45, "Carol": 0.85},
}


def edge_weight_matrix(g, nodes):
    idx = {n: i for i, n in enumerate(nodes)}
    size = len(nodes)
    m = [[0.0] * size for _ in range(size)]
    for src in nodes:
        for e in src.outlinks:
            if e.target in idx:
                m[idx[src]][idx[e.target]] = e.value
    return m


def print_quest_table(board):
    print(f"  {'Quest':<18} {'Quester':<10} {'Answers':<8} {'Avg Score':<10}")
    print(f"  {'-'*46}")
    for q in board.active + board.completed:
        avg = (
            sum(s for s in q.scores if s is not None) / len([s for s in q.scores if s is not None])
            if any(s is not None for s in q.scores)
            else 0
        )
        answered = len([s for s in q.scores if s is not None])
        print(f"  {q.name:<18} {q.quester_id:<10} {answered:<8} {avg:.3f}")


def print_edge_table(graph):
    print(f"  {'Source':<14} {'Target':<14} {'Weight':<8}")
    print(f"  {'-'*36}")
    for e in graph.E:
        print(f"  {e.source.name:<14} {e.target.name:<14} {e.value:.4f}")


def visualize_graph(graph, title, step):
    """用 matplotlib + networkx 画图。"""
    G = nx.DiKeyedGraph()
    for n in graph.V:
        G.add_node(n.name)
    for e in graph.E:
        G.add_edge(e.source.name, e.target.name, weight=e.value)
    pos = nx.circular_layout(G)
    weights = [G[u][v]["weight"] * 3 for u, v in G.edges()]
    plt.figure(figsize=(10, 6))
    nx.draw(
        G,
        pos,
        with_labels=True,
        node_color="lightblue",
        node_size=500,
        font_size=9,
        width=weights,
        arrowsize=15,
        edge_color="gray",
    )
    plt.title(f"{title} (step={step})")
    plt.tight_layout()
    plt.show(block=False)
    plt.pause(1.5)
    plt.close()


def main():
    # ── 初始化 ────────────────────────────────────
    g = mg()
    g.init_graph_full_random(6, 0.5, 2)

    operators = {
        name: Operator(name)
        for name in ["Alice", "Bob", "Carol", "Dave"]
    }

    # 锚定每个 operator 到专属节点
    # 先清空随机节点，用有意义的结构替代
    g.V.clear()
    g.clear_edges()
    anchors = {}
    for name, op in operators.items():
        anchor = g.add_node(Node(f"op_{name}", mg=g))
        op.bind(anchor)
        anchors[name] = anchor

    board = QuestBoard()

    print("=" * 60)
    print("  M-Grammaton 问答模拟")
    print("  Q&A 循环 → 边权重自组织")
    print("=" * 60)
    print()

    for round_idx in range(5):
        print(f"\n{'─'*60}")
        print(f"  第 {round_idx + 1} 轮")
        print(f"{'─'*60}")

        # ── 提问 ──
        asker_name = list(operators.keys())[round_idx % len(operators)]
        asker = operators[asker_name]
        content = QUEST_POOL[round_idx]
        quest = asker.ask(g, board, content)
        print(f"\n  [{asker_name}] 提问: 『{content}』")

        # ── 回答（回答者直接回答本轮 quest）──
        for ans_name, ans_op in operators.items():
            if ans_name == asker_name:
                continue
            ans_op.answer_quest(quest, board, g)
            print(f"  [{ans_name}] 回答: {quest.answers[-1][:40]}...")

        # ── 评分 ──
        for ans_name in operators:
            if ans_name == asker_name:
                continue
            score = SCORE_STRATEGIES[asker_name].get(ans_name, 0.5)
            asker.score_answer(quest, ans_name, score, g, board)
            print(f"  [{asker_name}] → {ans_name} 评分: {score}")

        # ── 归一化 ──
        g.force_normalize()

        # ── 输出状态 ──
        print(f"\n  --- 边权重 (op 节点间) ---")
        for src_name in operators:
            src = anchors[src_name]
            for e in src.outlinks:
                if e.target in anchors.values():
                    tgt_name = next(n for n, a in anchors.items() if a is e.target)
                    print(f"    {src_name} -> {tgt_name}: {e.value:.4f}")

        # 所有 operator 回到锚点
        for op in operators.values():
            op.bind(anchors[op.id])

    # ── 最终统计 ──
    print(f"\n{'='*60}")
    print("  最终统计")
    print(f"{'='*60}")
    print("\n--- 问答板 ---")
    print_quest_table(board)

    # 可视化边权重变化
    print("\n--- operator 间边权重热图 (最后状态) ---")
    op_nodes = [op.current.get() for op in operators.values()]
    op_names = list(operators.keys())
    matrix = edge_weight_matrix(g, op_nodes)
    if matrix:
        print(f"     {'':>10}", " ".join(f"{n:>10}" for n in op_names))
        for i, row_name in enumerate(op_names):
            print(f"     {row_name:>10}", " ".join(f"{v:>10.4f}" for v in matrix[i]))

    print("\n  [OK] 模拟完成")


if __name__ == "__main__":
    main()
