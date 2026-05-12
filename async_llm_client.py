"""异步 LLM 客户端 —— 基于 httpx.AsyncClient 的 OpenAI 兼容 API 封装。"""

import json
import math
from typing import Any

import httpx


class AsyncLLMClient:
    def __init__(self, config):
        self.client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=60.0,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )
        self.model = config.model
        self.temperature = getattr(config, "temperature", 0.7)

    async def chat(self, messages: list[dict], max_retries=3) -> str:
        last_error = None
        for attempt in range(max_retries):
            try:
                resp = await self.client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"] or ""
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await self._sleep_with_backoff(attempt)
        raise last_error or RuntimeError("chat failed after retries")

    async def chat_json(self, messages: list[dict], max_retries=3) -> dict[str, Any]:
        last_error = None
        for attempt in range(max_retries):
            try:
                resp = await self.client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"] or ""
                return json.loads(text)
            except (json.JSONDecodeError, Exception) as e:
                last_error = e
                if attempt < max_retries - 1:
                    await self._sleep_with_backoff(attempt)
        raise last_error or RuntimeError("chat_json failed after retries")

    async def close(self):
        await self.client.aclose()

    @staticmethod
    async def _sleep_with_backoff(attempt: int):
        import asyncio

        await asyncio.sleep(2 ** attempt)