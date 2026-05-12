"""M-Grammaton Gradio GUI —— 知识图谱问答系统可视化交互平台。"""

import os
import time
from pathlib import Path

try:
    import huggingface_hub

    if not hasattr(huggingface_hub, "HfFolder"):
        class _HfFolder:
            @staticmethod
            def get_token():
                return None

            @staticmethod
            def save_token(token):
                return None

            @staticmethod
            def delete_token():
                return None

        huggingface_hub.HfFolder = _HfFolder

    if not hasattr(huggingface_hub, "whoami"):
        huggingface_hub.whoami = lambda *args, **kwargs: None
except Exception:
    pass

import gradio as gr
import matplotlib
import pandas as pd
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

# 中文字体回退
for font_name in ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC"]:
    try:
        matplotlib.font_manager.findfont(font_name, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [font_name] + plt.rcParams["font.sans-serif"]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

from config import Config
from llm_client import LLMClient
from mgraph import MGraph, Node
from operators import Operator
from persistence import save_graph, load_graph, _md_to_node
from quest_board import QuestBoard
from questnode import AnswerNode, QuestNode
from importer import import_materials
from tag_manager import TagManager

# ── 常量 ────────────────────────────────────────────

OPERATOR_NAMES = ["Alice", "Bob", "Carol", "Dave"]


# ── 状态结构 ────────────────────────────────────────

def empty_state():
    return {
        "graph": None,
        "board": None,
        "operators": None,
        "config": None,
        "llm_client": None,
        "round": 0,
        "logs": [],
        "initialized": False,
        "data_dir": "data",
    }


# ── 日志辅助 ────────────────────────────────────────

def log(state, msg):
    state["logs"].append(msg)


def log_join(state):
    return "\n".join(state["logs"])


# ── 图可视化 ────────────────────────────────────────

def render_graph(graph):
    if graph is None or not graph.V:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "(尚未初始化)", ha="center", va="center", fontsize=14)
        return fig

    G = nx.DiGraph()
    node_labels = {}
    for n in graph.V:
        label = n.name
        if isinstance(n, QuestNode):
            label = f"Q: {n.name}"
        elif isinstance(n, AnswerNode):
            label = f"A: {n.name}"
        G.add_node(n.name)
        node_labels[n.name] = label

    for e in graph.E:
        G.add_edge(e.source.name, e.target.name, weight=round(e.value, 4))

    if G.number_of_edges() == 0:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "(图中无连接)", ha="center", va="center", fontsize=14)
        return fig

    pos = nx.circular_layout(G)
    weights = [max(G[u][v]["weight"] * 4, 0.3) for u, v in G.edges()]

    quest_nodes = {n.name for n in graph.V if isinstance(n, QuestNode)}
    answer_nodes = {n.name for n in graph.V if isinstance(n, AnswerNode)}
    node_colors = [
        "#ffcccc" if n in quest_nodes else "#ccffcc" if n in answer_nodes else "lightblue"
        for n in G.nodes()
    ]

    fig, ax = plt.subplots(figsize=(10, 7))
    nx.draw(
        G, pos, ax=ax,
        with_labels=True,
        labels=node_labels,
        node_color=node_colors,
        node_size=600,
        font_size=8,
        width=weights,
        arrowsize=12,
        edge_color="gray",
        arrowstyle="-|>",
    )
    ax.set_title("知识图谱", fontsize=14, fontweight="bold")
    plt.tight_layout()
    return fig


# ── 统计信息 ────────────────────────────────────────

def build_stats(graph, board, operators, round_idx, tag_manager=None):
    if graph is None:
        return "### 统计信息\n\n_(尚未初始化)_"

    quest_count = len(board.active) + len(board.completed) if board else 0

    op_lines = []
    if operators:
        for name, op in operators.items():
            cur_name = "(none)"
            try:
                cur_name = op.current.get().name
            except Exception:
                pass
            mbti_tag = f"[{op.persona.mbti}]" if op.persona else ""
            op_lines.append(f"- **{name}** {mbti_tag} -> `{cur_name}` (已提 {len(op.submitted_quests)} 问)")

    op_text = "\n".join(op_lines)

    stk_total = sum(len(n.stk) for n in graph.V)
    tag_total = tag_manager.total_tag_entries if tag_manager else sum(len(n.tags) for n in graph.V)
    tag_count = len(tag_manager.all_tags) if tag_manager else len(set.union(*[n.tags for n in graph.V])) if graph.V else 0
    return (
        f"### 统计信息\n\n"
        f"- **节点数**: {len(graph.V)}\n"
        f"- **边数**: {len(graph.E)}\n"
        f"- **Quest 总数**: {quest_count} (活跃 {len(board.active)})\n"
        f"- **已运行轮次**: {round_idx}\n"
        f"- **STK 总条目**: {stk_total}\n"
        f"- **标签数**: {tag_count} (总关联 {tag_total})\n\n"
        f"### Operator 状态\n{op_text}"
    )


