"""通过模拟 HTTP 响应验证渠道配置、流式协议和错误边界。"""

import json
import os
import tempfile
import unittest
from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
from openai import OpenAI

from integration.llm import ChatBackend, ChatBackendError, ChatErrorKind, ChatModelInfo, create_chat_backend, prepare_chat_backend

FAKE_KEY = "private-test-key"
PRIVATE_UPSTREAM_BODY = "private-upstream-body"


def _completion(content: str | None, finish: str = "stop") -> httpx.Response:
    """构造用于验证普通调用的供应商响应。

    :param content: 正文内容，为 None 时模拟响应缺少正文。
    :param finish: 生成结束原因，默认表示正常结束。
    :returns: 可供 HTTPX 模拟传输返回的响应。
    """
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
    })


def _frame(
    delta: dict | None = None, finish: str | None = None,
) -> bytes:
    """构造一帧 Chat Completions 流式响应。

    :param delta: 变化字段，为 None 时生成无 choices 的用量帧。
    :param finish: 生成结束原因，为 None 时表示尚无结束原因。
    :returns: 带有 SSE 分隔符的 UTF-8 字节串。
    """
    payload = {
        "choices": [] if delta is None else [
            {"index": 0, "delta": delta, "finish_reason": finish},
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


class _InterruptedStream(httpx.SyncByteStream):
    """模拟已经返回一段正文后连接读失败的 SSE 响应。"""

    closed = False

    def __iter__(self) -> Iterator[bytes]:
        """返回首个 SSE 事件后抛出传输错误。

        :returns: 首帧字节流。
        :raises httpx.ReadError: 读取首帧后模拟连接中断。
        """
        yield _frame({"content": "第一段"})
        raise httpx.ReadError(PRIVATE_UPSTREAM_BODY)

    def close(self) -> None:
        """标记底层响应流已被关闭。"""
        self.closed = True


class ChatBackendTests(unittest.TestCase):
    """使用真实 OpenAI SDK 和模拟传输验证模型接入，无需凭据或网络。"""

    def _backend(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        provider: str | None = None,
        *,
        model: str | None = None,
    ) -> ChatBackend:
        """构造由 HTTPX 模拟传输提供响应的后端。

        :param handler: 拦截并处理 HTTP 请求的函数。
        :param provider: 显式选择的渠道，为 None 时使用配置默认值。
        :param model: 显式选择的模型，为 None 时使用该渠道的第一个模型。
        :returns: 使用测试凭据和模拟传输的模型后端。
        """
        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http_client.close)
        with patch("integration.llm.client.OpenAI", wraps=OpenAI) as sdk:
            sdk.side_effect = lambda **options: OpenAI(http_client=http_client, **options)
            backend = create_chat_backend(api_key=FAKE_KEY, provider=provider, model=model)
            self.assertEqual(sdk.call_args.kwargs["timeout"], 120)
        return backend

    def test_channel_selection_and_request_format(self) -> None:
        """验证缺省走 DeepSeek，显式选择走 TokenHub，且参数在 SDK 层正确透传。"""
        cases = (
            (None, "https://api.deepseek.com/chat/completions", "deepseek-flash", {}),
            (
                "tokenhub", "https://tokenhub.tencentmaas.com/v1/chat/completions",
                "hy4-flash", {"reasoning_effort": "no_think"},
            ),
        )
        for provider, url, model, extra in cases:
            with self.subTest(provider=provider):
                def respond(request: httpx.Request) -> httpx.Response:
                    """验证请求地址、鉴权、消息和扩展字段。

                    :param request: SDK 实际生成的 HTTP 请求。
                    :returns: 固定的正常响应。
                    """
                    self.assertEqual(str(request.url), url)
                    self.assertEqual(request.headers["Authorization"], f"Bearer {FAKE_KEY}")
                    self.assertEqual(json.loads(request.content), {
                        "model": model,
                        "messages": [{"role": "system", "content": "系统"},
                                     {"role": "user", "content": "问题"}],
                        **extra,
                    })
                    return _completion(" 保留空白 ")

                # 切换工作目录，确认配置总是来自包资源。
                with tempfile.TemporaryDirectory() as directory:
                    original = os.getcwd()
                    try:
                        os.chdir(directory)
                        backend = self._backend(respond, provider)
                    finally:
                        os.chdir(original)
                    self.assertEqual(backend.chat("系统", "问题"), " 保留空白 ")

    def test_explicit_model_is_sent_for_selected_provider(self) -> None:
        """同一供应商登记多个模型时，请求使用明确指定的模型。"""
        config = {
            "timeout_seconds": 120,
            "providers": {"example": {"base_url": "https://example.test", "models": ["first", "second"]}},
        }

        def respond(request: httpx.Request) -> httpx.Response:
            """验证 SDK 请求中包含显式选择的模型。

            :param request: SDK 实际生成的 HTTP 请求。
            :returns: 固定的正常响应。
            """
            self.assertEqual(json.loads(request.content)["model"], "second")
            return _completion("成功")

        with patch("integration.llm.client.load_config_section", return_value=config):
            backend = self._backend(respond, "example", model="second")
            self.assertEqual(backend.chat("系统", "问题"), "成功")

    def test_model_probe_uses_short_prompt_and_same_backend(self) -> None:
        """探测使用固定短提示，正式请求复用选中的模型及客户端。"""
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            """保存请求供探测与正式调用的对比。

            :param request: SDK 发出的模拟请求。
            :returns: 固定的正常响应。
            """
            requests.append((str(request.url), json.loads(request.content)))
            return _completion("OK")

        with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
            with patch("integration.llm.client.OpenAI", side_effect=lambda **options: OpenAI(http_client=http_client, **options)):
                backend = prepare_chat_backend(api_key=FAKE_KEY, selection=ChatModelInfo("deepseek", "deepseek-flash"))
                self.assertEqual(backend.chat("纠错", "字幕原文"), "OK")

        (probe_url, probe), (completion_url, completion) = requests
        self.assertEqual(probe_url, completion_url)
        self.assertEqual(probe["model"], completion["model"])
        self.assertEqual(probe["max_tokens"], 16)
        self.assertEqual(probe["thinking"], {"type": "disabled"})
        self.assertEqual(probe["messages"][-1]["content"], "连接检查")
        self.assertNotIn("thinking", completion)
        self.assertEqual(completion["messages"][-1]["content"], "字幕原文")

    def test_rejects_missing_key_and_unknown_provider(self) -> None:
        """验证缺少密钥和无效渠道会在构造 SDK 之前报错。"""
        cases = ((" ", None), (FAKE_KEY, "unknown"), (FAKE_KEY, ""))
        for api_key, provider in cases:
            with self.subTest(provider=provider), patch("integration.llm.client.OpenAI") as sdk:
                with self.assertRaises(ChatBackendError) as caught:
                    create_chat_backend(api_key=api_key, provider=provider)
                self.assertEqual(caught.exception.kind, ChatErrorKind.CONFIGURATION)
                sdk.assert_not_called()

    def test_stream_returns_reasoning_text_usage_heartbeat_and_done(self) -> None:
        """验证 SDK 透传思考和正文，以及用量帧后流能正常结束。"""
        content = b"".join((
            _frame({"reasoning_content": "思考"}), _frame({"content": "第一段"}),
            _frame({"content": "第二段"}), _frame({}, "stop"), _frame(), b"data: [DONE]\n\n",
        ))

        def respond(request: httpx.Request) -> httpx.Response:
            """验证流式请求参数并发送模拟 SSE 响应。

            :param request: SDK 发出的流式 HTTP 请求。
            :returns: 包含正常结束标记的流式响应。
            """
            body = json.loads(request.content)
            self.assertTrue(body["stream"])
            self.assertEqual(body["stream_options"], {"include_usage": True})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)

        events = list(self._backend(respond).chat_stream("系统", "问题"))
        self.assertEqual(events, [
            ("reasoning", "思考"), ("text", "第一段"), ("text", "第二段"), ("ping", ""), ("done", ""),
        ])

    def test_maps_sdk_errors_without_exposing_upstream_details(self) -> None:
        """验证鉴权、限流、超时和上游出错可区分，且只提交一次请求。"""
        cases = (
            (401, ChatErrorKind.AUTHENTICATION), (403, ChatErrorKind.AUTHENTICATION),
            (429, ChatErrorKind.RATE_LIMIT), (408, ChatErrorKind.TIMEOUT),
            (500, ChatErrorKind.UPSTREAM), (None, ChatErrorKind.TIMEOUT),
        )
        for status, expected_kind in cases:
            with self.subTest(status=status):
                requests = []

                def respond(request: httpx.Request) -> httpx.Response:
                    """模拟上游错误，保留待验证的私有标记。

                    :param request: SDK 生成的请求。
                    :returns: 含模拟私有消息的失败响应。
                    :raises httpx.ReadTimeout: 没有 HTTP 状态码时模拟读取超时。
                    """
                    requests.append(request)
                    if status is None:
                        raise httpx.ReadTimeout(PRIVATE_UPSTREAM_BODY, request=request)
                    return httpx.Response(status, json={"error": {"message": PRIVATE_UPSTREAM_BODY}})

                with self.assertRaises(ChatBackendError) as caught:
                    self._backend(respond).chat("系统", "问题")
                self.assertEqual(caught.exception.kind, expected_kind)
                self.assertEqual(caught.exception.provider, "deepseek")
                self.assertEqual(caught.exception.model, "deepseek-flash")
                self.assertNotIn(PRIVATE_UPSTREAM_BODY, str(caught.exception))
                self.assertNotIn(FAKE_KEY, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertEqual(len(requests), 1)

    def test_rejects_incomplete_plain_responses(self) -> None:
        """验证非模型响应、空白正文和截断正文均不作为完整结果返回。"""
        responses = (
            httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Gateway</p>"),
            httpx.Response(200, json={"choices": []}),
            _completion(None), _completion(" "), _completion("只有前半段", "length"),
        )
        for response in responses:
            with self.subTest(response=response.content):
                with self.assertRaises(ChatBackendError) as caught:
                    self._backend(self._return_response(response)).chat("系统", "问题")
                self.assertEqual(caught.exception.kind, ChatErrorKind.INCOMPLETE_RESPONSE)

    def test_rejects_incomplete_streams(self) -> None:
        """验证没有正文、静默断流和截断三种情况均不会发送 done。"""
        cases = (
            _frame({"reasoning_content": "思考"}) + _frame({}, "stop"),
            _frame({"content": "只有前半段"}),
            _frame({"content": "只有前半段"}) + _frame({}, "length"),
        )
        for content in cases:
            with self.subTest(content=content):
                response = httpx.Response(200, content=content)
                events = []
                backend = self._backend(self._return_response(response))
                with self.assertRaises(ChatBackendError) as caught:
                    events.extend(backend.chat_stream("系统", "问题"))
                self.assertEqual(caught.exception.kind, ChatErrorKind.INCOMPLETE_RESPONSE)
                self.assertNotIn(("done", ""), events)

    def test_stream_read_failure_is_raised_and_stream_is_closed(self) -> None:
        """验证已读部分正文后的连接错误可处理，并释放底层响应流。"""
        source = _InterruptedStream()
        response = httpx.Response(200, stream=source)
        backend = self._backend(self._return_response(response))
        stream = backend.chat_stream("系统", "问题")
        self.assertEqual(next(stream), ("text", "第一段"))
        with self.assertRaises(ChatBackendError) as caught:
            next(stream)
        self.assertEqual(caught.exception.kind, ChatErrorKind.CONNECTION)
        self.assertNotIn(PRIVATE_UPSTREAM_BODY, str(caught.exception))
        self.assertTrue(source.closed)

    @staticmethod
    def _return_response(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
        """将固定 HTTP 响应包装为模拟请求处理器。

        :param response: 模拟传输应返回的响应。
        :returns: 忽略请求内容并返回指定响应的函数。
        """
        def respond(request: httpx.Request) -> httpx.Response:
            """返回指定的模拟响应。

            :param request: 被拦截的请求，当前用例不检查其内容。
            :returns: 预先构造的响应。
            """
            return response

        return respond
