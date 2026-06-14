"""LLM 后端：Protocol 定义 + DeepSeek 实现 (支持流式 + 思考模式)"""
import logging
from collections.abc import Iterator
from typing import Protocol

from valhalla.core.env import load_env

logger = logging.getLogger(__name__)


class ChatBackend(Protocol):
    """LLM 后端协议：任何有此方法的对象都能当 LLM 用"""
    def chat(self, system: str, user: str) -> str:
        ...

    def chat_stream(self, system: str, user: str) -> Iterator[tuple[str, str]]:
        """流式聊天：yield (type, content) — type: 'reasoning' | 'text' | 'done'"""
        ...


class DeepSeekBackend:
    """DeepSeek API 后端 (兼容 OpenAI 协议，支持 reasoning_effort)"""

    def __init__(self, config_file: str = ".env"):
        config = load_env(config_file)
        self._model = config.get("DEEPSEEK_MODEL", "deepseek-chat")
        self._reasoning = config.get("DEEPSEEK_REASONING", "").strip()
        from openai import OpenAI
        self._client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=config["DEEPSEEK_API_KEY"],
            timeout=120.0,
        )
        if self._reasoning:
            logger.info("思考模式: %s", self._reasoning)

    @property
    def model_name(self) -> str:
        label = self._model
        if self._reasoning:
            label += f" (reasoning={self._reasoning})"
        return label

    @property
    def has_reasoning(self) -> bool:
        return bool(self._reasoning)

    def chat(self, system: str, user: str) -> str:
        logger.info("调用 DeepSeek (model=%s)...", self._model)
        kwargs = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        if self._reasoning:
            kwargs["reasoning_effort"] = self._reasoning
        r = self._client.chat.completions.create(**kwargs)
        return r.choices[0].message.content

    def chat_stream(self, system: str, user: str) -> Iterator[tuple[str, str]]:
        """流式：yield ('reasoning', chunk) / ('text', chunk) / ('done', '')"""
        logger.info("流式调用 DeepSeek (model=%s)...", self._model)
        kwargs = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=4096,
            stream=True,
            stream_options={"include_usage": True},
        )
        if self._reasoning:
            kwargs["reasoning_effort"] = self._reasoning

        stream = self._client.chat.completions.create(**kwargs)
        try:
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    # 空 chunk — 发心跳保持连接
                    yield ("ping", "")
                    continue
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    yield ("reasoning", rc)
                if delta.content:
                    yield ("text", delta.content)
        except Exception as e:
            logger.error("DeepSeek 流式中断: %s", e)
            yield ("text", f"\n\n[生成中断: {e}]")
        yield ("done", "")
