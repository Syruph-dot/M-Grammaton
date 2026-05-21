"""M-Grammaton LLM 配置 —— DeepSeek API。"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path


_VENDOR_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "aliyun": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


@dataclass
class Config:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    vendor: str = "deepseek"  # "deepseek" | "aliyun"
    temperature: float = 0.7
    request_pool_window_seconds: float = 15.0
    request_pool_token_budget: int = 250000
    data_dir: str = "data"

    def __post_init__(self):
        # 1. 从 config.json 加载覆盖
        path = Path(__file__).parent / "config.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(self, k) and v:
                    setattr(self, k, v)

        # 2. vendor 默认模型
        if not self.model:
            self.model = "deepseek-chat" if self.vendor == "deepseek" else "qwen-plus"

        # 3. base_url 随 vendor 自动切换
        if not self.base_url:
            self.base_url = _VENDOR_BASE_URLS.get(self.vendor, "https://api.deepseek.com")

        # 4. API Key 从环境变量读取
        if not self.api_key:
            if self.vendor == "aliyun":
                self.api_key = os.environ.get("ALIYUN_API_KEY", "")
            else:
                self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    def validate(self) -> bool:
        return bool(self.api_key)
