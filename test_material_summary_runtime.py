import asyncio

from material_context import SUMMARY_METADATA_KEY
from mgraph import MGraph, Node
from questnode import AnswerNode, QuestNode
from runtime.material_summary import summarize_stale_materials_once


class FakeAsyncLLM:
    model = "summary-model"

    def __init__(self):
        self.calls = []

    async def chat(self, messages, telemetry_action="chat"):
        self.calls.append((messages, telemetry_action))
        return "这是一个超过五十字约束但仍应被代码硬截断的摘要" * 4


def test_summarize_stale_materials_once_stores_summary_and_skips_qa_nodes():
    async def run():
        graph = MGraph()
        material = Node("material", content="完整材料内容", mg=graph)
        quest = QuestNode("quest", quester_id="Alice", content="q?")
        answer = AnswerNode(
            "answer",
            answerer_id="Bob",
            quest_name="quest",
            content="a",
        )
        graph.add_node(quest)
        graph.add_node(answer)
        fake = FakeAsyncLLM()

        count = await summarize_stale_materials_once(graph, fake, batch_size=10)

        assert count == 1
        assert len(fake.calls) == 1
        assert fake.calls[0][1] == "summary"
        assert "不超过50字" in fake.calls[0][0][0]["content"]
        assert len(material.metadata[SUMMARY_METADATA_KEY]["text"]) <= 120
        assert SUMMARY_METADATA_KEY not in quest.metadata
        assert SUMMARY_METADATA_KEY not in answer.metadata

    asyncio.run(run())
