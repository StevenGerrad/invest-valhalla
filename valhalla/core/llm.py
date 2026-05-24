"""LLM 后端：Protocol 定义 + DeepSeek 实现"""
import logging
from typing import Protocol

from valhalla.core.env import load_env

logger = logging.getLogger(__name__)


class ChatBackend(Protocol):
    """LLM 后端协议：任何有此方法的对象都能当 LLM 用"""
    def chat(self, system: str, user: str) -> str:
        ...


class DeepSeekBackend:
    """DeepSeek API 后端 (兼容 OpenAI 协议)"""

    def __init__(self, config_file: str = ".env"):
        config = load_env(config_file)
        from openai import OpenAI
        self._client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=config["DEEPSEEK_API_KEY"],
        )
        self._model = config.get("DEEPSEEK_MODEL", "deepseek-chat")

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system: str, user: str) -> str:
        logger.info("调用 DeepSeek (model=%s)...", self._model)
        r = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        return r.choices[0].message.content
