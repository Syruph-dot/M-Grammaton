from math import cos, pi, sin
from random import randint

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

from mgraph import insert_response, mg

NODES = 6
STEPS = 1000
PAUSE = 0.02


def node_index(item):
    return int(item.name.rsplit("_", 1)[-1])


def ordered_nodes(graph):
    return sorted(graph.V, key=node_index)


def circular_layout(nodes, radius=1.0):
    positions = {}
    count = len(nodes)
    for index, item in enumerate(nodes):
        angle = 2.0 * pi * index / count - pi / 2.0
        positions[item] = (radius * cos(angle), radius * sin(angle))
    return positions


def stack_summary(item, limit=8):
    if not item.stk:
        return "stk:[]"
    symbols = ["+" if response.reaction else "-" for response in item.stk]
    if len(symbols) > limit:
        symbols = ["…", *symbols[-limit:]]
    return "stk:" + "".join(symbols)


def stack_offset(x, y, base=0.16, extra=0.18):
    length = (x * x + y * y) ** 0.5
    if length == 0:
        return base, base
    scale = base + extra / length
    return x * scale, y * scale


def draw_graph(ax, nodes, positions, current_source, current_target, current_edge, step, reaction):
    ax.clear()
    weight_max = max(1.0, max((link.value for source in nodes for link in source.outlinks), default=1.0))
    weight_norm = Normalize(vmin=0.0, vmax=weight_max)
    weight_cmap = plt.cm.viridis

    for source in nodes:
        x1, y1 = positions[source]
        for link in source.outlinks:
            x2, y2 = positions[link.target]
            weight = link.value
            ax.plot(
                [x1, x2],
                [y1, y2],
                color=weight_cmap(weight_norm(weight)),
                alpha=0.22 + 0.45 * min(1.0, weight / weight_max),
                linewidth=0.4 + 1.8 * weight,
                zorder=1,
            )

    if current_edge is not None:
        x1, y1 = positions[current_edge.source]
        x2, y2 = positions[current_edge.target]
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(arrowstyle="->", color="crimson", lw=3.0, shrinkA=14, shrinkB=14),
            zorder=3,
        )

    xs = [positions[item][0] for item in nodes]
    ys = [positions[item][1] for item in nodes]
    colors = []
    edgecolors = []
    sizes = []
    for item in nodes:
        if item is current_source:
            colors.append("#FFD54F")
            edgecolors.append("#C97B00")
            sizes.append(280)
        elif item is current_target:
            colors.append("#FF8A80")
            edgecolors.append("#B71C1C")
            sizes.append(260)
        else:
            colors.append("#B3E5FC")
            edgecolors.append("#2C3E50")
            sizes.append(190)

    ax.scatter(xs, ys, s=sizes, c=colors, edgecolors=edgecolors, linewidths=1.5, zorder=4)
    for item in nodes:
        x, y = positions[item]
        ax.text(x, y, item.name.replace("node_", ""), ha="center", va="center", fontsize=9, zorder=5)
        dx, dy = stack_offset(x, y)
        ax.text(
            x + dx,
            y + dy,
            stack_summary(item),
            ha="left" if dx >= 0 else "right",
            va="center",
            fontsize=7,
            color="#444444",
            zorder=6,
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", alpha=0.65, edgecolor="none"),
        )

    title = f"step={step}"
    if reaction is not None:
        title += f" reaction={int(reaction)}"
    ax.set_title(title)
    ax.set_aspect("equal")
    ax.axis("off")
    return weight_norm, weight_cmap


def draw_heatmap(ax, matrix, nodes, step):
    ax.clear()
    vmax = max(1, max((max(row) for row in matrix), default=1))
    image = ax.imshow(matrix, cmap="viridis", vmin=0, vmax=vmax, interpolation="nearest")
    labels = [item.name.replace("node_", "") for item in nodes]
    ax.set_title(f"transition counts after {step} steps")
    ax.set_xlabel("target")
    ax.set_ylabel("source")
    ax.set_xticks(range(len(nodes)))
    ax.set_yticks(range(len(nodes)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(labels, fontsize=8)
    return image


def build_adjacency_matrix(nodes):
    matrix = [[0.0 for _ in range(len(nodes))] for _ in range(len(nodes))]
    index = {item: position for position, item in enumerate(nodes)}
    for source in nodes:
        source_index = index[source]
        total = sum(link.value for link in source.outlinks)
        if total <= 0:
            continue
        for link in source.outlinks:
            matrix[source_index][index[link.target]] = link.value / total
    return matrix


graph = mg()
graph.init_graph_full_random(NODES, 0.5, 5)
nodes = ordered_nodes(graph)
node_to_index = {item: index for index, item in enumerate(nodes)}
positions = circular_layout(nodes)

htmp2 = [[0 for _ in range(NODES)] for _ in range(NODES)]

plt.ion()
fig, (ax_graph, ax_heat, ax_adj) = plt.subplots(1, 3, figsize=(20, 7), constrained_layout=True)

current = graph.random_node()
source = current
current, edge = current.sample_l1()
if edge is None:
    raise ValueError("graph has no outgoing edges")

reaction = bool(randint(0, 1))
insert_response(reaction, edge)
htmp2[node_to_index[source]][node_to_index[current]] += 1

weight_norm, weight_cmap = draw_graph(ax_graph, nodes, positions, source, current, edge, 1, reaction)
image = draw_heatmap(ax_heat, htmp2, nodes, 1)
adj_matrix = build_adjacency_matrix(nodes)
adj_image = draw_heatmap(ax_adj, adj_matrix, nodes, 1)
ax_adj.set_title("current adjacency matrix")
weight_sm = plt.cm.ScalarMappable(norm=weight_norm, cmap=weight_cmap)
weight_sm.set_array([])
weight_cbar = fig.colorbar(weight_sm, ax=ax_graph, fraction=0.046, pad=0.04)
weight_cbar.set_label("edge weight")
colorbar = fig.colorbar(image, ax=ax_heat, fraction=0.046, pad=0.04)
adj_colorbar = fig.colorbar(adj_image, ax=ax_adj, fraction=0.046, pad=0.04)
fig.canvas.draw_idle()
plt.pause(PAUSE)

for step in range(2, STEPS + 1):
    source = current
    current, edge = current.sample_l1()
    if edge is None:
        break

    reaction = bool(randint(0, 1))
    insert_response(reaction, edge)
    htmp2[node_to_index[source]][node_to_index[current]] += 1

    weight_norm, weight_cmap = draw_graph(ax_graph, nodes, positions, source, current, edge, step, reaction)
    weight_sm.set_norm(weight_norm)
    weight_cbar.update_normal(weight_sm)
    image = draw_heatmap(ax_heat, htmp2, nodes, step)
    colorbar.update_normal(image)
    adj_matrix = build_adjacency_matrix(nodes)
    adj_image = draw_heatmap(ax_adj, adj_matrix, nodes, step)
    ax_adj.set_title(f"current adjacency matrix after {step} steps")
    adj_colorbar.update_normal(adj_image)
    fig.canvas.draw_idle()
    plt.pause(PAUSE)

plt.ioff()
plt.show()
