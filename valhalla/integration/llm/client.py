"""用同一个 OpenAI Chat Completions 客户端调用已配置的模型渠道。"""

import math
from collections.abc import Iterator
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam

from ..config import load_config_section

type ChatEvent = tuple[Literal["reasoning", "text", "ping", "done"], str]


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
    ) -> None:
        """保存可安全报告的错误上下文。

        :param kind: 接入层错误类别。
        :param provider: 已验证的配置渠道名，未知时为 None。
        :param model: 已配置的模型 ID，未选定模型时为 None。
        """
        self.kind = kind
        self.provider = provider
        self.model = model
        details = ", ".join(value for value in (provider, model) if value is not None)
        super().__init__(f"模型接入错误 [{kind}]" + (f" ({details})" if details else ""))


class _OpenAIChatBackend:
    """将 OpenAI 兼容响应转换为业务模块使用的文本和流式事件。"""

    def __init__(
        self, client: OpenAI, provider: str, model: str, extra_body: dict,
    ) -> None:
        """绑定一个已配置的 SDK 客户端和模型。

        :param client: 已配置服务地址、鉴权和超时的客户端。
        :param provider: 渠道名，用于错误定位。
        :param model: 传入模型接口的模型 ID。
        :param extra_body: 供应商扩展请求字段，空字典表示无扩展字段。
        """
        self._client = client
        self._provider = provider
        self._model = model
        self._extra_body = extra_body

    def chat(self, system: str, user: str) -> str:
        """请求完整正文，并检查服务是否正常结束生成。

        :param system: 系统提示词。
        :param user: 用户消息。
        :returns: 保留原始空白的模型正文。
        :raises ChatBackendError: 请求失败、正文为空或生成未正常结束。
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model, messages=_messages(system, user), extra_body=self._extra_body,
            )
        except APIError as exc:
            raise ChatBackendError(_error_kind(exc), self._provider, self._model) from None
        except ValueError:
            raise ChatBackendError(
                ChatErrorKind.INCOMPLETE_RESPONSE, self._provider, self._model,
            ) from None

        # 网关也可能返回成功状态的 HTML 页面，或返回带截断标记的正文。
        choices = getattr(response, "choices", None)
        if choices:
            choice = choices[0]
            content = getattr(choice.message, "content", None)
            if choice.finish_reason == "stop" and content and content.strip():
                return content
        raise ChatBackendError(ChatErrorKind.INCOMPLETE_RESPONSE, self._provider, self._model)

    def chat_stream(self, system: str, user: str) -> Iterator[ChatEvent]:
        """归一化分块响应，迭代完成后确认终止标记和正文。

        :param system: 系统提示词。
        :param user: 用户消息。
        :returns: 模型流式事件，成功时以 done 收尾。
        :raises ChatBackendError: 请求失败、流式中断或未得到完整正文。
        """
        finish_reason = None
        has_text = False
        try:
            # 迭代器提前关闭或服务报错时，SDK 上下文管理器会释放连接。
            with self._client.chat.completions.create(
                model=self._model,
                messages=_messages(system, user),
                extra_body=self._extra_body,
                stream=True,
                stream_options={"include_usage": True},
            ) as stream:
                for chunk in stream:
                    # 用量帧可能不带 choices。保留心跳事件，等待流正常结束。
                    if not chunk.choices:
                        yield "ping", ""
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason is not None:
                        finish_reason = choice.finish_reason
                    reasoning = getattr(choice.delta, "reasoning_content", None)
                    if reasoning:
                        yield "reasoning", reasoning
                    content = getattr(choice.delta, "content", None)
                    if content:
                        has_text = has_text or bool(content.strip())
                        yield "text", content
        except APIError as exc:
            raise ChatBackendError(_error_kind(exc), self._provider, self._model) from None
        except httpx.TimeoutException:
            raise ChatBackendError(ChatErrorKind.TIMEOUT, self._provider, self._model) from None
        except httpx.TransportError:
            # SDK 建立连接后，读取响应流时可能直接抛出 HTTPX 传输错误。
            raise ChatBackendError(ChatErrorKind.CONNECTION, self._provider, self._model) from None
        except ValueError:
            raise ChatBackendError(
                ChatErrorKind.INCOMPLETE_RESPONSE, self._provider, self._model,
            ) from None

        # 遇到静默断流时可能已有正文，但缺少终止标记不能算成功。
        if finish_reason != "stop" or not has_text:
            raise ChatBackendError(ChatErrorKind.INCOMPLETE_RESPONSE, self._provider, self._model)
        yield "done", ""


def _messages(system: str, user: str) -> list[ChatCompletionMessageParam]:
    """构造两种调用共用的 Chat Completions 消息列表。

    :param system: 系统提示词。
    :param user: 用户消息。
    :returns: 按系统和用户顺序排列的 SDK 消息。
    """
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _error_kind(exc: APIError) -> ChatErrorKind:
    """归类 SDK 错误，避免将上游响应或请求细节放入异常消息。

    :param exc: SDK 在请求或流式迭代中抛出的异常。
    :returns: 可向调用方报告的接入错误类别。
    """
    # APITimeoutError 属于 APIConnectionError，先匹配超时。
    if isinstance(exc, APITimeoutError):
        return ChatErrorKind.TIMEOUT
    if isinstance(exc, APIConnectionError):
        return ChatErrorKind.CONNECTION
    if isinstance(exc, APIStatusError):
        if exc.status_code in (401, 403):
            return ChatErrorKind.AUTHENTICATION
        if exc.status_code == 429:
            return ChatErrorKind.RATE_LIMIT
        if exc.status_code in (408, 504):
            return ChatErrorKind.TIMEOUT
    return ChatErrorKind.UPSTREAM


def create_chat_backend(*, api_key: str, provider: str | None = None) -> ChatBackend:
    """按集中配置创建可独立使用的文本模型后端。

    :param api_key: 调用方提供的渠道密钥。
    :param provider: 配置中的渠道名，为 None 时使用 llm.default_provider。
    :returns: 已绑定渠道和模型的文本后端。
    :raises ChatBackendError: 密钥为空、渠道未知或渠道配置无效。
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ChatBackendError(ChatErrorKind.CONFIGURATION)

    try:
        config = load_config_section("llm")
        # 显式选择优先于配置默认值。空字符串是无效渠道，不会静默回退。
        selected = config["default_provider"] if provider is None else provider
        settings = config["providers"][selected]
        model = settings["model"]
        base_url = settings["base_url"]
        timeout = config["timeout_seconds"]
        extra = settings.get("extra_body", {})
        url = urlsplit(base_url)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        raise ChatBackendError(ChatErrorKind.CONFIGURATION) from None

    # 扩展字段仅用于配置供应商选项，避免覆盖后端管理的请求字段。
    if (
        not isinstance(model, str) or not model.strip()
        or url.scheme != "https" or not url.hostname or url.username is not None
        or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
        or not isinstance(extra, dict)
        or {"model", "messages", "stream", "stream_options"}.intersection(extra)
    ):
        raise ChatBackendError(ChatErrorKind.CONFIGURATION)

    # 每次调用只提交一次，由调用方决定是否重试可能已计费的请求。
    client = OpenAI(api_key=api_key.strip(), base_url=base_url, timeout=timeout, max_retries=0)
    return _OpenAIChatBackend(client, selected, model, extra)
