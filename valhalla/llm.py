"""LLM 后端 (兼容入口 — 已迁移到 valhalla.core.llm)"""
from valhalla.core.env import load_env
from valhalla.core.llm import ChatBackend, DeepSeekBackend

__all__ = ["load_env", "ChatBackend", "DeepSeekBackend"]
