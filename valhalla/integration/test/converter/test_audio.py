"""验证 FFmpeg 参数、配置覆盖及文件提交边界。"""

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from valhalla.integration.converter import AudioConversionError, FFmpegConfig, extract_audio

_RUN = "valhalla.integration.converter.audio.subprocess.run"


def _write_output(command: list[str], **options: object) -> subprocess.CompletedProcess:
    """模拟 FFmpeg 成功生成临时文件。

    :param command: FFmpeg 参数列表，最后一个参数为输出路径。
    :param options: subprocess.run 的调用选项。
    :returns: 退出码为零的进程结果。
    """
    Path(command[-1]).write_bytes(b"new wav")
    return subprocess.CompletedProcess(command, 0)


def _fail_after_writing(command: list[str], **options: object) -> None:
    """模拟 FFmpeg 写入部分文件后失败。

    :param command: FFmpeg 参数列表，最后一个参数为输出路径。
    :param options: subprocess.run 的调用选项。
    :raises subprocess.CalledProcessError: 模拟媒体中没有可用音轨。
    """
    Path(command[-1]).write_bytes(b"partial wav")
    raise subprocess.CalledProcessError(1, command, stderr="no audio stream")


class AudioTest(unittest.TestCase):
    """隔离 FFmpeg 进程，验证调用者可观测的配置、结果和失败状态。"""

    def test_extract_uses_override_and_replaces_output(self) -> None:
        """采用配置覆盖项，成功后提交转换结果并清理临时目录。"""
        with TemporaryDirectory() as directory, patch(_RUN, side_effect=_write_output) as run:
            root = Path(directory)
            source, target = root / "video file.mp4", root / "audio.wav"
            source.write_bytes(b"input")
            target.write_bytes(b"existing wav")
            override = root / "settings.toml"
            override.write_text('[ffmpeg]\nexecutable = "custom-ffmpeg"\nsample_rate = 8000\n', encoding="utf-8")

            self.assertEqual(extract_audio(source, target, config=FFmpegConfig.load(override)), target)

            command = run.call_args.args[0]
            self.assertEqual(command[0], "custom-ffmpeg")
            self.assertEqual(command[command.index("-map") + 1], "0:a:0")
            self.assertEqual(command[command.index("-ar") + 1], "8000")
            self.assertEqual(run.call_args.kwargs["timeout"], 600)
            self.assertEqual(target.read_bytes(), b"new wav")
            self.assertFalse(Path(command[-1]).parent.exists())

    def test_error_keeps_existing_output(self) -> None:
        """FFmpeg 失败后保留调用方已有的产物，并删除部分输出。"""
        with TemporaryDirectory() as directory, patch(_RUN, side_effect=_fail_after_writing) as run:
            root = Path(directory)
            source, target = root / "video.mp4", root / "audio.wav"
            source.write_bytes(b"input")
            target.write_bytes(b"existing wav")

            with self.assertRaisesRegex(AudioConversionError, "no audio stream"):
                extract_audio(source, target)

            self.assertEqual(target.read_bytes(), b"existing wav")
            self.assertFalse(Path(run.call_args.args[0][-1]).parent.exists())

    def test_timeout_leaves_no_output(self) -> None:
        """转换超时可以单独识别，且没有可被误读为完整结果的文件。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "video.mp4", root / "audio.wav"
            source.touch()
            with patch(_RUN, side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
                with self.assertRaisesRegex(AudioConversionError, "1 秒"):
                    extract_audio(source, target, config=FFmpegConfig("ffmpeg", 16000, 1))
            self.assertEqual(list(root.iterdir()), [source])

    def test_rejects_source_as_destination(self) -> None:
        """调用方不能将输入文件自身作为转换目标。"""
        with TemporaryDirectory() as directory, patch(_RUN) as run:
            source = Path(directory) / "audio.wav"
            source.write_bytes(b"input")
            with self.assertRaises(ValueError):
                extract_audio(source, source)
            run.assert_not_called()
            self.assertEqual(source.read_bytes(), b"input")