# ── 问答板表格 ──────────────────────────────────────

def build_quest_table(board):
    if board is None:
        return (
            pd.DataFrame(columns=["Quest", "提问者", "内容", "回答数", "追问深度"]),
            pd.DataFrame(columns=["Quest", "提问者", "内容", "回答数", "平均匹配度", "平均新颖度", "追问深度"]),
        )

    active_rows = []
    for q in board.active:
        answers = q.get_answers()
        depth = getattr(q, "depth", 0)
        active_rows.append({
            "Quest": q.name,
            "提问者": q.quester_id,
            "内容": q.content[:50],
            "回答数": len(answers),
            "追问深度": depth,
        })

    completed_rows = []
    for q in board.completed:
        answers = q.get_answers()
        scored = [a for a in answers if a.match_score is not None]
        avg_match = sum(a.match_score for a in scored) / len(scored) if scored else 0
        avg_novel = sum(a.novelty_score for a in scored) / len(scored) if scored else 0
        depth = getattr(q, "depth", 0)
        completed_rows.append({
            "Quest": q.name,
            "提问者": q.quester_id,
            "内容": q.content[:50],
            "回答数": len(answers),
            "平均匹配度": f"{avg_match:.1f}",
            "平均新颖度": f"{avg_novel:.1f}",
            "追问深度": depth,
        })

    return pd.DataFrame(active_rows), pd.DataFrame(completed_rows)


# ── 节点/边表格 ─────────────────────────────────────

def build_graph_tables(graph):
    if graph is None:
        return (
            pd.DataFrame(columns=["名称", "类型", "出度", "入度", "内容预览", "标签"]),
            pd.DataFrame(columns=["源", "目标", "权重"]),
        )

    nodes = []
    for n in graph.V:
        nodes.append({
            "名称": n.name,
            "类型": n.kind,
            "出度": len(n.outlinks),
            "入度": len(n.inlinks),
            "内容预览": n.content[:40] if n.content else "",
            "标签": ", ".join(sorted(n.tags)) if n.tags else "",
        })

    edges = []
    for e in graph.E:
        edges.append({
            "源": e.source.name,
            "目标": e.target.name,
            "权重": f"{e.value:.4f}",
        })

    return pd.DataFrame(nodes), pd.DataFrame(edges)


def build_tag_table(tag_manager):
    """构建标签统计表格。"""
    if tag_manager is None:
        return pd.DataFrame(columns=["标签", "关联节点数", "节点列表"])
    rows = []
    for tag, nodes in sorted(tag_manager.tag_counts.items()):
        rows.append({
            "标签": tag,
            "关联节点数": nodes,
            "节点列表": ", ".join(sorted(tag_manager.get_tag_nodes(tag))),
        })
    return pd.DataFrame(rows)


# ── 问答详情 ────────────────────────────────────────

def build_quest_detail(board, quest_name):
    if board is None:
        return "_(无数据)_"

    all_quests = board.active + board.completed
    for q in all_quests:
        if q.name == quest_name:
            break
    else:
        return f"未找到 Quest: {quest_name}"

    lines = [f"### {q.name}", f"**提问者**: {q.quester_id}", "", f"**内容**:\n\n{q.content}", ""]

    # 追问链信息
    parent_name = getattr(q, "parent_quest", None)
    depth = getattr(q, "depth", 0)
    if parent_name or depth > 0:
        chain_parts = []
        if parent_name:
            chain_parts.append(f"父 Quest: `{parent_name}`")
        if depth > 0:
            chain_parts.append(f"追问深度: {depth}")
        lines.append(f"**追问链**: {' | '.join(chain_parts)}")
        lines.append("")

    for i, ans in enumerate(q.get_answers()):
        lines.append("---")
        lines.append(f"**回答 #{i}** — {ans.answerer_id}")
        lines.append(f"> {ans.content}")
        if ans.match_score is not None:
            lines.append(f"评分: 匹配度={ans.match_score:.0f}, 新颖度={ans.novelty_score:.0f}")
        if ans.trace:
            path = " -> ".join(ans.trace.node_names) if ans.trace.node_names else "(空)"
            lines.append(f"阅读路径: {path}")
        lines.append("")

    return "\n".join(lines)


