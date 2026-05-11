"""多 Operator 问答模拟演示 —— Q&A 循环驱动图权重自组织。"""

from mgraph import MGraph, Node
from operators import Operator
from quest_board import QuestBoard
from questnode import AnswerNode
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
    "Alice": {"Bob": (85, 70), "Carol": (40, 65), "Dave": (70, 75)},
    "Bob": {"Alice": (75, 70), "Carol": (60, 65), "Dave": (90, 80)},
    "Carol": {"Alice": (30, 60), "Bob": (80, 70), "Dave": (55, 65)},
    "Dave": {"Alice": (65, 70), "Bob": (45, 60), "Carol": (85, 75)},
}


def print_quest_table(board):
    print(f"  {'Quest':<18} {'Quester':<10} {'Answers':<8} {'Avg Match':<10} {'Avg Novel':<10}")
    print(f"  {'-'*56}")
    for q in board.active + board.completed:
        answers = q.get_answers()
        scored = [a for a in answers if a.match_score is not None]
        if scored:
            avg_match = sum(a.match_score for a in scored) / len(scored)
            avg_novel = sum(a.novelty_score for a in scored) / len(scored)
        else:
            avg_match = avg_novel = 0
        answered = len(scored)
        print(f"  {q.name:<18} {q.quester_id:<10} {answered:<8} {avg_match:<10.1f} {avg_novel:<10.1f}")


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
    g = MGraph()
    g.init_graph_full_random(6, 0.5, 2)

    operators = {
        name: Operator(name)
        for name in ["Alice", "Bob", "Carol", "Dave"]
    }

    # 用有意义的内容节点替换随机节点
    g.V.clear()
    g.clear_edges()
    content_nodes = []
    for i in range(4):
        node = g.add_node(Node(f"content_{i}", kind="document",
                                content=f"知识材料 #{i}", mg=g))
        content_nodes.append(node)

    # 内容节点之间全连接
    for u in content_nodes:
        for v in content_nodes:
            if u is not v:
                u.link_to(v, 1.0)

    # 算子绑定到第一个内容节点
    for op in operators.values():
        op.bind(content_nodes[0])

    board = QuestBoard()

    print("=" * 60)
    print("  M-Grammaton 问答模拟")
    print("  Q&A 循环 -> 边权重自组织")
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

        # ── 回答 ──
        for ans_name, ans_op in operators.items():
            if ans_name == asker_name:
                continue
            ans_node = ans_op.answer_quest(quest, board, g)
            trace = ans_node.trace
            path_str = " -> ".join(trace.node_names) if trace else "(no trace)"
            print(f"  [{ans_name}] 回答: {ans_node.content[:40]}...")
            print(f"         path: {path_str}")

        # ── 评分 ──
        for ans_name in operators:
            if ans_name == asker_name:
                continue
            match_score, novelty_score = SCORE_STRATEGIES[asker_name].get(ans_name, (50, 50))
            asker.score_answer(quest, ans_name, match_score, novelty_score, g, board)
            avg = (match_score + novelty_score) / 2
            fb = "positive" if avg > 80 else "negative"
            ans_node = quest.get_answer_by_id(ans_name)
            edges = len(ans_node.trace.edge_refs) if ans_node and ans_node.trace else 0
            print(f"  [{asker_name}] -> {ans_name}  [{match_score}, {novelty_score}]  avg={avg:.0f}  {fb}  edges={edges}")

        # ── 归一化 ──
        g.force_normalize()

        # ── stk 腐烂 ──
        decayed = g.decay_stk()
        if decayed > 0:
            print(f"  [遗忘] stk 腐烂: {decayed} 条过期反馈已清除")

    # ── 最终统计 ──
    print(f"\n{'='*60}")
    print("  最终统计")
    print(f"{'='*60}")
    print("\n--- 问答板 ---")
    print_quest_table(board)

    # ── 图边权重 ──
    print("\n--- 图中所有边 (最后状态) ---")
    print_edge_table(g)

    print("\n  [OK] 模拟完成")


if __name__ == "__main__":
    main()
