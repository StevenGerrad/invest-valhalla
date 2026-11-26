"""实现字幕资料加工及加工稿删除。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from functools import cache
from time import perf_counter

from integration.llm import ChatBackend, ChatBackendError, ChatModelInfo, bind_chat_invoke
from ingestion.entity import AvatarIndex, MaterialEntity, MaterialIndex, Platform, SubtitleMaterialEntity, SubtitleSegment
from ingestion.entity.agent import SubtitleProcessAgent
from ingestion.service._batch import batch_delete, log_batch_results
from ingestion.service._support import repository_call
from ingestion.common.dto.material_dto import DeletionResult, MaterialDetail, MaterialSelectionParam, ProcessingResult
from ingestion.common.dto.subtitle.subtitle_dto import SubtitleProcessParam
from ingestion.common.constant.result_status import ResultStatus
from ingestion.service.error import IngestionError
from ingestion.storage import MaterialRepository

from ...dto.material_process_service_dto import BatchProcessMaterialParam, ProcessedMaterialDetail, ProcessMaterialParam
from ...material_process_service import MaterialProcessService

logger = logging.getLogger(__name__)


class SubtitleMaterialProcessServiceImpl(MaterialProcessService):
    """维护由原始字幕生成的加工稿，适用于不同平台的字幕资料。"""

    def __init__(
        self, materials: MaterialRepository, backend: Callable[[], ChatBackend],
        *, selected_backend: Callable[[ChatModelInfo], ChatBackend] | None = None,
    ) -> None:
        """接收资料仓储和模型能力。

        :param materials: 读取原稿并保存整理结果的仓储。
        :param backend: 仅在需要加工时调用的模型能力构造函数。
        :param selected_backend: 构造并探测指定模型的函数。为 None 时仅能使用默认后端。
        """
        self._materials = materials
        self._backend = backend
        self._selected_backend = selected_backend

    async def get_processed_material(self, material_index: MaterialIndex) -> ProcessedMaterialDetail | None:
        """读取一份已保存的加工稿。

        :param material_index: 目标资料的本地索引。
        :returns: 加工稿详情。没有资料或尚无加工稿时返回 None。
        :raises IngestionError: 无法读取本地资料。
        """
        material_id = material_index.get_material_index()
        material = await repository_call(self._materials.get_by_id, material_id)
        logger.debug("查询本地资料 material_id=%d found=%s", material_id, material is not None)
        if isinstance(material, SubtitleMaterialEntity) and material.optimized_segments:
            return ProcessedMaterialDetail.from_entity(material)
        return None

    async def list_processed_materials(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[ProcessedMaterialDetail]:
        """列出作者已保存的加工稿。

        :param avatar_index: 作者的本地索引。
        :param platform: 可选平台。为 None 时列出所有来源。
        :returns: 仅包含已有加工稿的资料详情。
        :raises IngestionError: 无法读取本地资料。
        """
        started = perf_counter()
        author_id = avatar_index.get_avatar_index()
        materials = await repository_call(self._materials.list_by_author, author_id)
        details = [
            ProcessedMaterialDetail.from_entity(material) for material in materials
            if isinstance(material, SubtitleMaterialEntity)
            and material.optimized_segments
            and (platform is None or material.platform is platform)
        ]
        logger.debug("加工稿列表 author_id=%d platform=%s count=%d elapsed=%.3fs",
                     author_id, platform, len(details), perf_counter() - started)
        return details

    async def process_material(self, material_index: MaterialIndex, param: ProcessMaterialParam) -> ProcessingResult:
        """加工一份字幕资料，在整份稿件通过校验后更新实体。

        :param material_index: 本地资料索引。
        :param param: 已有加工稿的跳过策略及可选模型。
        :returns: 加工结果及可供查看的详情。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 模型或仓储操作失败。
        """
        return await self._process_material(material_index, param.skip_existing, self._backend_for(param.model_selection))

    async def _process_material(
        self, material_index: MaterialIndex, skip_existing: bool, backend: Callable[[], ChatBackend],
    ) -> ProcessingResult:
        """复用单条加工流程，按需在工作线程取得本次请求的后端。

        :param material_index: 本地资料索引。
        :param skip_existing: 有加工稿时是否跳过。
        :param backend: 本次调用共用的延迟后端入口。
        :returns: 加工结果及资料详情。
        :raises KeyError: 指定的资料不存在。
        :raises IngestionError: 模型探测、加工或仓储操作失败。
        """
        started = perf_counter()
        material = await self._require_material(material_index)
        if not isinstance(material, SubtitleMaterialEntity) or not material.raw_segments:
            logger.info("资料无需字幕加工 material_id=%d reason=unsupported_or_empty", material.id)
            return ProcessingResult(material.id, ResultStatus.NOT_REQUIRED, MaterialDetail.for_material(material))
        if skip_existing and material.optimized_segments:
            logger.info("字幕加工跳过 material_id=%d reason=existing_processed", material.id)
            return ProcessingResult(material.id, ResultStatus.SKIPPED, MaterialDetail.for_material(material))

        logger.info("字幕加工开始 material_id=%d segments=%d", material.id, len(material.raw_segments))
        try:
            sections, keywords = await asyncio.to_thread(self._process, backend, material)
        except IngestionError as error:
            logger.warning("字幕加工无法启动 material_id=%d error_type=%s elapsed=%.3fs",
                           material.id, type(error).__name__, perf_counter() - started)
            raise
        except (ValueError, RuntimeError) as error:
            logger.error("字幕加工失败 material_id=%d stage=model error_type=%s elapsed=%.3fs",
                         material.id, type(error).__name__, perf_counter() - started)
            raise IngestionError(f"资料 {material.id} 的字幕加工失败：{error}") from error

        updated = replace(material, optimized_segments=sections, global_keywords=keywords)
        # 写入条件基于读取时的版本，期间重新采集或删除资料会触发冲突。
        await repository_call(self._materials.save, updated, expected_updated_at=material.updated_at)
        stored = await self._require_material(material_index)
        logger.info("字幕加工完成 material_id=%d sections=%d elapsed=%.3fs",
                    material.id, len(sections), perf_counter() - started)
        return ProcessingResult(material.id, ResultStatus.SUCCESS, MaterialDetail.for_material(stored))

    async def batch_process_material(self, param: BatchProcessMaterialParam) -> list[ProcessingResult]:
        """顺序加工多条资料并记录每项结果。

        :param param: 排序后的目标资料，以及共用的模型和跳过策略。
        :returns: 与输入顺序一致的结果列表。
        """
        started = perf_counter()
        backend = self._backend_for(param.model_selection)
        logger.info("批量加工开始 count=%d skip_existing=%s", len(param.material_indexes), param.skip_existing)
        results = []
        for index in param.material_indexes:
            try:
                result = await self._process_material(index, param.skip_existing, backend)
            except (KeyError, IngestionError) as error:
                material_id = index.get_material_index()
                logger.warning("批量加工项失败 material_id=%d error_type=%s", material_id, type(error).__name__)
                result = ProcessingResult(material_id, ResultStatus.FAILED, error=str(error))
            results.append(result)
        log_batch_results(logger, "batch_process_material", (result.status for result in results), perf_counter() - started)
        return results

    async def delete_processed_material(self, material_index: MaterialIndex) -> None:
        """清除一份资料的加工稿和全文关键词，保留原稿。

        :param material_index: 本地资料索引。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 无法读写资料。
        """
        material = await self._require_material(material_index)
        if isinstance(material, SubtitleMaterialEntity) and material.optimized_segments:
            updated = replace(material, optimized_segments=[], global_keywords=())
            await repository_call(self._materials.save, updated, expected_updated_at=material.updated_at)
            logger.info("已删除加工稿 material_id=%d", material.id)
        else:
            logger.debug("资料没有可删除的加工稿 material_id=%d", material.id)

    async def batch_delete_processed_material(self, param: MaterialSelectionParam) -> list[DeletionResult]:
        """逐项清除加工稿并保留各份原始资料。

        :param param: 按提交顺序排列的资料索引。
        :returns: 各项目的删除结果。
        """
        return await batch_delete(param.material_indexes, self.delete_processed_material)

    async def _require_material(self, material_index: MaterialIndex) -> MaterialEntity:
        """读取一份必需存在的本地资料。

        :param material_index: 本地资料索引。
        :returns: 仓储返回的完整资料。
        :raises KeyError: 目标资料不存在。
        """
        material_id = material_index.get_material_index()
        material = await repository_call(self._materials.get_by_id, material_id)
        if material is None:
            logger.warning("加工服务找不到资料 material_id=%d", material_id)
            raise KeyError(f"找不到资料 ID {material_id}")
        return material

    def _backend_for(self, selection: ChatModelInfo | None) -> Callable[[], ChatBackend]:
        """为一次加工请求准备按需加载的模型入口。

        :param selection: 供应商和模型组合。None 使用既有后端。
        :returns: 在线程中取得后端的函数，批量任务共用同一次探测结果。
        """
        if selection is None:
            return self._backend

        @cache
        def prepare() -> ChatBackend | str:
            """构造选定后端，保留一次探测的结果供同批条目复用。

            :returns: 通过探测的后端，或可以展示的失败说明。
            """
            if self._selected_backend is None:
                return "当前加工服务缺少指定模型的接入配置"
            try:
                backend = self._selected_backend(selection)
            except ChatBackendError as error:
                logger.warning("模型探测失败 provider=%s model=%s kind=%s",
                               selection.provider, selection.model, error.kind)
                return str(error)
            except IngestionError as error:
                logger.warning("模型准备失败 provider=%s model=%s error_type=%s",
                               selection.provider, selection.model, type(error).__name__)
                return str(error)
            logger.info("模型探测通过 provider=%s model=%s", selection.provider, selection.model)
            return backend

        def prepared_backend() -> ChatBackend:
            """取得已准备的后端，并将前置失败报告给加工流程。

            :returns: 已通过可用性探测的后端。
            :raises IngestionError: 无法准备指定模型。
            """
            result = prepare()
            if isinstance(result, str):
                raise IngestionError(result)
            return result

        return prepared_backend

    def _process(
        self, backend: Callable[[], ChatBackend], material: SubtitleMaterialEntity,
    ) -> tuple[list[SubtitleSegment], tuple[str, ...]]:
        """在线程中将整份原稿交给字幕 Agent，并转换其输出。

        :param backend: 本次加工使用的延迟后端入口。
        :param material: 带有原始字幕的资料。
        :returns: 加工片段和全文关键词。
        :raises ValueError: 字幕或模型返回不符合加工约束。
        :raises ChatBackendError: 模型调用失败或响应未完整返回。
        """
        agent = SubtitleProcessAgent(bind_chat_invoke(backend()))
        result = agent.process(SubtitleProcessParam.from_entity(material))
        # Agent 使用共享 DTO 交付正文。仓储继续接收领域实体，保留原稿和资料标识。
        segments = [SubtitleSegment(item.start_seconds, item.end_seconds, item.text) for item in result.segments]
        return segments, tuple(result.global_keywords)