def _quest_detail_from_selection(table, state, evt: gr.SelectData):
    """从 Quest 表格选择事件中提取 Quest 名称并返回详情。"""
    quest_name = ""

    row_value = getattr(evt, "row_value", None)
    if isinstance(row_value, dict):
        quest_name = str(row_value.get("Quest", "")).strip()
    elif isinstance(row_value, (list, tuple)) and row_value:
        quest_name = str(row_value[0]).strip()

    if not quest_name:
        value = getattr(evt, "value", None)
        if isinstance(value, str):
            quest_name = value.strip()
        elif isinstance(value, (list, tuple)) and value:
            quest_name = str(value[0]).strip()

    if not quest_name and isinstance(table, pd.DataFrame) and not table.empty:
        try:
            index = evt.index[0] if isinstance(evt.index, tuple) else evt.index
            if isinstance(index, int) and 0 <= index < len(table) and "Quest" in table.columns:
                quest_name = str(table.iloc[index]["Quest"]).strip()
        except Exception:
            pass

    if not quest_name:
        return "### Quest 详情\n\n_(点击表格中的 Quest 查看详情)_"

    return build_quest_detail(state["board"], quest_name)


# ── 内部辅助：算子绑定到图中第一个可用的内容节点 ──────

def _bind_operators_to_graph(operators, graph):
    """将每个算子绑定到图中第一个非 quest、非 answer 的节点。"""
    content_nodes = [n for n in graph.V
                     if not isinstance(n, QuestNode)
                     and not isinstance(n, AnswerNode)]
    if not content_nodes:
        return
    for op in operators.values():
        try:
            _ = op.current.get()
        except Exception:
            op.bind(content_nodes[0])


# ── 内部辅助：从 data/ 目录引导加载节点（无 meta 时） ──

def _bootstrap_graph(data_dir):
    """无 meta/graph.json 时，从 .md 文件加载节点到新图。"""
    root = Path(data_dir)
    graph = MGraph()
    node_map: dict[str, Node] = {}
    pending_parent: dict[str, str | None] = {}

    md_files = sorted(root.glob("*.md"))
    if not md_files:
        return graph, {}

    for md_file in md_files:
        md_text = md_file.read_text(encoding="utf-8")
        node, parent_name, _stk_raw = _md_to_node(md_text, graph)
        node_map[node.name] = node
        pending_parent[node.name] = parent_name

    # 重建父子关系
    for node_name, parent_name in pending_parent.items():
        if parent_name and parent_name in node_map:
            child = node_map[node_name]
            parent = node_map[parent_name]
            parent.add_child(child)

    return graph, node_map


def _create_llm_client(api_key, model_name):
    """用控制台输入或环境变量创建可用的 LLMClient。"""
    if not api_key.strip():
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise gr.Error("请提供 API Key，或设置环境变量 DEEPSEEK_API_KEY")

    config = Config(api_key=api_key.strip(), model=model_name)
    if not config.validate():
        raise gr.Error("API Key 无效")

    return config, LLMClient(config)


# ── 回调：初始化系统 ─────────────────────────────────

