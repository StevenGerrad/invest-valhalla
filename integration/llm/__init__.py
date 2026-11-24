"""向业务模块提供统一的文本模型接口。"""

from .client import ChatBackend, ChatBackendError, ChatErrorKind, create_chat_backend

__all__ = ["ChatBackend", "ChatBackendError", "ChatErrorKind", "create_chat_backend"]
