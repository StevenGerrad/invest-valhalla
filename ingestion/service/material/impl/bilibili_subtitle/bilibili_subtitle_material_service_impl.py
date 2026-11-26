"""实现 B 站资料浏览、字幕采集及采集后加工。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import TYPE_CHECKING

from integration.converter import AudioConversionError, TranscriptionError, render_srt
from integration.converter import SubtitleSegment as TranscribedSegment
from integration.fetcher.address import parse_bilibili_collection_key, parse_bilibili_creator_url
from integration.fetcher.error import FetchError
from integration.llm import ChatModelInfo, resolve_chat_model

from ingestion.entity import AvatarIndex, MaterialEntity, MaterialIndex, Platform, SubtitleMaterialEntity, SubtitleSegment
from ingestion.service._batch import batch_delete, log_batch_results
from ingestion.service._support import repository_call
from ingestion.common.dto.material_dto import (
    BatchCollectMaterialParam, CollectMaterialParam, CollectionResult, DeletionResult,
    MaterialDetail, MaterialSelectionParam,
)
from ingestion.common.constant.result_status import ResultStatus
from ingestion.service.error import IngestionError
from ingestion.service.material_process.dto.material_process_service_dto import (
    BatchProcessMaterialParam, ProcessMaterialParam,
)
from ingestion.service.material_process.material_process_service import MaterialProcessService
from ingestion.storage import AvatarRepository, MaterialRepository

from ...dto.material_collect_and_process_service_dto import (
    BatchCollectAndProcessMaterialParam, CollectAndProcessMaterialParam, CollectAndProcessResult,
    RawAndProcessedMaterialDetail,
)
from ...dto.material_service_dto import ListRemoteMaterialsParam, MaterialListItem, MaterialPage, RawMaterialDetail
from ...material_collect_and_process_service import MaterialCollectAndProcessService
from ...material_service import MaterialService

if TYPE_CHECKING:
    from integration.fetcher.bilibili import BilibiliContentSource

logger = logging.getLogger(__name__)
_BVID = re.compile(r"BV[0-9A-Za-z]{10}")


class BilibiliSubtitleMaterialServiceImpl(MaterialService, MaterialCollectAndProcessService):
    """管理 B 站字幕采集，并将已保存的原稿交给独立加工服务。"""

    def __init__(
        self,
        avatars: AvatarRepository,
        materials: MaterialRepository,
        source: Callable[[], BilibiliContentSource],
        convert_audio: Callable[[Path, Path], object],
        transcribe: Callable[[Path], tuple[TranscribedSegment, ...]],
        *,
        material_process_service: MaterialProcessService | None = None,
    ) -> None:
        """接收仓储和可独立替换的媒体能力。

        :param avatars: 用于查找已登记账号的仓储。
        :param materials: 完整资料仓储。
        :param source: 在首次访问远端时构造 B 站能力的函数。
        :param convert_audio: 将源音轨转换到指定 WAV 路径的函数。
        :param transcribe: 将 WAV 文件转录成带时间字幕的函数。
        :param material_process_service: 处理原稿的服务。为 None 时仅提供独立采集。
        """
        self._avatars = avatars
        self._materials = materials
        self._source = source
        self._convert_audio = convert_audio
        self._transcribe = transcribe
        self._material_process_service = material_process_service

    async def list_remote_materials(
        self, avatar_index: AvatarIndex, platform: Platform, param: ListRemoteMaterialsParam | None = None,
    ) -> MaterialPage:
        """读取一页投稿或指定合集的资料。

        :param avatar_index: 作者的本地索引。
        :param platform: 已登记的来源平台。
        :param param: 分页和合集选项。为 None 时读取普通投稿的首页。
        :returns: 可供采集的条目及下一页。
        :raises KeyError: 找不到作者或平台登记。
        :raises ValueError: 平台、合集或分页无效。
        :raises IngestionError: 无法读取远端资料。
        """
        started = perf_counter()
        author_id = avatar_index.get_avatar_index()
        mid = await self._creator_mid(author_id, platform)
        options = param or ListRemoteMaterialsParam()
        try:
            source = self._source()
            if options.collection_key is None:
                page = await source.list_creator_videos(mid, page=options.page, page_size=options.page_size)
            else:
                kind, collection_id = parse_bilibili_collection_key(options.collection_key)
                page = await source.list_collection_videos(
                    mid, collection_id, kind=kind, page=options.page, page_size=options.page_size,
                )
        except FetchError as error:
            logger.warning("远端分页失败 author_id=%d platform=%s page=%d error_type=%s",
                           author_id, platform.value, options.page, type(error).__name__)
            raise IngestionError(str(error)) from error
        items = [
            MaterialListItem(item.bvid, item.title or None, item.source_url, _published_at(item.published_ts))
            for item in page.items
        ]
        logger.info("远端分页完成 author_id=%d platform=%s page=%d count=%d next_page=%s elapsed=%.3fs",
                    author_id, platform.value, options.page, len(items), page.next_page, perf_counter() - started)
        return MaterialPage(items, page.next_page)

    async def list_local_materials(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[MaterialDetail]:
        """列出指定作者的完整本地资料详情。

        :param avatar_index: 作者的本地索引。
        :param platform: 可选平台过滤条件。
        :returns: 符合条件的资料列表。
        :raises IngestionError: 无法读取本地资料。
        """
        materials = await self._list_saved_materials(avatar_index, platform)
        return [MaterialDetail.for_material(material) for material in materials]

    async def get_material(self, material_index: MaterialIndex) -> MaterialDetail | None:
        """读取一份资料的详情，包括原稿和可用的加工稿。

        :param material_index: 资料的本地索引。
        :returns: 资料详情。找不到时为 None。
        :raises IngestionError: 无法读取本地资料。
        """
        material = await self._read_saved_material(material_index)
        return MaterialDetail.for_material(material) if material is not None else None

    async def get_raw_material(self, material_index: MaterialIndex) -> RawMaterialDetail | None:
        """读取一份已保存的原稿。

        :param material_index: 目标资料的本地索引。
        :returns: 原稿详情。找不到时返回 None，已保存的空字幕返回空片段列表。
        :raises IngestionError: 无法读取本地资料。
        """
        material = await self._read_saved_material(material_index)
        return RawMaterialDetail.from_entity(material) if isinstance(material, SubtitleMaterialEntity) else None

    async def list_raw_materials(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[RawMaterialDetail]:
        """列出作者已保存的原稿。

        :param avatar_index: 作者的本地索引。
        :param platform: 可选平台。为 None 时列出所有来源。
        :returns: 原稿详情列表，包含已保存的空字幕。
        :raises IngestionError: 无法读取本地资料。
        """
        materials = await self._list_saved_materials(avatar_index, platform)
        return [RawMaterialDetail.from_entity(material) for material in materials if isinstance(material, SubtitleMaterialEntity)]

    async def get_raw_and_processed_material(
        self, material_index: MaterialIndex,
    ) -> RawAndProcessedMaterialDetail | None:
        """从同一份资料读取原稿及已保存的加工稿。

        :param material_index: 目标资料的本地索引。
        :returns: 组合详情。资料不存在时返回 None，尚无加工稿时对应字段为 None。
        :raises IngestionError: 无法读取本地资料。
        """
        material = await self._read_saved_material(material_index)
        return RawAndProcessedMaterialDetail.from_entity(material) if isinstance(material, SubtitleMaterialEntity) else None

    async def list_raw_and_processed_material(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[RawAndProcessedMaterialDetail]:
        """列出作者的原稿及各自可用的加工稿。

        :param avatar_index: 作者的本地索引。
        :param platform: 可选平台。为 None 时列出所有来源。
        :returns: 组合详情列表，包含只有原稿的资料。
        :raises IngestionError: 无法读取本地资料。
        """
        materials = await self._list_saved_materials(avatar_index, platform)
        return [
            RawAndProcessedMaterialDetail.from_entity(material)
            for material in materials if isinstance(material, SubtitleMaterialEntity)
        ]

    async def _read_saved_material(self, material_index: MaterialIndex) -> MaterialEntity | None:
        """为本服务的单条查询读取同一份本地资料。

        :param material_index: 待查询资料的本地索引。
        :returns: 完整资料。查询不到时返回 None。
        :raises IngestionError: 资料无法读取。
        """
        material_id = material_index.get_material_index()
        material = await repository_call(self._materials.get_by_id, material_id)
        logger.debug("查询本地资料 material_id=%d found=%s", material_id, material is not None)
        return material

    async def _list_saved_materials(
        self, avatar_index: AvatarIndex, platform: Platform | None,
    ) -> list[MaterialEntity]:
        """为本服务的列表查询读取作者资料并应用平台筛选。

        :param avatar_index: 作者的本地索引。
        :param platform: 目标平台。为 None 时保留所有平台。
        :returns: 符合平台条件的完整资料，沿用仓储顺序。
        :raises IngestionError: 资料无法读取。
        """
        started = perf_counter()
        author_id = avatar_index.get_avatar_index()
        materials = await repository_call(self._materials.list_by_author, author_id)
        matching = [material for material in materials if platform is None or material.platform is platform]
        logger.debug("本地资料列表 author_id=%d platform=%s count=%d elapsed=%.3fs",
                     author_id, platform, len(matching), perf_counter() - started)
        return matching

    async def collect_material(
        self, avatar_index: AvatarIndex, platform: Platform, param: CollectMaterialParam,
    ) -> CollectionResult:
        """获取指定 BV 号的原始字幕。

        :param avatar_index: 作者的本地索引。
        :param platform: 已登记的来源平台。
        :param param: BV 号及跳过已有原稿的选项。
        :returns: 采集或跳过结果及资料详情。
        :raises KeyError: 找不到作者或平台登记。
        :raises ValueError: 平台、BV 号或视频归属不符合要求。
        :raises IngestionError: 无法下载、转录或保存资料。
        """
        author_id = avatar_index.get_avatar_index()
        mid = await self._creator_mid(author_id, platform)
        return await self._collect(author_id, platform, mid, param)

    async def batch_collect_material(
        self, avatar_index: AvatarIndex, platform: Platform, param: BatchCollectMaterialParam,
    ) -> list[CollectionResult]:
        """对同一账号按输入顺序采集一组原始字幕。

        :param avatar_index: 共用的作者本地索引。
        :param platform: 共用的来源平台。
        :param param: BV 号序列和是否跳过已有资料。
        :returns: 各项结果。某个视频失败时继续下一项。
        :raises KeyError: 找不到批次共用的作者或平台登记。
        :raises ValueError: 平台无效。
        """
        if not param.source_keys:
            return []
        started = perf_counter()
        author_id = avatar_index.get_avatar_index()
        logger.info("批量采集开始 author_id=%d count=%d skip_existing=%s",
                    author_id, len(param.source_keys), param.skip_existing)
        mid = await self._creator_mid(author_id, platform)
        results = []
        for position, key in enumerate(param.source_keys, start=1):
            try:
                results.append(await self._collect(author_id, platform, mid, CollectMaterialParam(key, param.skip_existing)))
            except (KeyError, ValueError, IngestionError) as error:
                # 未通过校验的来源键属于任意外部输入，批量失败用条目位置定位。
                logger.warning("批量采集项失败 author_id=%d position=%d error_type=%s",
                               author_id, position, type(error).__name__)
                results.append(CollectionResult(key, ResultStatus.FAILED, error=str(error)))
        log_batch_results(logger, "batch_collect_material", (result.status for result in results), perf_counter() - started)
        return results

    async def collect_and_process_material(
        self, avatar_index: AvatarIndex, platform: Platform, param: CollectAndProcessMaterialParam,
    ) -> CollectAndProcessResult:
        """采集一份原稿并委托现有加工服务处理。

        :param avatar_index: 作者的本地索引。
        :param platform: 已登记的来源平台。
        :param param: 来源标识、模型选项及两个阶段共用的跳过策略。
        :returns: 同一份资料在采集和加工两个阶段的结果。
        :raises KeyError: 找不到作者或平台登记。
        :raises ValueError: 模型选择或采集参数无效。
        :raises IngestionError: 无法采集或加工。加工出错时原稿仍可重试。
        """
        processor = self._require_process_service()
        selection = _resolve_processing_model(param.model_selection)
        collection = await self.collect_material(
            avatar_index, platform, CollectMaterialParam(param.source_key, param.skip_existing),
        )
        detail = collection.material
        if detail is None:
            raise IngestionError("采集结果缺少可加工的本地资料")

        try:
            processing = await processor.process_material(
                detail, ProcessMaterialParam(skip_existing=param.skip_existing, model_selection=selection),
            )
        except (KeyError, ValueError, IngestionError) as error:
            logger.warning("采集后加工失败 material_id=%d error_type=%s", detail.id, type(error).__name__)
            raise IngestionError(f"资料 {detail.id} 的原稿已保存，加工失败。{error}") from error
        return CollectAndProcessResult(collection, processing)

    async def batch_collect_and_process_material(
        self, avatar_index: AvatarIndex, platform: Platform, param: BatchCollectAndProcessMaterialParam,
    ) -> list[CollectAndProcessResult]:
        """顺序采集所有原稿，再由现有加工服务顺序处理可用资料。

        :param avatar_index: 批次共用的作者本地索引。
        :param platform: 批次共用的来源平台。
        :param param: 有序的来源标识、模型选项和两阶段跳过策略。
        :returns: 与输入位置对应的结果，采集失败的条目没有加工结果。
        :raises KeyError: 找不到作者或平台登记。
        :raises ValueError: 批次共用参数无效。
        :raises IngestionError: 无法读取批次共用的登记或配置。
        """
        if not param.source_keys:
            return []
        processor = self._require_process_service()
        selection = _resolve_processing_model(param.model_selection)
        collections = await self.batch_collect_material(
            avatar_index, platform, BatchCollectMaterialParam(param.source_keys, param.skip_existing),
        )
        results = [CollectAndProcessResult(collection) for collection in collections]
        candidates = [
            (index, item.material) for index, item in enumerate(collections)
            if item.status is not ResultStatus.FAILED and item.material is not None
        ]
        if not candidates:
            return results

        processed = await processor.batch_process_material(BatchProcessMaterialParam(
            material_indexes=[detail for _, detail in candidates],
            skip_existing=param.skip_existing,
            model_selection=selection,
        ))
        # 用输入位置关联阶段结果，保留同一个 BV 号被重复提交时的独立结果。
        for (position, _), processing in zip(candidates, processed, strict=True):
            results[position] = CollectAndProcessResult(collections[position], processing)
        return results

    def _require_process_service(self) -> MaterialProcessService:
        """取得采集后加工所需的服务。

        :returns: 装配时注入的加工服务。
        :raises IngestionError: 当前实例未接入加工服务。
        """
        if self._material_process_service is None:
            raise IngestionError("当前采集服务未接入字幕加工服务")
        return self._material_process_service

    async def delete_material(self, material_index: MaterialIndex) -> None:
        """删除完整的本地资料。

        :param material_index: 待删除的资料索引。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 无法删除资料。
        """
        material_id = material_index.get_material_index()
        await repository_call(self._materials.delete, material_id)
        logger.info("资料已删除 material_id=%d", material_id)

    async def batch_delete_material(self, param: MaterialSelectionParam) -> list[DeletionResult]:
        """批量删除完整资料，并保留每项的处理结果。

        :param param: 按提交顺序排列的资料索引。
        :returns: 各项删除结果。
        """
        return await batch_delete(param.material_indexes, self.delete_material)

    async def _creator_mid(self, author_id: int, platform: Platform) -> int:
        """把本地作者 ID 转换为登记的 B 站 MID。

        :param author_id: 本地博主 ID。
        :param platform: 请求的远端来源平台。
        :returns: 该博主登记的 B 站 MID。
        :raises KeyError: 找不到博主或 B 站登记。
        :raises ValueError: 请求的平台尚不受支持。
        """
        if platform is not Platform.BILIBILI:
            raise ValueError(f"尚未支持平台 {platform}")
        author = await repository_call(self._avatars.get, author_id)
        if author is None:
            logger.debug("采集找不到博主 author_id=%d", author_id)
            raise KeyError(f"找不到博主 ID {author_id}")
        for url in author.source_urls:
            try:
                return parse_bilibili_creator_url(url)
            except ValueError:
                # 主页列表允许来自多个平台，只从中选取 B 站空间。
                continue
        logger.warning("采集缺少 B 站登记 author_id=%d", author_id)
        raise KeyError(f"博主 {author_id} 尚未登记 B 站主页")

    async def _collect(
        self, author_id: int, platform: Platform, mid: int, param: CollectMaterialParam,
    ) -> CollectionResult:
        """在完成下载和转录后一次性写入资料。

        :param author_id: 本地博主 ID。
        :param platform: 所选平台。
        :param mid: 已登记的 B 站作者 ID。
        :param param: BV 号和重采选项。
        :returns: 新采集或复用的资料详情。
        :raises ValueError: BV 号或视频归属无效。
        :raises IngestionError: 远端、转录或保存步骤失败。
        """
        started = perf_counter()
        key = param.source_key.strip()
        if not _BVID.fullmatch(key):
            logger.warning("采集来源标识无效 author_id=%d", author_id)
            raise ValueError("source_key 须为 B 站 BV 号")
        logger.info("采集开始 author_id=%d platform=%s source_key=%s skip_existing=%s",
                    author_id, platform.value, key, param.skip_existing)
        previous = await repository_call(self._materials.get, author_id, platform, key)
        # 已有字幕实体代表完成过转录。静音视频的空字幕同样可以复用。
        if isinstance(previous, SubtitleMaterialEntity) and param.skip_existing:
            logger.info("采集跳过 source_key=%s material_id=%d reason=existing_raw", key, previous.id)
            return CollectionResult(key, ResultStatus.SKIPPED, MaterialDetail.for_material(previous))

        stage = "load_session"
        try:
            source = self._source()
            stage = "get_video"
            video = await source.get_video(key)
            if video.bvid != key or video.author_mid != mid:
                logger.warning("视频作者校验失败 author_id=%d source_key=%s expected_mid=%d actual_mid=%s",
                               author_id, key, mid, video.author_mid)
                raise ValueError(f"无法确认视频 {key} 属于已登记的 B 站作者 {mid}")
            stage = "prepare_audio"
            with TemporaryDirectory(prefix="valhalla-audio-") as directory:
                audio, wav = Path(directory) / "source.m4a", Path(directory) / "speech.wav"
                stage = "download_audio"
                await source.download_audio(key, audio)
                stage = "convert_audio"
                await asyncio.to_thread(self._convert_audio, audio, wav)
                stage = "transcribe"
                logger.info("开始语音转录 source_key=%s", key)
                segments = await asyncio.to_thread(self._transcribe, wav)
                stage = "cleanup_audio"
        except FetchError as error:
            logger.warning("采集失败 source_key=%s stage=%s error_type=%s elapsed=%.3fs",
                           key, stage, type(error).__name__, perf_counter() - started)
            raise IngestionError(str(error)) from error
        except (AudioConversionError, OSError, TranscriptionError) as error:
            logger.error("采集失败 source_key=%s stage=%s error_type=%s elapsed=%.3fs",
                         key, stage, type(error).__name__, perf_counter() - started)
            raise IngestionError(f"无法下载或转录视频 {key} 的音轨") from error

        raw_hash = hashlib.sha256(render_srt(segments).encode("utf-8")).digest()
        unchanged = isinstance(previous, SubtitleMaterialEntity) and previous.content_hash == raw_hash
        now = datetime.now(UTC)
        material = SubtitleMaterialEntity(
            id=previous.id if previous is not None else await repository_call(self._materials.reserve_id),
            created_at=previous.created_at if previous is not None else now, updated_at=now,
            author_id=author_id, platform=platform, source_key=key, source_url=video.source_url,
            title=video.title or None, published_at=_published_at(video.published_ts), content_hash=raw_hash,
            metadata={**(previous.metadata if previous is not None else {}), "author_mid": mid, "part": 1},
            raw_segments=[SubtitleSegment(segment.start, segment.end, segment.text) for segment in segments],
            optimized_segments=previous.optimized_segments if unchanged else [],
            global_keywords=previous.global_keywords if unchanged else (),
        )
        if unchanged and previous == replace(material, updated_at=previous.updated_at, raw_segments=previous.raw_segments):
            logger.info("重采结果未变 source_key=%s material_id=%d elapsed=%.3fs",
                        key, previous.id, perf_counter() - started)
            return CollectionResult(key, ResultStatus.SUCCESS, MaterialDetail.for_material(previous))
        await repository_call(
            self._materials.save, material, expected_updated_at=previous.updated_at if previous is not None else None,
        )
        stored = await repository_call(self._materials.get_by_id, material.id)
        if stored is None:
            raise IngestionError(f"保存后的资料 {material.id} 已不存在")
        logger.info("采集完成 source_key=%s material_id=%d segments=%d elapsed=%.3fs",
                    key, stored.id, len(segments), perf_counter() - started)
        return CollectionResult(key, ResultStatus.SUCCESS, MaterialDetail.for_material(stored))


def _resolve_processing_model(selection: ChatModelInfo | None) -> ChatModelInfo:
    """在采集前校验配置中的模型组合，真实探测留给加工阶段。

    :param selection: 调用方选择的模型。为 None 时由接入层解析默认选项。
    :returns: 已登记的供应商与模型组合。
    :raises ValueError: 指定组合未在目录中登记。
    """
    if selection is None:
        return resolve_chat_model()
    return resolve_chat_model(provider=selection.provider, model=selection.model)


def _published_at(timestamp: int | None) -> datetime | None:
    """把平台返回的 Unix 秒数转换成带时区的发布时间。

    :param timestamp: Unix 秒数。为 None 时表示平台未提供时间。
    :returns: UTC 发布时间或 None。
    """
    return datetime.fromtimestamp(timestamp, UTC) if timestamp is not None else None
