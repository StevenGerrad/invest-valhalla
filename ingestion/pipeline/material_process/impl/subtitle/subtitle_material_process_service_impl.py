"""实现字幕资料加工及加工稿删除。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from time import perf_counter
from typing import TYPE_CHECKING

from ingestion.entity import MaterialEntity, MaterialIndex, SubtitleMaterialEntity, SubtitleSegment
from ingestion.pipeline._support import repository_call
from ingestion.pipeline.constant.result_status import ResultStatus
from ingestion.pipeline.error import IngestionError
from ingestion.pipeline.material._support import batch_delete, log_batch_results, material_detail
from ingestion.pipeline.material.dto.material_service_dto import DeletionResult, MaterialSelectionParam
from ingestion.storage import MaterialRepository

from ...dto.material_process_service_dto import BatchProcessMaterialParam, ProcessingResult, ProcessMaterialParam
from ...material_process_service import MaterialProcessService
from .subtitle_processor import process_subtitles

if TYPE_CHECKING:
    from integration.llm import ChatBackend

logger = logging.getLogger(__name__)


class SubtitleMaterialProcessServiceImpl(MaterialProcessService):
    """维护由原始字幕生成的加工稿，适用于不同平台的字幕资料。"""

    def __init__(self, materials: MaterialRepository, backend: Callable[[], ChatBackend]) -> None:
        """接收资料仓储和模型能力。

        :param materials: 读取原稿并保存整理结果的仓储。
        :param backend: 仅在需要加工时调用的模型能力构造函数。
        """
        self._materials = materials
        self._backend = backend

    async def process_material(self, material_index: MaterialIndex, param: ProcessMaterialParam) -> ProcessingResult:
        """加工一份字幕资料，在全部批次成功后更新实体。

        :param material_index: 本地资料索引。
        :param param: 是否保留已有加工稿并跳过。
        :returns: 加工结果及可供查看的详情。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 模型或仓储操作失败。
        """
        started = perf_counter()
        material = await self._require_material(material_index)
        if not isinstance(material, SubtitleMaterialEntity) or not material.raw_segments:
            logger.info("资料无需字幕加工 material_id=%d reason=unsupported_or_empty", material.id)
            return ProcessingResult(material.id, ResultStatus.NOT_REQUIRED, material_detail(material))
        if param.skip_existing and material.optimized_segments:
            logger.info("字幕加工跳过 material_id=%d reason=existing_processed", material.id)
            return ProcessingResult(material.id, ResultStatus.SKIPPED, material_detail(material))

        logger.info("字幕加工开始 material_id=%d segments=%d", material.id, len(material.raw_segments))
        try:
            sections, keywords = await asyncio.to_thread(self._process, material)
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
        return ProcessingResult(material.id, ResultStatus.SUCCESS, material_detail(stored))

    async def batch_process_material(self, param: BatchProcessMaterialParam) -> list[ProcessingResult]:
        """顺序加工多条资料并记录每项结果。

        :param param: 排序后的目标资料及共用策略。
        :returns: 与输入顺序一致的结果列表。
        """
        started = perf_counter()
        logger.info("批量加工开始 count=%d skip_existing=%s", len(param.material_indexes), param.skip_existing)
        results = []
        for index in param.material_indexes:
            try:
                result = await self.process_material(index, ProcessMaterialParam(param.skip_existing))
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

    def _process(self, material: SubtitleMaterialEntity) -> tuple[list[SubtitleSegment], tuple[str, ...]]:
        """在线程中构造模型并加工原始字幕。

        :param material: 带有原始字幕的资料。
        :returns: 加工片段和全文关键词。
        """
        return process_subtitles(self._backend(), material)
