"""文段导入器 —— 将原始 markdown 材料转为 data/*.md 节点文件。"""

import re
import os
from pathlib import Path

import yaml

from mgraph import Node


def import_materials(
    source_path: str,
    data_dir: str = "data",
    tags: list[str] | None = None,
    overwrite: bool = False,
    metadata: dict | None = None,
) -> list[str]:
    """从源文件/目录导入材料章节为 data/*.md 节点文件。

    参数：
        source_path: 源 .md 文件或包含 .md 文件的目录
        data_dir: 目标 data/ 目录
        tags: 所有导入节点共享的标签
        overwrite: True=覆盖已存在的节点
        metadata: 注入到所有节点的 metadata（如 author, source）

    返回：已导入的节点名列表。
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"源路径不存在: {source_path}")

    md_files = sorted(src.glob("*.md")) if src.is_dir() else [src]
    if not md_files:
        raise ValueError(f"未找到 .md 文件: {source_path}")

    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)

    imported: list[str] = []
    tags = tags or []

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        materials = _parse_material_sections(text)
        for label, content in materials:
            node_name = _make_node_name(md_file.stem, label)
            file_path = root / f"{node_name}.md"

            if file_path.exists() and not overwrite:
                continue

            # 提取 title：前 8 个有意义的词
            title = _extract_title(content, label)

            # 构建 metadata
            node_meta = dict(metadata or {})
            if "source" not in node_meta:
                node_meta["source"] = md_file.name

            node = Node(
                name=node_name,
                kind="document",
                content=content,
                tags=set(tags),
                metadata=node_meta,
            )
            node.title = title

            md_text = _node_to_md(node)
            tmp_path = root / f"{node_name}.md.tmp"
            tmp_path.write_text(md_text, encoding="utf-8")
            os.replace(str(tmp_path), str(file_path))

            imported.append(node_name)

    return imported


def import_single_text(
    title: str,
    content: str,
    data_dir: str = "data",
    node_name: str | None = None,
    kind: str = "document",
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> str:
    """导入单篇文段为一个节点文件。

    返回：节点名。
    """
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)

    name = node_name or _slugify(title)

    node = Node(
        name=name,
        kind=kind,
        content=content,
        tags=set(tags or []),
        metadata=dict(metadata or {}),
    )
    node.title = title

    file_path = root / f"{name}.md"
    tmp_path = root / f"{name}.md.tmp"
    tmp_path.write_text(_node_to_md(node), encoding="utf-8")
    os.replace(str(tmp_path), str(file_path))

    return name


# ── 内部辅助 ──────────────────────────────────────

# 匹配 ## 材料[A-Z] 或 ## 材料[A-Z]（...）
_MATERIAL_RE = re.compile(
    r"^##\s+材料([A-Za-z])(?:[（(][^)）]*[)）])?[：:]\s*$", re.MULTILINE
)


def _parse_material_sections(text: str) -> list[tuple[str, str]]:
    """解析 markdown 中的材料章节 → [(label, content), ...]"""
    matches = list(_MATERIAL_RE.finditer(text))
    if not matches:
        return []

    result = []
    for i, m in enumerate(matches):
        label = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content and len(content) > 100 and "{format:" not in content[:200]:
            result.append((label, content))

    return result


def _make_node_name(source_stem: str, label: str) -> str:
    """生成节点名：源文件名_材料X。"""
    return f"{source_stem}_材料{label}"


def _extract_title(content: str, label: str) -> str:
    """从内容开头提取有意义的词作为标题。"""
    first_line = content.split("\n")[0].strip()[:60]
    # 去除末尾不完整的单词/字符
    clean = first_line.rstrip(",.;:!?，。；：！？")
    return f"材料{label} — {clean}" if clean else f"材料{label}"


def _slugify(text: str) -> str:
    """将文本转为合法的节点名。"""
    name = re.sub(r'[<>:"/\\|?*]', "_", text)
    name = name.strip(". ")
    return name[:64] if name else "untitled"


# ── Node → .md（最小化复制，避免循环导入） ─────────

def _node_to_md(node: Node) -> str:
    """Node → .md 字符串（YAML frontmatter + body）。"""
    fm = {
        "name": node.name,
        "kind": node.kind,
        "title": getattr(node, "title", node.name),
        "tags": sorted(node.tags) if node.tags else [],
        "t_read": node.t_read,
        "t_write": node.t_write,
        "t_lp": node.t_lp,
        "parent": node.parent.name if node.parent else None,
        "metadata": dict(getattr(node, "metadata", {})),
        "stk": [],
    }

    yaml_str = yaml.safe_dump(fm, allow_unicode=True, default_flow_style=False,
                               sort_keys=False).strip()
    content = node.content or ""
    if content.lstrip().startswith("---"):
        content = "\n" + content

    return f"---\n{yaml_str}\n---\n\n{content}"


# ── CLI ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="M-Grammaton 文段导入器")
    ap.add_argument("source", help="源 .md 文件或目录")
    ap.add_argument("--data-dir", default="data", help="目标 data/ 目录 (默认: data)")
    ap.add_argument("--tags", default="", help="逗号分隔的标签")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已存在的节点")
    args = ap.parse_args()

    tag_list = [t.strip() for t in args.tags.split(",") if t.strip()]
    names = import_materials(args.source, args.data_dir, tags=tag_list,
                             overwrite=args.overwrite)
    print(f"Import done: {len(names)} nodes")
    for n in names:
        print(f"  -> data/{n}.md")
