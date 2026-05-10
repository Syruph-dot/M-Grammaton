"""DeepSeek API 封装（OpenAI 兼容接口）。"""

import json
import time
from openai import OpenAI


class LLMClient:
    def __init__(self, config):
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.temperature = config.temperature

    def chat(self, messages, max_retries=3):
        """普通文本回复。"""
        for attempt in range(max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                return resp.choices[0].message.content
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return ""

    def chat_json(self, messages, max_retries=3):
        """JSON 模式回复，返回解析后的 dict。"""
        for attempt in range(max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )
                text = resp.choices[0].message.content
                return json.loads(text)
            except (json.JSONDecodeError, Exception) as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return {}
