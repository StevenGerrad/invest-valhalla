"""验证 B 站采集后加工能够复用原稿和现有字幕处理服务。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from integration.converter import SubtitleSegment
from integration.fetcher.bilibili import VideoInfo
from integration.llm import ChatBackendError, ChatErrorKind, resolve_chat_model
from ingestion.entity import Platform
from ingestion.service import (
    BatchCollectAndProcessMaterialParam,
    CollectAndProcessMaterialParam,
    IngestionError,
    ResultStatus,
)
from ingestion.service.material.impl.bilibili_subtitle.bilibili_subtitle_material_service_impl import (
    BilibiliSubtitleMaterialServiceImpl,
)
from ingestion.service.material_process.impl.subtitle.subtitle_material_process_service_impl import (
    SubtitleMaterialProcessServiceImpl,
)
from ingestion.storage.impl.local_file.avatar_repository_impl import AvatarRepositoryImpl
from ingestion.storage.impl.local_file.material_repository_impl import MaterialRepositoryImpl

_FIRST = "BV1hp4g6HEXz"
_SECOND = "BV1hp4g6HEXY"


class BilibiliSubtitleMaterialServiceTests(IsolatedAsyncioTestCase):
    """用本地仓储和模拟平台覆盖两阶段编排及模型选择。"""

    def setUp(self) -> None:
        """准备带独立临时仓储的采集和加工实例。"""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        avatars = AvatarRepositoryImpl(Path(directory.name))
        self.materials = MaterialRepositoryImpl(Path(directory.name))
        self.avatar = avatars.create("示例博主", ["https://space.bilibili.com/42"])
        self.fetcher = Mock(get_video=AsyncMock(side_effect=_video_info), download_audio=AsyncMock())
        self.backend = Mock()
        self.backend.chat.return_value = _processed_text("加工稿")
        self.prepare_backend = Mock(return_value=self.backend)
        processor = SubtitleMaterialProcessServiceImpl(
            self.materials, Mock(), selected_backend=self.prepare_backend,
        )
        self.service = BilibiliSubtitleMaterialServiceImpl(
            avatars, self.materials, lambda: self.fetcher, Mock(),
            Mock(return_value=(SubtitleSegment(0, 1, "原稿"),)),
            material_process_service=processor,
        )

    async def test_collect_skip_and_reprocess(self) -> None:
        """首次采集并加工，已有两稿时跳过，覆盖时将指定模型传到加工服务。"""
        first = await self.service.collect_and_process_material(
            self.avatar, Platform.BILIBILI, CollectAndProcessMaterialParam(_FIRST),
        )
        self.assertIs(first.collection.status, ResultStatus.SUCCESS)
        self.assertIs(first.processing.status, ResultStatus.SUCCESS)
        material_id = first.processing.material_id
        self.prepare_backend.assert_called_once_with(resolve_chat_model())

        skipped = await self.service.collect_and_process_material(
            self.avatar, Platform.BILIBILI, CollectAndProcessMaterialParam(_FIRST),
        )
        self.assertIs(skipped.collection.status, ResultStatus.SKIPPED)
        self.assertIs(skipped.processing.status, ResultStatus.SKIPPED)
        self.fetcher.download_audio.assert_awaited_once()
        self.backend.chat.assert_called_once()
        self.prepare_backend.assert_called_once()

        selection = resolve_chat_model(provider="tokenhub")
        self.backend.chat.return_value = _processed_text("重新加工稿")
        forced = await self.service.collect_and_process_material(
            self.avatar, Platform.BILIBILI,
            CollectAndProcessMaterialParam(_FIRST, model_selection=selection, skip_existing=False),
        )
        self.assertEqual(self.fetcher.download_audio.await_count, 2)
        self.prepare_backend.assert_called_with(selection)
        self.assertIs(forced.processing.status, ResultStatus.SUCCESS)
        self.assertEqual(forced.processing.material_id, material_id)
        self.assertEqual(self.materials.get_by_id(material_id).optimized_segments[0].text, "重新加工稿")

    async def test_batch_preserves_order_and_keeps_raw_on_failure(self) -> None:
        """采集失败不加工，加工失败保留原稿，后续及重复项保持原顺序。"""
        self.backend.chat.side_effect = [ChatBackendError(ChatErrorKind.UPSTREAM), _processed_text("成功")]
        results = await self.service.batch_collect_and_process_material(
            self.avatar, Platform.BILIBILI, BatchCollectAndProcessMaterialParam((_FIRST, "无效", _SECOND, _SECOND)),
        )
        self.assertEqual([entry.collection.source_key for entry in results], [_FIRST, "无效", _SECOND, _SECOND])
        self.assertIs(results[0].processing.status, ResultStatus.FAILED)
        self.assertIs(results[1].collection.status, ResultStatus.FAILED)
        self.assertIsNone(results[1].processing)
        self.assertIs(results[2].processing.status, ResultStatus.SUCCESS)
        self.assertIs(results[3].processing.status, ResultStatus.SKIPPED)
        self.prepare_backend.assert_called_once()
        first = self.materials.get_by_id(results[0].processing.material_id)
        self.assertEqual(first.raw_segments[0].text, "原稿")
        self.assertEqual(first.optimized_segments, [])

    async def test_failed_probe_is_shared_and_original_can_be_retried(self) -> None:
        """同批探测失败仅调用一次，之后可复用已保存的原稿单独重试加工。"""
        self.prepare_backend.side_effect = ChatBackendError(ChatErrorKind.AUTHENTICATION)
        results = await self.service.batch_collect_and_process_material(
            self.avatar, Platform.BILIBILI, BatchCollectAndProcessMaterialParam((_FIRST, _SECOND)),
        )
        self.assertEqual([item.processing.status for item in results], [ResultStatus.FAILED, ResultStatus.FAILED])
        self.prepare_backend.assert_called_once()
        self.backend.chat.assert_not_called()
        with self.assertRaisesRegex(IngestionError, "原稿已保存"):
            await self.service.collect_and_process_material(
                self.avatar, Platform.BILIBILI, CollectAndProcessMaterialParam(_FIRST),
            )

        self.prepare_backend.side_effect = None
        retried = await self.service.collect_and_process_material(
            self.avatar, Platform.BILIBILI, CollectAndProcessMaterialParam(_FIRST),
        )
        self.assertIs(retried.collection.status, ResultStatus.SKIPPED)
        self.assertIs(retried.processing.status, ResultStatus.SUCCESS)
        self.assertEqual(self.fetcher.download_audio.await_count, 2)


def _video_info(bvid: str) -> VideoInfo:
    """返回模拟的 B 站视频信息。

    :param bvid: 当前要采集的视频标识。
    :returns: 属于测试博主的视频。
    """
    return VideoInfo(bvid, bvid, "示例博主", None, 1, f"https://example.test/{bvid}", 42)


def _processed_text(text: str) -> str:
    """构造可由真实字幕处理器解析的模型响应。

    :param text: 加工稿正文。
    :returns: 位于原稿时间范围内的字幕 JSON。
    """
    return json.dumps({"sections": [{"heading": "主题", "start_time": 0, "end_time": 1, "text": text}]})
