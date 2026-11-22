"""通过模拟 faster-whisper 和 OpenCC 验证识别适配。"""

import sys
import unittest
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integration.converter import SubtitleSegment, TranscriptionError, WhisperConfig, WhisperTranscriber


def _interrupted_segments() -> Iterator[SimpleNamespace]:
    """模拟模型返回一个片段后，在惰性迭代期间报告解码失败。

    :returns: 模拟模型响应的生成器。
    :raises RuntimeError: 读取第一个片段后的模拟解码错误。
    """
    yield SimpleNamespace(start=0.2, end=0.6, text="部分结果")
    raise RuntimeError("decoding failed")


class WhisperTest(unittest.TestCase):
    """模拟模型与词典依赖，检查转录契约和完整结果交付。"""

    def test_model_is_lazy_and_preserves_segment_positions(self) -> None:
        """模型延迟初始化并复用，提示词与热词由调用方提供。"""
        model_factory = Mock()
        model = model_factory.return_value
        model.transcribe.return_value = ([
            SimpleNamespace(start=1.25, end=2.75, text="  現金流  "),
            SimpleNamespace(start=3, end=4, text=" "),
        ], None)
        opencc_factory = Mock()
        opencc_factory.return_value.convert.return_value = "现金流"
        dependencies = {
            "faster_whisper": SimpleNamespace(WhisperModel=model_factory),
            "opencc": SimpleNamespace(OpenCC=opencc_factory),
        }
        with TemporaryDirectory() as directory, patch.dict(sys.modules, dependencies):
            source = Path(directory) / "audio.wav"
            source.touch()
            transcriber = WhisperTranscriber(WhisperConfig("tiny", "cpu", "int8"))
            model_factory.assert_not_called()

            result = transcriber.transcribe(source, language="zh", initial_prompt="语音内容",
                                            hotwords=["现金流", "ROE"], simplify_chinese=True)
            self.assertEqual(result, (SubtitleSegment(1.25, 2.75, "现金流"),))
            self.assertEqual(model.transcribe.call_args.kwargs["hotwords"], "现金流 ROE")
            self.assertEqual(model.transcribe.call_args.kwargs["initial_prompt"], "语音内容")
            self.assertEqual(model.transcribe.call_args.kwargs["language"], "zh")
            opencc_factory.assert_called_once_with("t2s")

            self.assertEqual(transcriber.transcribe(source), (SubtitleSegment(1.25, 2.75, "現金流"),))
            self.assertIsNone(model.transcribe.call_args.kwargs["hotwords"])
            self.assertIsNone(model.transcribe.call_args.kwargs["language"])
            model_factory.assert_called_once_with("tiny", device="cpu", compute_type="int8")

    def test_decode_failure_after_first_segment_is_reported(self) -> None:
        """迭代中途失败时抛出统一错误，使调用方避免保存部分结果。"""
        model_factory = Mock()
        model_factory.return_value.transcribe.return_value = (_interrupted_segments(), None)
        dependencies = {"faster_whisper": SimpleNamespace(WhisperModel=model_factory)}
        with TemporaryDirectory() as directory, patch.dict(sys.modules, dependencies):
            source = Path(directory) / "audio.wav"
            source.touch()
            with self.assertRaises(TranscriptionError) as error:
                WhisperTranscriber().transcribe(source)
            self.assertIsInstance(error.exception.__cause__, RuntimeError)

    def test_missing_optional_dependency_is_reported_at_conversion(self) -> None:
        """创建转录器不依赖 SDK，首次调用时将缺失依赖转为可处理的错误。"""
        with TemporaryDirectory() as directory, patch.dict(sys.modules, {"faster_whisper": None}):
            source = Path(directory) / "audio.wav"
            source.touch()
            transcriber = WhisperTranscriber()
            with self.assertRaisesRegex(TranscriptionError, "transcription"):
                transcriber.transcribe(source)
