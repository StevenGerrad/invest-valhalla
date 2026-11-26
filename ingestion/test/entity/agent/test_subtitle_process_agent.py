"""用 DTO 模拟模型请求与响应，验证独立字幕 Agent。"""

import json
from unittest import TestCase
from unittest.mock import Mock

from integration.llm import ChatBackendError, ChatErrorKind, ChatRequest, ChatResponse
from ingestion.common.dto.subtitle.subtitle_dto import (
    ProcessedSubtitleInfo,
    ProcessedSubtitleSegmentInfo,
    SubtitleProcessParam,
    SubtitleSegmentInfo,
)
from ingestion.entity.agent import SubtitleProcessAgent


def _response(start: float, end: float, global_keywords: list[str]) -> ChatResponse:
    """模拟模型把一批原稿合并为一个带语义信息的段落。

    :param start: 加工段落的开始时间，单位为秒。
    :param end: 加工段落的结束时间，单位为秒。
    :param global_keywords: 模型为本批返回的关键词。
    :returns: 可用于测试的模型响应 DTO。
    """
    return ChatResponse(json.dumps({
        "sections": [{
            "start_time": start, "end_time": end, "heading": "市场观察",
            "text": "  保留正文。  ", "keywords": [" 市场 ", ""],
        }],
        "global_keywords": global_keywords,
    }))


class SubtitleProcessAgentTest(TestCase):
    """验证数据契约、时间轴和模型失败处理。"""

    def test_process_batches_and_preserves_section_metadata(self) -> None:
        """按 20 加 1 分批发送，保留段落标题、关键词及原媒体时间。"""
        invoke = Mock(side_effect=[_response(0, 20, ["行业", "市场"]), _response(20, 21, [" 市场 ", "政策"])])
        original = [SubtitleSegmentInfo(index, index + 1, f"原稿 {index}") for index in range(21)]
        result = SubtitleProcessAgent(invoke).process(SubtitleProcessParam("示例视频", original))

        requests = [call.args[0] for call in invoke.call_args_list]
        for request in requests:
            self.assertIsInstance(request, ChatRequest)
            self.assertIn("按话题分段", request.system)
        batches = [json.loads(request.user) for request in requests]
        self.assertEqual([batch["title"] for batch in batches], ["示例视频", "示例视频"])
        self.assertEqual(
            [batch["segments"] for batch in batches],
            [[{"start": i, "end": i + 1, "text": f"原稿 {i}"} for i in range(20)],
             [{"start": 20, "end": 21, "text": "原稿 20"}]],
        )
        self.assertEqual(result, ProcessedSubtitleInfo([
            ProcessedSubtitleSegmentInfo(0.0, 20.0, "保留正文。", "市场观察", ("市场",)),
            ProcessedSubtitleSegmentInfo(20.0, 21.0, "保留正文。", "市场观察", ("市场",)),
        ], ["行业", "市场", "政策"]))

    def test_retries_invalid_responses(self) -> None:
        """依次重试无效 JSON 和超出批次的时间，第三次交付结果。"""
        invoke = Mock(side_effect=[ChatResponse("非 JSON"), _response(2, 8, []), _response(2, 3, [])])
        param = SubtitleProcessParam(None, [SubtitleSegmentInfo(2, 3, "原稿")])
        result = SubtitleProcessAgent(invoke).process(param)
        self.assertEqual(invoke.call_count, 3)
        self.assertTrue(all(call == invoke.call_args for call in invoke.call_args_list))
        self.assertEqual(result.segments[0].end_seconds, 3)

    def test_stops_after_three_invalid_responses(self) -> None:
        """第二批持续失败时报告错误，避免交付第一批的部分结果。"""
        invoke = Mock(side_effect=[_response(0, 20, []), *([ChatResponse("{}")] * 3)])
        param = SubtitleProcessParam(None, [SubtitleSegmentInfo(i, i + 1, "原稿") for i in range(21)])
        with self.assertRaisesRegex(ValueError, "字幕格式或时间范围无效"):
            SubtitleProcessAgent(invoke).process(param)
        self.assertEqual(invoke.call_count, 4)

    def test_propagates_model_call_error(self) -> None:
        """将模型调用异常原样交回调用方，避免将其当作响应格式错误。"""
        failure = ChatBackendError(ChatErrorKind.TIMEOUT)
        invoke = Mock(side_effect=failure)
        with self.assertRaises(ChatBackendError) as raised:
            SubtitleProcessAgent(invoke).process(SubtitleProcessParam(None, [SubtitleSegmentInfo(0, 1, "原稿")]))
        self.assertIs(raised.exception, failure)
        invoke.assert_called_once()

    def test_empty_and_invalid_input_do_not_call_model(self) -> None:
        """空原稿返回空结果，非法时间在提交任何批次之前报错。"""
        invoke = Mock()
        agent = SubtitleProcessAgent(invoke)
        self.assertEqual(agent.process(SubtitleProcessParam(None, [])), ProcessedSubtitleInfo([], []))
        for segments in (
            [SubtitleSegmentInfo(0, float("inf"), "时间无效")],
            [SubtitleSegmentInfo(2, 3, "后片段"), SubtitleSegmentInfo(0, 1, "前片段")],
        ):
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                agent.process(SubtitleProcessParam(None, segments))
        invoke.assert_not_called()