def init_system(data_dir, api_key, model_name, state):
    state = dict(state)
    state["logs"] = []
    state["data_dir"] = data_dir

    data_path = Path(data_dir)
    meta_graph = data_path / "meta" / "graph.json"

    if meta_graph.is_file():
        # ── 从 data/ 加载已有状态 ──
        try:
            graph, board, operators, metadata, tag_manager = load_graph(data_dir)
        except Exception as e:
            raise gr.Error(f"加载 data/ 失败: {e}")

        log(state, f"[加载] 从 {data_dir}/ 加载: {len(graph.V)} 节点, {len(graph.E)} 边")
        log(state, f"  Operator: {', '.join(operators.keys())}")

        # 算子绑定到图中内容节点（若当前指针无效）
        _bind_operators_to_graph(operators, graph)

        # 恢复轮次
        round_idx = metadata.get("round", 0) if metadata else 0

    else:
        # ── 引导模式：从 .md 文件加载节点，创建新的 operators/board ──
        graph, _node_map = _bootstrap_graph(data_dir)
        if not graph.V:
            raise gr.Error(f"data/ 目录为空或没有有效的 .md 节点文件。\n请先使用「文段导入」Tab 导入材料。")

        log(state, f"[引导] 从 {data_dir}/ 加载 {len(graph.V)} 个节点（无已有状态）")

        # 创建 Operator，绑定到第一个内容节点
        operators = {}
        content_nodes = [n for n in graph.V
                         if not isinstance(n, QuestNode)
                         and not isinstance(n, AnswerNode)]
        for name in OPERATOR_NAMES:
            op = Operator(name)
            if content_nodes:
                op.bind(content_nodes[0])
            operators[name] = op

        # 材料节点之间初始连接
        for u in content_nodes:
            for v in content_nodes:
                if u is not v and v.name not in [e.target.name for e in u.outlinks]:
                    u.link_to(v, 1.0)

        graph.force_normalize()
        board = QuestBoard()
        round_idx = 0

        # 创建 TagManager
        tag_manager = TagManager()
        tag_manager.rebuild_from_graph(graph)

        log(state, f"  Operator: {', '.join(operators.keys())}")

    # ── LLM 客户端 ──
    config, llm_client = _create_llm_client(api_key, model_name)
    log(state, f"[LLM] 已连接 — 模型: {model_name}")

    # 注入 LLM 客户端到所有 operator
    for op in operators.values():
        op.llm_client = llm_client

    state["graph"] = graph
    state["board"] = board
    state["operators"] = operators
    state["config"] = config
    state["llm_client"] = llm_client
    state["round"] = round_idx
    state["tag_manager"] = tag_manager
    state["initialized"] = True

    log(state, f"[OK] 初始化完成: {len(graph.V)} 节点, {len(graph.E)} 边, {len(operators)} Operator")

    return (
        state,
        log_join(state),
        render_graph(graph),
        build_stats(graph, board, operators, round_idx, tag_manager),
        *build_quest_table(board),
        build_quest_detail(board, ""),
        *build_graph_tables(graph),
        build_tag_table(tag_manager),
    )


# ── 回调：运行一轮 ──────────────────────────────────

def run_round(state, discussion_depth=0):
    if not state["initialized"]:
        raise gr.Error("请先初始化系统")

    state = dict(state)
    graph = state["graph"]
    board = state["board"]
    operators = state["operators"]
    llm_client = state["llm_client"]
    round_idx = state["round"]
    tag_manager = state.get("tag_manager")
    save_graph(state["graph"], state["board"], state["operators"],
               data_dir, metadata=metadata, tag_manager=tag_manager)

    state = dict(state)
    state["data_dir"] = data_dir
    log(state, f"[OK] 状态已保存到 {data_dir}/")
    return state, log_join(state)


def decay_stk_cb(decay_fraction, state):
    """手动触发 stk 衰减。"""
    if not state["initialized"]:
        raise gr.Error("请先初始化系统")
    state = dict(state)
    graph = state["graph"]
    removed = graph.decay_stk(decay_fraction=decay_fraction)
    tag_manager = state.get("tag_manager")
    log(state, f"[手动] stk 衰减 {decay_fraction:.0%}: 移除了 {removed} 条条目")
    return (
        state,
        log_join(state),
        build_stats(graph, state["board"], state["operators"], state["round"], tag_manager),
        build_tag_table(tag_manager),
    )


def test_llm_cb(api_key, model_name):
    """发送固定测试消息，检查当前 API Key / 模型是否可用。"""
    config, llm_client = _create_llm_client(api_key, model_name)
    try:
        reply = llm_client.chat([
            {"role": "user", "content": "hello,this is a test message"},
        ])
        reply_text = reply.strip() if isinstance(reply, str) else str(reply)
        if not reply_text.strip():
            reply_text = "(空响应)"
        return (
            f"模型: {config.model}\n"
            f"发送: hello,this is a test message\n"
            f"回复: {reply_text}"
        )
    finally:
        llm_client.close()


