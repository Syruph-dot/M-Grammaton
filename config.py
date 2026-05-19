"""M-Grammaton LLM 配置 —— DeepSeek API。"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path


@dataclass
class Config:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    vendor: str = "deepseek"  # "deepseek" | "aliyun"
    temperature: float = 0.7
    request_pool_window_seconds: float = 15.0
    request_pool_token_budget: int = 250000
    data_dir: str = "data"

    def __post_init__(self):
        if not self.api_key:
            if self.vendor == "aliyun":
                self.api_key = os.environ.get("ALIYUN_API_KEY", "")
            else:
                self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        path = Path(__file__).parent / "config.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(self, k) and v:
                    setattr(self, k, v)

    def validate(self) -> bool:
        return bool(self.api_key)
