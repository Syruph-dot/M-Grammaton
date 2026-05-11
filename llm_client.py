"""DeepSeek API 封装（OpenAI 兼容接口）。"""

import json
import math
import time
from openai import OpenAI

from request_pool import PoolResult, RequestPool


class LLMClient:
    def __init__(self, config, client=None, request_pool=None):
        self.client = client or OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.temperature = config.temperature
        self._owns_request_pool = request_pool is None
        self.request_pool = request_pool or RequestPool(
            window_seconds=getattr(config, "request_pool_window_seconds", 15.0),
            token_budget=getattr(config, "request_pool_token_budget", 250_000),
        )

    def chat(self, messages, max_retries=3):
        """普通文本回复。"""
        return self.request_pool.submit(
            lambda: self._chat_once(messages, max_retries=max_retries, json_mode=False)
        )

    def chat_json(self, messages, max_retries=3):
        """JSON 模式回复，返回解析后的 dict。"""
        return self.request_pool.submit(
            lambda: self._chat_once(messages, max_retries=max_retries, json_mode=True)
        )

    def close(self):
        if self._owns_request_pool:
            self.request_pool.close()

    def _chat_once(self, messages, max_retries=3, json_mode=False):
        used_tokens = 0
        for attempt in range(max_retries):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                resp = self.client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""
                attempt_tokens = self._usage_tokens(resp, messages, text)

                if json_mode:
                    try:
                        value = json.loads(text)
                    except json.JSONDecodeError:
                        used_tokens += attempt_tokens
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                            continue
                        return PoolResult({}, used_tokens or attempt_tokens)

                    used_tokens += attempt_tokens
                    return PoolResult(value, used_tokens)

                used_tokens += attempt_tokens
                return PoolResult(text, used_tokens)
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    fallback_tokens = used_tokens or self._estimate_tokens(messages)
                    return PoolResult({} if json_mode else "", fallback_tokens)

    @staticmethod
    def _usage_tokens(response, messages, text=""):
        usage = getattr(response, "usage", None)
        if usage is not None:
            total_tokens = LLMClient._usage_field(usage, "total_tokens")
            if total_tokens is not None:
                return int(total_tokens)

            prompt_tokens = LLMClient._usage_field(usage, "prompt_tokens")
            completion_tokens = LLMClient._usage_field(usage, "completion_tokens")
            if prompt_tokens is not None or completion_tokens is not None:
                return int(prompt_tokens or 0) + int(completion_tokens or 0)

        return LLMClient._estimate_tokens(messages, text)

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
            total += LLMClient._estimate_text(message.get("content", ""))
        total += LLMClient._estimate_text(text)
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
