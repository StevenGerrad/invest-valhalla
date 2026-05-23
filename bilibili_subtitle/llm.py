"""LLM 后端：配置加载 + 薄封装"""
import logging
import os
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


def load_env(filepath: str | Path = ".env") -> dict[str, str]:
    """加载 KEY=VALUE 格式的配置文件，忽略注释和空行"""
    config: dict[str, str] = {}
    if not os.path.exists(filepath):
        return config
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k] = v
    return config


class ChatBackend(Protocol):
    """LLM 后端协议：任何有此方法的对象都能当 LLM 用"""
    def chat(self, system: str, user: str) -> str:
        ...


class DeepSeekBackend:
    """DeepSeek API 后端 (兼容 OpenAI 协议)"""

    def __init__(self, config_file: str | Path = ".env"):
        config = load_env(config_file)
        from openai import OpenAI
        self._client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=config["DEEPSEEK_API_KEY"],
        )
        self._model = config.get("DEEPSEEK_MODEL", "deepseek-chat")

    def chat(self, system: str, user: str) -> str:
        logger.info("调用 DeepSeek (model=%s)...", self._model)
        r = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
        )
        return r.choices[0].message.content