# ── 回调：加载 ──────────────────────────────────────

def load_state_cb(data_dir):
    data_path = Path(data_dir)
    if not (data_path / "meta" / "graph.json").is_file():
        raise gr.Error(f"未找到有效的保存状态: {data_dir}/meta/graph.json")

    # TODO [GUI Phase E]: load_graph 返回 5 值，含 tag_manager
    graph, board, operators, metadata, tag_manager = load_graph(data_dir)

    state = empty_state()
    state["graph"] = graph
    state["board"] = board
    state["operators"] = operators
    state["tag_manager"] = tag_manager
    state["initialized"] = True
    state["data_dir"] = data_dir

    # 算子绑定到图中内容节点（若当前指针无效）
    _bind_operators_to_graph(operators, graph)

    # 重建 LLM 客户端（需要用户重新提供 API Key）
    state["round"] = metadata.get("round", 0) if metadata else 0

    log(state, f"[OK] 状态已从 {data_dir}/ 加载")
    log(state, f"  图: {len(graph.V)} 节点, {len(graph.E)} 边")
    log(state, f"  Operator: {', '.join(operators.keys())}")
    last_model = metadata.get("llm_model") if metadata else None
    if last_model:
        log(state, f"  LLM: 模型={last_model}（请在控制台重新提供 API Key 并初始化）")
    else:
        log(state, "  LLM: 未配置（请在控制台重新初始化以运行新轮次）")

    return (
        state,
        log_join(state),
        render_graph(graph),
        build_stats(graph, board, operators, state["round"], tag_manager),
        *build_quest_table(board),
        build_quest_detail(board, ""),
        *build_graph_tables(graph),
        build_tag_table(tag_manager),
    )


# ── 回调：文段导入 ──────────────────────────────────

def import_materials_cb(source_path, data_dir, tags_str, overwrite, state):
    if not source_path.strip():
        raise gr.Error("请输入源文件路径")

    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    try:
        names = import_materials(source_path, data_dir, tags=tags, overwrite=overwrite)
    except Exception as e:
        raise gr.Error(f"导入失败: {e}")

    state = dict(state)
    state["data_dir"] = data_dir

    lines = [f"[OK] 成功导入 {len(names)} 个节点:"]
    for n in names:
        lines.append(f"  -> data/{n}.md")
    lines.append("")
    lines.append("下一步: 前往 [控制台] -> 初始化系统")

    return state, "\n".join(lines)


def add_tag_cb(tag_name, node_name, state):
    """给指定节点添加标签。"""
    if not tag_name.strip() or not node_name.strip():
        raise gr.Error("标签名和节点名不能为空")
    if not state["initialized"]:
        raise gr.Error("请先初始化系统")

    state = dict(state)
    graph = state["graph"]
    tag_manager = state.get("tag_manager")

    # 查找节点
    node = None
    for n in graph.V:
        if n.name == node_name.strip():
            node = n
            break
    if node is None:
        raise gr.Error(f"未找到节点: {node_name}")

    node.tags.add(tag_name.strip())
    if tag_manager:
        tag_manager.add_tag(node.name, tag_name.strip())

    log(state, f"[标签] 已将标签「{tag_name}」添加到节点「{node.name}」")
    return state, log_join(state)


# ── Gradio 应用 ─────────────────────────────────────

CSS = """
.gr-box {border-radius: 8px;}
h1 {text-align: center;}
"""

