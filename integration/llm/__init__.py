"""向业务模块提供统一的文本模型接口。"""

from .catalog import ChatModelCatalog, ChatModelInfo, list_chat_models, resolve_chat_model
from .configured import create_configured_chat_backend
from .contracts import ChatBackend, ChatBackendError, ChatErrorKind, ChatInvoke, ChatRequest, ChatResponse, bind_chat_invoke

__all__ = [
    "ChatBackend",
    "ChatBackendError",
    "ChatErrorKind",
    "ChatInvoke",
    "ChatModelCatalog",
    "ChatModelInfo",
    "ChatRequest",
    "ChatResponse",
    "bind_chat_invoke",
    "create_chat_backend",
    "create_configured_chat_backend",
    "list_chat_models",
    "prepare_chat_backend",
    "resolve_chat_model",
]


def create_chat_backend(*, api_key: str, provider: str | None = None, model: str | None = None) -> ChatBackend:
    """为已登记的模型创建一个文本调用后端。

    :param api_key: 对应供应商的 API Key。
    :param provider: 可选的供应商标识。两项都省略时使用旧调用的默认渠道。
    :param model: 可选的模型标识。省略时使用所选渠道登记的第一个模型。
    :returns: 绑定到指定模型的调用后端。
    :raises ChatBackendError: API Key、模型选择或接入配置无效。
    """
    # 查询目录及导入业务 DTO 不需要加载 OpenAI SDK。
    from .client import create_chat_backend as create_backend

    return create_backend(api_key=api_key, provider=provider, model=model)


def prepare_chat_backend(*, api_key: str, selection: ChatModelInfo) -> ChatBackend:
    """为指定模型创建并探测文本后端。

    :param api_key: 所选供应商的 API Key。
    :param selection: 已登记的供应商和模型组合。
    :returns: 已通过探测的调用后端。
    :raises ChatBackendError: 配置无效或探测调用失败。
    """
    from .client import prepare_chat_backend as prepare_backend

    return prepare_backend(api_key=api_key, selection=selection)
