"""以模拟远端和真实文件仓储验证新 CLI 的装配。"""

import asyncio
import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from ingestion.entity import Platform
from ingestion.interaction.cli.bootstrap import run_cli
from ingestion.service import AvatarPlatformParam, CreateAvatarParam
from ingestion.service.avatar.impl.avatar_service_impl import AvatarServiceImpl
from ingestion.storage.impl.local_file.avatar_repository_impl import AvatarRepositoryImpl
from ingestion.storage.impl.local_file.material_repository_impl import MaterialRepositoryImpl
from integration.converter import SubtitleSegment
from integration.fetcher.bilibili import CollectionKind, VideoInfo, VideoPage
from integration.fetcher.error import FetchError
from integration.llm import ChatModelInfo

_VIDEO = "BV1xx411c7mD"
_OTHER_VIDEO = "BV1xx411c7mE"


class BootstrapTest(TestCase):
    """验证命令在进程调用之间可通过文件索引继续工作。"""

    def setUp(self) -> None:
        """创建独立数据目录，使用服务完成一次博主登记。"""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        data = self.root / "data" / "ingestion"
        self.repository = MaterialRepositoryImpl(data)
        service = AvatarServiceImpl(AvatarRepositoryImpl(data), self.repository)
        self.avatar = asyncio.run(service.create_avatar(CreateAvatarParam(
            "示例作者", [AvatarPlatformParam(Platform.BILIBILI, "https://space.bilibili.com/42/video")],
        )))
        self.remote_args = ["--avatar-id", str(self.avatar.id), "--platform", "bilibili"]

    def test_collect_process_recollect(self) -> None:
        """验证远端分页、批量失败、加工重试和重采使旧加工稿失效。"""
        video = VideoInfo(_VIDEO, "示例视频", "作者", 1_700_000_000, 3, "https://www.bilibili.com/video/BV1xx411c7mD", 42)
        remote = Mock(
            list_collection_videos=AsyncMock(return_value=VideoPage((video,), 2, 1, 5, 3)),
            get_video=AsyncMock(side_effect=[replace(video, bvid=_OTHER_VIDEO, author_mid=99), video]),
            download_audio=AsyncMock(),
        )
        transcriber = Mock()
        transcriber.transcribe.return_value = (SubtitleSegment(0, 2, "原始字幕"),)
        backend = Mock()
        backend.chat.return_value = json.dumps({
            "sections": [{"heading": "主题", "start_time": 0.0, "end_time": 2.0, "text": "优化字幕"}],
            "global_keywords": ["示例"],
        })
        with (
            patch("integration.fetcher.bilibili.BilibiliFetcher", return_value=remote) as fetcher,
            patch("ingestion.interaction.cli.bootstrap.extract_audio"),
            patch("ingestion.interaction.cli.bootstrap.WhisperTranscriber", return_value=transcriber),
            patch("ingestion.interaction.cli.bootstrap.create_configured_chat_backend", return_value=backend),
        ):
            self.assertEqual(self._run("avatar", "list")[0], 0)
            fetcher.assert_not_called()
            code, out, _ = self._run("material", "list-remote", *self.remote_args,
                                    "--page", "2", "--page-size", "1", "--collection-key", "series:18")
            self.assertEqual(code, 0)
            self.assertIn(_VIDEO, out)
            remote.list_collection_videos.assert_awaited_once_with(42, 18, kind=CollectionKind.SERIES, page=2, page_size=1)
            fetcher.assert_called_with(session_dir=self.root / ".sessions")

            code, out, err = self._run("material", "batch-collect", *self.remote_args,
                                      "--source-key", _OTHER_VIDEO, "--source-key", _VIDEO)
            self.assertEqual(code, 1)
            self.assertIn(_OTHER_VIDEO, err)
            self.assertIn(_VIDEO, out)
            remote.download_audio.assert_awaited_once()
            original = self.repository.get(self.avatar.id, Platform.BILIBILI, _VIDEO)
            material_id = str(original.id)
            self.assertEqual(self._run("material", "process", "--material-id", material_id)[0], 0)
            optimized = self.repository.get_by_id(original.id)
            self.assertEqual(optimized.optimized_segments[0].text, "优化字幕")
            self.assertEqual(optimized.global_keywords, ("示例",))
            self.assertEqual(self._run("material", "process", "--material-id", material_id)[0], 0)
            backend.chat.assert_called_once()

            backend.chat.return_value = "无效响应"
            self.assertEqual(self._run("material", "process", "--material-id", material_id, "--no-skip-existing")[0], 1)
            self.assertEqual(self.repository.get_by_id(original.id), optimized)

            collect = ("material", "collect", *self.remote_args, "--source-key", _VIDEO)
            self.assertEqual(self._run(*collect)[0], 0)
            remote.download_audio.assert_awaited_once()
            remote.get_video.side_effect = None
            remote.get_video.return_value = video
            remote.download_audio.side_effect = FetchError("模拟下载失败")
            self.assertEqual(self._run(*collect, "--no-skip-existing")[0], 1)
            self.assertEqual(self.repository.get_by_id(original.id), optimized)
            remote.download_audio.side_effect = None
            self.assertEqual(self._run(*collect, "--no-skip-existing")[0], 0)
            self.assertEqual(self.repository.get_by_id(original.id), optimized)

            transcriber.transcribe.return_value = (SubtitleSegment(0, 2, "重采后的字幕"),)
            self.assertEqual(self._run(*collect, "--no-skip-existing")[0], 0)
            updated = self.repository.get_by_id(original.id)
            self.assertEqual(updated.created_at, original.created_at)
            self.assertNotEqual(updated.content_hash, original.content_hash)
            self.assertEqual(updated.optimized_segments, [])
            self.assertEqual(updated.global_keywords, ())
            self.assertIn("重采后的字幕", self._run("material", "show", "--material-id", material_id)[1])

    def test_collect_and_process_uses_selected_model(self) -> None:
        """一次命令将指定模型交给加工服务，并同时保存两份字幕。"""
        video = VideoInfo(_VIDEO, "示例", "作者", None, 2, f"https://example.test/{_VIDEO}", 42)
        remote = Mock(get_video=AsyncMock(return_value=video), download_audio=AsyncMock())
        transcriber = Mock()
        transcriber.transcribe.return_value = (SubtitleSegment(0, 2, "原稿"),)
        backend = Mock()
        backend.chat.return_value = json.dumps({
            "sections": [{"heading": "主题", "start_time": 0.0, "end_time": 2.0, "text": "加工稿"}],
        })
        with (
            patch("integration.fetcher.bilibili.BilibiliFetcher", return_value=remote),
            patch("ingestion.interaction.cli.bootstrap.extract_audio"),
            patch("ingestion.interaction.cli.bootstrap.WhisperTranscriber", return_value=transcriber),
            patch("ingestion.interaction.cli.bootstrap.create_configured_chat_backend", return_value=backend) as create_backend,
        ):
            code, out, _ = self._run(
                "material", "collect-and-process", *self.remote_args, "--source-key", _VIDEO,
                "--provider", "tokenhub", "--model", "hy4-flash",
            )
        self.assertEqual(code, 0)
        self.assertIn("采集\n", out)
        self.assertIn("加工\n", out)
        self.assertEqual(out.count("成功"), 2)
        create_backend.assert_called_once_with(
            project_root=self.root, selection=ChatModelInfo("tokenhub", "hy4-flash"), probe=True,
        )
        stored = self.repository.get(self.avatar.id, Platform.BILIBILI, _VIDEO)
        self.assertEqual(stored.raw_segments[0].text, "原稿")
        self.assertEqual(stored.optimized_segments[0].text, "加工稿")

    def test_logging_correlates_cli_service_and_storage(self) -> None:
        """检查同一命令在工作线程上沿用运行 ID，异常日志过滤远端内容。"""
        config = self.root / "core" / "config.toml"
        config.parent.mkdir()
        config.write_text('[logging]\nlevel = "DEBUG"\n', encoding="utf-8")
        remote = Mock(get_video=AsyncMock(side_effect=FetchError("sensitive-upstream-placeholder")))
        with patch("integration.fetcher.bilibili.BilibiliFetcher", return_value=remote):
            code, _, _ = self._run("material", "collect", *self.remote_args, "--source-key", _VIDEO)
        self.assertEqual(code, 1)
        logs = self.root / "logs" / "ingestion"
        app = next(logs.glob("app-*.log")).read_text(encoding="utf-8")
        errors = next(logs.glob("error-*.log")).read_text(encoding="utf-8")
        self.assertIn("命令开始 command=material collect", app)
        self.assertIn("博主索引读取", app)
        self.assertIn("按来源读取资料", app)
        self.assertIn(f"采集失败 source_key={_VIDEO} stage=get_video error_type=FetchError", errors)
        self.assertIn("命令结束 command=material collect exit_code=1", app)
        self.assertNotIn("sensitive-upstream-placeholder", app + errors)
        self.assertEqual(len(set(re.findall(r"run_id=([0-9a-f]{32})", app + errors))), 1)

    def _run(self, *argv: str) -> tuple[int, str, str]:
        """通过实际装配入口运行一个命令并捕获输出。

        :param argv: CLI 参数。
        :returns: 退出码、标准输出和标准错误。
        """
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run_cli(argv, project_root=self.root)
        return code, out.getvalue(), err.getvalue()
