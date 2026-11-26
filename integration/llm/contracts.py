"""定义文本模型接入的调用契约和错误类型。"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


type ChatEvent = tuple[Literal["reasoning", "text", "ping", "done"], str]


@dataclass(frozen=True)
class ChatRequest:
    """表示一次非流式文本模型调用的消息。"""

    #: 系统提示词，描述本次模型调用的任务和约束。
    system: str
    #: 用户消息，承载本轮提交给模型的内容。
    user: str


@dataclass(frozen=True)
class ChatResponse:
    """承载一次非流式文本模型调用的完整正文。"""

    #: 模型返回的文本，由调用方按业务约定解释。
    text: str


#: 由调用方注入的单轮模型调用，使用请求和响应 DTO 交换消息。
type ChatInvoke = Callable[[ChatRequest], ChatResponse]


class ChatBackend(Protocol):
    """约定业务模块使用的文本和流式调用方式，隔离供应商 SDK。"""

    def chat(self, system: str, user: str) -> str:
        """返回一轮对话的完整正文。

        :param system: 系统提示词。
        :param user: 用户消息。
        :returns: 模型生成的完整文本。
        :raises ChatBackendError: 请求失败或未得到完整正文。
        """
        ...

    def chat_stream(self, system: str, user: str) -> Iterator[ChatEvent]:
        """逐段返回思考、正文和心跳，正常结束时发送 done。

        :param system: 系统提示词。
        :param user: 用户消息。
        :returns: 由事件类型和文本组成的迭代器，ping 和 done 的文本为空。
        :raises ChatBackendError: 请求或迭代失败，或未得到完整正文。
        """
        ...


class ChatErrorKind(StrEnum):
    """提供供调用方判断的稳定错误类别。"""

    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INCOMPLETE_RESPONSE = "incomplete_response"
    UPSTREAM = "upstream"


class ChatBackendError(RuntimeError):
    """统一报告配置、服务调用和响应完整性问题。"""

    def __init__(
        self, kind: ChatErrorKind, provider: str | None = None, model: str | None = None,
        *, detail: str | None = None,
    ) -> None:
        """保存可安全报告的错误上下文。

        :param kind: 接入层错误类别。
        :param provider: 已验证的配置渠道名，未知时为 None。
        :param model: 已配置的模型 ID，未选定模型时为 None。
        :param detail: 接入层生成的安全说明，例如缺失的配置变量名。
        """
        self.kind = kind
        self.provider = provider
        self.model = model
        details = ", ".join(value for value in (provider, model) if value is not None)
        message = f"模型接入错误 [{kind}]" + (f" ({details})" if details else "")
        super().__init__(f"{message}。{detail}" if detail else message)
