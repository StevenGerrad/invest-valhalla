"""用 DTO 模拟模型请求与响应，验证独立字幕 Agent。"""

import json
from unittest import TestCase
from unittest.mock import Mock

from integration.llm import ChatBackendError, ChatErrorKind, ChatRequest, ChatResponse
from ingestion.common.dto.subtitle.subtitle_dto import (
    ProcessedSubtitleInfo,
    SubtitleProcessParam,
    SubtitleSegmentInfo,
)
from ingestion.entity.agent import SubtitleProcessAgent


def _response(*ranges: tuple[int, int]) -> ChatResponse:
    """模拟模型根据原始编号组织整份字幕的话题段。

    :param ranges: 各段覆盖的原始片段编号范围，两端均包含。
    :returns: 可用于测试的模型响应 DTO。
    """
    return ChatResponse(json.dumps({
        "sections": [{
            "start_id": start, "end_id": end, "text": "  保留正文。  ",
        } for start, end in ranges],
        "global_keywords": ["行业", "市场", " 市场 ", "政策"],
    }))


class SubtitleProcessAgentTest(TestCase):
    """验证整稿请求、原稿片段覆盖和模型失败处理。"""

    def test_processes_full_transcript_and_merges_across_old_boundary(self) -> None:
        """一次提交所有原稿，允许模型合并跨过旧分界的同一话题。"""
        invoke = Mock(return_value=_response((1, 17), (18, 21)))
        original = [SubtitleSegmentInfo(index, index + 1, f"原稿 {index}") for index in range(21)]
        result = SubtitleProcessAgent(invoke).process(SubtitleProcessParam("示例视频", original))

        invoke.assert_called_once()
        request = invoke.call_args.args[0]
        self.assertIsInstance(request, ChatRequest)
        self.assertIn("通读整份", request.system)
        self.assertIn("不要概括", request.system)
        self.assertNotIn('"heading"', request.system)
        self.assertNotIn('"keywords"', request.system)
        self.assertEqual(
            json.loads(request.user),
            {"title": "示例视频", "segments": [
                {"id": i + 1, "start": i, "end": i + 1, "text": f"原稿 {i}"} for i in range(21)
            ]},
        )
        self.assertEqual(result, ProcessedSubtitleInfo([
            SubtitleSegmentInfo(0, 17, "保留正文。"),
            SubtitleSegmentInfo(17, 21, "保留正文。"),
        ], ["行业", "市场", "政策"]))

    def test_uses_latest_source_end_for_overlapping_segments(self) -> None:
        """按原稿恢复时间，覆盖范围内较早开始的片段也可能最后结束。"""
        invoke = Mock(return_value=_response((1, 2)))
        param = SubtitleProcessParam(None, [SubtitleSegmentInfo(2, 8, "甲"), SubtitleSegmentInfo(3, 5, "乙")])
        result = SubtitleProcessAgent(invoke).process(param)
        self.assertEqual((result.segments[0].start_seconds, result.segments[0].end_seconds), (2, 8))

    def test_rejects_incomplete_or_overlapping_source_ranges(self) -> None:
        """拒绝漏开头、中间跳号、重复、越界、反向、错序或缺尾部的结果。"""
        param = SubtitleProcessParam(None, [SubtitleSegmentInfo(i, i + 1, "原稿") for i in range(4)])
        cases = (
            ((2, 4),), ((1, 2), (4, 4)), ((1, 2), (2, 4)), ((1, 5),),
            ((1, 0),), ((3, 4), (1, 2)), ((1, 3),), ((True, 4),),
        )
        for ranges in cases:
            with self.subTest(ranges=ranges):
                invoke = Mock(return_value=_response(*ranges))
                with self.assertRaisesRegex(ValueError, "原稿"):
                    SubtitleProcessAgent(invoke).process(param)
                invoke.assert_called_once()

    def test_invalid_json_fails_without_another_model_request(self) -> None:
        """响应格式无效时直接报告失败，避免重复发送整份原稿。"""
        invoke = Mock(return_value=ChatResponse('{"sections":['))
        param = SubtitleProcessParam(None, [SubtitleSegmentInfo(0, 1, "原稿")])
        with self.assertRaises(json.JSONDecodeError):
            SubtitleProcessAgent(invoke).process(param)
        invoke.assert_called_once()

    def test_propagates_model_call_error(self) -> None:
        """将模型调用异常原样交回调用方，避免将其当作响应格式错误。"""
        failure = ChatBackendError(ChatErrorKind.TIMEOUT)
        invoke = Mock(side_effect=failure)
        with self.assertRaises(ChatBackendError) as raised:
            SubtitleProcessAgent(invoke).process(SubtitleProcessParam(None, [SubtitleSegmentInfo(0, 1, "原稿")]))
        self.assertIs(raised.exception, failure)
        invoke.assert_called_once()

    def test_empty_and_invalid_input_do_not_call_model(self) -> None:
        """空原稿返回空结果，非法时间在提交整稿之前报错。"""
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
