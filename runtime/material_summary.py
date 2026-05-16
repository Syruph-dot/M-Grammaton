"""Background material-summary maintenance for the async runtime."""

from __future__ import annotations

import asyncio
import logging

from material_context import build_summary_prompt, store_summary, summary_is_stale
from questnode import AnswerNode, QuestNode

logger = logging.getLogger(__name__)


def _material_nodes(graph):
    return [
        node for node in graph.V
        if not isinstance(node, (QuestNode, AnswerNode))
        and (node.content or "").strip()
    ]


async def summarize_stale_materials_once(graph, llm_client, batch_size: int = 2) -> int:
    if llm_client is None:
        return 0
    count = 0
    model = getattr(llm_client, "model", "")
    for node in _material_nodes(graph):
        if count >= batch_size:
            break
        if not summary_is_stale(node, model=model):
            continue
        messages = build_summary_prompt(node)
        try:
            text = await llm_client.chat(messages, telemetry_action="summary")
        except TypeError:
            text = await llm_client.chat(messages)
        except Exception:
            logger.exception("material summary failed for %s", node.name)
            continue
        store_summary(node, text, model=model)
        count += 1
    return count


async def material_summary_loop(
    runtime,
    interval_seconds: float = 30.0,
    batch_size: int = 2,
):
    while runtime.running:
        await summarize_stale_materials_once(
            runtime.graph,
            runtime.llm_client,
            batch_size=batch_size,
        )
        await asyncio.sleep(interval_seconds)
