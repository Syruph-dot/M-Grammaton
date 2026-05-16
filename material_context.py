"""Answer material summary metadata and prompt-context selection."""

from __future__ import annotations

import hashlib
import random
import string
import time
from typing import Iterable

from mgraph import Node

SUMMARY_METADATA_KEY = "llm_summary"
SUMMARY_TARGET_CHARS = 50
SUMMARY_HARD_LIMIT_CHARS = 120
SUMMARY_SUBSTITUTION_PROBABILITY = 0.15


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def summary_hash(text: str | None) -> str | None:
    if not text:
        return None
    return content_hash(text)


def build_summary_prompt(node: Node) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "请把以下材料压缩为不超过50字的中文摘要。"
                "保留核心事实、人物、地点、冲突或结论。"
                "只输出摘要正文，不要解释，不要项目符号。"
            ),
        },
        {"role": "user", "content": node.content or ""},
    ]


def normalize_summary_text(text: str | None) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:SUMMARY_HARD_LIMIT_CHARS]


def get_summary_record(node: Node) -> dict | None:
    record = node.metadata.get(SUMMARY_METADATA_KEY)
    return record if isinstance(record, dict) else None


def summary_is_stale(node: Node, model: str | None = None) -> bool:
    record = get_summary_record(node)
    if not record:
        return True
    if record.get("content_hash") != content_hash(node.content or ""):
        return True
    if model is not None and record.get("model") != model:
        return True
    return not bool(record.get("text"))


def store_summary(node: Node, text: str, model: str, now: float | None = None) -> dict:
    record = {
        "text": normalize_summary_text(text),
        "model": model,
        "content_hash": content_hash(node.content or ""),
        "updated_at": time.time() if now is None else float(now),
    }
    node.metadata[SUMMARY_METADATA_KEY] = record
    return record


def material_refs_from_nodes(nodes: Iterable[Node]) -> list[dict]:
    refs = []
    for node in nodes:
        full_text = (node.content or "").strip()
        if not full_text:
            continue
        record = get_summary_record(node)
        summary_text = None
        if record and not summary_is_stale(node):
            summary_text = normalize_summary_text(record.get("text", ""))
        refs.append(
            {
                "node": node.name,
                "title": node.title or node.name,
                "full_text": full_text,
                "summary_text": summary_text,
                "content_hash": content_hash(full_text),
                "summary_hash": summary_hash(summary_text),
            }
        )
    return refs


def choose_answer_materials(
    materials: list[dict],
    rng=None,
    summary_probability: float = SUMMARY_SUBSTITUTION_PROBABILITY,
) -> list[dict]:
    if rng is None:
        rng = random
    chosen = []
    for material in materials:
        summary_text = material.get("summary_text")
        use_summary = (
            bool(summary_text)
            and len(materials) > 1
            and rng.random() < summary_probability
        )
        mode = "summary" if use_summary else "full"
        chosen.append(
            {
                "node": material["node"],
                "title": material["title"],
                "mode": mode,
                "text": summary_text if mode == "summary" else material["full_text"],
                "content_hash": material["content_hash"],
                "summary_hash": (
                    material.get("summary_hash") if mode == "summary" else None
                ),
            }
        )
    if chosen and all(item["mode"] == "summary" for item in chosen):
        first = chosen[0]
        original = next(
            material for material in materials
            if material["node"] == first["node"]
        )
        first["mode"] = "full"
        first["text"] = original["full_text"]
        first["summary_hash"] = None
    return chosen


def format_material_context(chosen: list[dict]) -> str:
    parts = []
    for i, item in enumerate(chosen):
        label = string.ascii_uppercase[i] if i < 26 else str(i + 1)
        mode_label = "摘要" if item["mode"] == "summary" else "全文"
        parts.append(
            f"【材料{label}｜{mode_label}｜{item['title']}】\n{item['text']}"
        )
    return "\n\n---\n\n".join(parts)


def material_trace_records(chosen: list[dict]) -> list[dict]:
    return [
        {
            "node": item["node"],
            "mode": item["mode"],
            "content_hash": item["content_hash"],
            "summary_hash": item.get("summary_hash"),
        }
        for item in chosen
    ]
