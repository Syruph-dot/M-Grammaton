"""阿里云百炼混发客户端。

从 data/ALIYUN_MODEL_LIST 文件中读取模型列表，
每次 chat()/chat_json() 随机挑选一个模型，
重试时重新随机挑选（同一请求的不同尝试可能使用不同模型）。
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Any

import httpx

from request_pool import PoolResult, RequestPool

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_TIMEOUT_S = 120
MAX_RETRIES = 3
RETRY_BACKOFF_S = 1.5
DEFAULT_MODEL_LIST_PATH = "data/ALIYUN_MODEL_LIST"


class AliyunLLMClient:
    """阿里云百炼混发客户端。

    - 从 ALIYUN_MODEL_LIST 文件中读取模型列表
    - 每次 chat()/chat_json() 随机挑选一个模型
    - 重试时重新随机挑选（同一请求的不同尝试可能使用不同模型）
    - 与 LLMClient 保持相同的 chat()/chat_json()/close() 接口
    """

    def __init__(
        self,
        api_key: str,
        model_list_path: str | Path = DEFAULT_MODEL_LIST_PATH,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        temperature: float = 0.7,
        request_pool: RequestPool | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.temperature = temperature
        self.model_list = self._load_model_list(model_list_path)
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s))
        self._owns_request_pool = request_pool is None
        self.request_pool = request_pool or RequestPool(
            window_seconds=15.0,
            token_budget=250_000,
        )
        logger.info(
            "AliyunLLMClient 已加载 %d 个模型: %s",
            len(self.model_list), ", ".join(self.model_list),
        )

    @staticmethod
    def _load_model_list(path: str | Path) -> list[str]:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"模型列表文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            models = [line.strip() for line in f if line.strip()]
        if not models:
            raise ValueError(f"模型列表文件为空: {path}")
        return models

    def _pick_model(self) -> str:
        return random.choice(self.model_list)

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
        self._client.close()
        if self._owns_request_pool:
            self.request_pool.close()

    def _chat_once(self, messages, max_retries=3, json_mode=False):
        picked = self._pick_model()
        used_tokens = 0

        for attempt in range(max_retries):
            if attempt > 0:
                # 重试时重新随机选模型
                picked = self._pick_model()

            payload: dict[str, Any] = {
                "model": picked,
                "messages": messages,
                "temperature": self.temperature,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                resp = self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    content=json.dumps(payload),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    choice = data["choices"][0]
                    text = choice["message"]["content"] or ""

                    attempt_tokens = self._usage_tokens(resp, messages, text)
                    used_tokens += attempt_tokens

                    if json_mode:
                        try:
                            value = json.loads(text)
                        except json.JSONDecodeError:
                            if attempt < max_retries - 1:
                                time.sleep(2 ** attempt)
                                continue
                            return PoolResult({}, used_tokens or attempt_tokens)
                        return PoolResult(value, used_tokens)

                    return PoolResult(text, used_tokens)
                else:
                    # 4xx 不重试
                    if 400 <= resp.status_code < 500:
                        fallback_tokens = used_tokens or self._estimate_tokens(messages)
                        return PoolResult({} if json_mode else "", fallback_tokens)
                    # 5xx 重试
                    if attempt < max_retries - 1:
                        time.sleep(RETRY_BACKOFF_S * (2 ** attempt))
                        continue
                    fallback_tokens = used_tokens or self._estimate_tokens(messages)
                    return PoolResult({} if json_mode else "", fallback_tokens)

            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPError):
                if attempt < max_retries - 1:
                    time.sleep(RETRY_BACKOFF_S * (2 ** attempt))
                    continue
                fallback_tokens = used_tokens or self._estimate_tokens(messages)
                return PoolResult({} if json_mode else "", fallback_tokens)

        fallback_tokens = used_tokens or self._estimate_tokens(messages)
        return PoolResult({} if json_mode else "", fallback_tokens)

    @staticmethod
    def _usage_tokens(response, messages, text=""):
        usage = getattr(response, "usage", None)
        if usage is not None:
            total_tokens = AliyunLLMClient._usage_field(usage, "total_tokens")
            if total_tokens is not None:
                return int(total_tokens)
            prompt_tokens = AliyunLLMClient._usage_field(usage, "prompt_tokens")
            completion_tokens = AliyunLLMClient._usage_field(usage, "completion_tokens")
            if prompt_tokens is not None or completion_tokens is not None:
                return int(prompt_tokens or 0) + int(completion_tokens or 0)

        # httpx response -- try reading data
        if isinstance(response, httpx.Response):
            try:
                data = response.json()
                usage = data.get("usage", {})
                if usage:
                    return int(usage.get("total_tokens", 0)
                               or usage.get("prompt_tokens", 0)
                               + usage.get("completion_tokens", 0))
            except Exception:
                pass

        return AliyunLLMClient._estimate_tokens(messages, text)

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
            total += AliyunLLMClient._estimate_text(message.get("content", ""))
        total += AliyunLLMClient._estimate_text(text)
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