with gr.Blocks(title="M-Grammaton", css=CSS, theme=gr.themes.Soft()) as demo:
    state = gr.State(empty_state)

    gr.Markdown(
        "# M-Grammaton — 知识图谱问答系统\n"
        "_Operator 通过 LLM 问答循环驱动图边权重自组织_"
    )

    # ═══════════════════════════════════════════════
    # Tab 1: 控制台
    # ═══════════════════════════════════════════════
    with gr.Tab("控制台"):
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 数据目录")
                data_dir = gr.Textbox(
                    "data", label="data/ 目录",
                    info="从该目录加载知识图谱节点和拓扑数据",
                )

                gr.Markdown("### LLM 配置")
                api_key = gr.Textbox(
                    label="API Key",
                    type="password",
                    placeholder="留空则使用环境变量 DEEPSEEK_API_KEY",
                )
                model_name = gr.Dropdown(
                    ["deepseek-v4-flash", "deepseek-chat", "gpt-4o"],
                    value="deepseek-v4-flash",
                    label="模型",
                )

                with gr.Row():
                    init_btn = gr.Button("初始化系统", variant="primary", size="lg")
                    test_llm_btn = gr.Button("测试 LLM", variant="secondary", size="lg")

                llm_test_result = gr.Textbox(
                    label="LLM 测试结果",
                    lines=6,
                    max_lines=12,
                    interactive=False,
                    placeholder="点击「测试 LLM」后，这里会显示固定消息 hello,this is a test message 的回复",
                )

            with gr.Column(scale=1):
                gr.Markdown("### 运行控制")

    with gr.Tab("文段导入"):
        gr.Markdown("### 将原始 Markdown 材料导入为 data/ 节点文件")

        with gr.Row():
            with gr.Column(scale=1):
                import_source = gr.Textbox(
                    label="源文件/目录",
                    placeholder="例如: 00-设计/ 或 00-设计/00-样例01.md",
                    info="支持单个 .md 文件或包含 .md 文件的目录",
                )
                import_tags = gr.Textbox(
                    label="标签 (逗号分隔)",
                    placeholder="例如: touhou, 东方, 音乐",
                )
                import_overwrite = gr.Checkbox(
                    label="覆盖已存在的节点",
                    value=False,
                )
                import_btn = gr.Button("导入", variant="primary", size="lg")

            with gr.Column(scale=1):
                import_result = gr.Textbox(
                    label="导入结果",
                    lines=12,
                    max_lines=20,
                    interactive=False,
                )

    # ═══════════════════════════════════════════════
    # Tab 6: 标签管理
    # ═══════════════════════════════════════════════
    with gr.Tab("标签管理"):
        gr.Markdown("### 全局标签统计与关联管理")
        with gr.Row():
            tag_table = gr.Dataframe(
                label="标签列表",
                headers=["标签", "关联节点数", "节点列表"],
                interactive=False,
                wrap=True,
            )
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### 关联概念图（按标签筛选）")
                tag_filter = gr.Dropdown(
                    label="按标签筛选概念",
                    choices=[],
                    multiselect=True,
                    interactive=True,
                )
            with gr.Column(scale=1):
                gr.Markdown("#### 标签操作")
                new_tag_name = gr.Textbox(label="新标签名", placeholder="输入标签名")
                new_tag_node = gr.Textbox(label="关联节点名", placeholder="输入节点名")
                add_tag_btn = gr.Button("添加标签到节点", size="sm")

    # ═══════════════════════════════════════════════
    # 事件绑定
    # ═══════════════════════════════════════════════

    state_outputs = [state, log_box, graph_plot, stats_md,
                     active_quests, completed_quests, quest_detail_md,
                     node_table, edge_table, tag_table]

    init_btn.click(
        fn=init_system,
        inputs=[data_dir, api_key, model_name, state],
        outputs=state_outputs,
    )

    run_btn.click(fn=run_round, inputs=[state, discussion_depth], outputs=state_outputs)

    run_n_btn.click(fn=run_n_rounds, inputs=[n_rounds, state], outputs=state_outputs)

    save_btn.click(fn=save_state_cb, inputs=[save_dir, state],
                   outputs=[state, log_box])

    decay_btn.click(
        fn=decay_stk_cb,
        inputs=[decay_fraction, state],
        outputs=[state, log_box, stats_md, tag_table],
    )

    test_llm_btn.click(
        fn=test_llm_cb,
        inputs=[api_key, model_name],
        outputs=[llm_test_result],
    )

    load_btn.click(fn=load_state_cb, inputs=[save_dir],
                   outputs=state_outputs)

    import_btn.click(
        fn=import_materials_cb,
        inputs=[import_source, data_dir, import_tags, import_overwrite, state],
        outputs=[state, import_result],
    )

    add_tag_btn.click(
        fn=add_tag_cb,
        inputs=[new_tag_name, new_tag_node, state],
        outputs=[state, log_box],
    )


# ── 启动 ────────────────────────────────────────────

if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7863,
        show_error=True,
    )
