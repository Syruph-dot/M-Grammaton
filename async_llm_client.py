"""异步 LLM 客户端 —— 基于 httpx.AsyncClient 的 OpenAI 兼容 API 封装。"""

import json
import math
from typing import Any

import httpx


class AsyncLLMClient:
    def __init__(self, config, monitor=None, operator_id: str | None = None):
        self.client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=60.0,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )
        self.model = config.model
        self.temperature = getattr(config, "temperature", 0.7)
        self.monitor = monitor
        self.operator_id = operator_id

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
                text = data["choices"][0]["message"]["content"] or ""
                self._report_tokens(messages, text, data, action="chat")
                return text
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
                value = json.loads(text)
                self._report_tokens(messages, text, data, action="chat_json")
                return value
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

    def _report_tokens(self, messages, text, response_data, action: str):
        if self.monitor is None:
            return
        tokens, source = self._usage_tokens(response_data, messages, text)
        self.monitor.report_tokens(
            operator_id=self.operator_id or "",
            action=action,
            tokens=tokens,
            source=source,
        )

    @staticmethod
    def _usage_tokens(response_data, messages, text="") -> tuple[int, str]:
        usage = response_data.get("usage") if isinstance(response_data, dict) else None
        if usage is not None:
            total_tokens = AsyncLLMClient._usage_field(usage, "total_tokens")
            if total_tokens is not None:
                return int(total_tokens), "reported"

            prompt_tokens = AsyncLLMClient._usage_field(usage, "prompt_tokens")
            completion_tokens = AsyncLLMClient._usage_field(usage, "completion_tokens")
            if prompt_tokens is not None or completion_tokens is not None:
                return int(prompt_tokens or 0) + int(completion_tokens or 0), "reported"

        return AsyncLLMClient._estimate_tokens(messages, text), "estimated"

    @staticmethod
    def _usage_field(usage, field_name):
        if hasattr(usage, field_name):
            return getattr(usage, field_name)
        if isinstance(usage, dict):
            return usage.get(field_name)
        return None

    @staticmethod
    def _estimate_tokens(messages, text=""):
        total = 0.0
        for message in messages:
            total += 4.0
            total += AsyncLLMClient._estimate_text(message.get("content", ""))
        total += AsyncLLMClient._estimate_text(text)
        return max(1, math.ceil(total))

    @staticmethod
    def _estimate_text(text):
        total = 0.0
        for ch in text:
            if ch.isspace():
                continue
            code = ord(ch)
            if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3000 <= code <= 0x303F:
                total += 0.6
            elif ch.isascii() and (ch.isalnum() or ch in {"_", "-"}):
                total += 0.3
            elif ch.isascii():
                total += 1.0
            else:
                total += 0.6
        return total
