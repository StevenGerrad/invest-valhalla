"""为采集和加工服务提供资料详情转换及批量删除。"""

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from time import perf_counter

from ...entity import MaterialEntity, MaterialIndex, SubtitleMaterialEntity, SubtitleSegment
from ..constant.result_status import ResultStatus
from ..error import IngestionError
from .dto.material_service_dto import DeletionResult, MaterialDetail, SubtitleMaterialDetail, SubtitleSegmentInfo


def material_detail(material: MaterialEntity) -> MaterialDetail:
    """将域内实体和字幕片段转换为独立的交互层 DTO。

    :param material: 需要展示的完整资料。
    :returns: 对应资料类型的详情。
    """
    fields = dict(
        id=material.id, created_at=material.created_at, updated_at=material.updated_at,
        author_id=material.author_id, platform=material.platform, source_key=material.source_key,
        title=material.title, source_url=material.source_url, published_at=material.published_at,
    )
    if isinstance(material, SubtitleMaterialEntity):
        return SubtitleMaterialDetail(
            **fields, raw_segments=list(map(_segment_info, material.raw_segments)),
            optimized_segments=list(map(_segment_info, material.optimized_segments)),
        )
    return MaterialDetail(**fields, content_type=material.content_type)


def _segment_info(segment: SubtitleSegment) -> SubtitleSegmentInfo:
    """复制一个可定位的字幕片段。

    :param segment: 资料实体中的字幕片段。
    :returns: 面向交互层的片段信息。
    """
    return SubtitleSegmentInfo(
        segment.start_seconds, segment.end_seconds, segment.text, segment.heading, segment.keywords,
    )


async def batch_delete(
    indexes: Iterable[MaterialIndex], operation: Callable[[MaterialIndex], Awaitable[None]],
) -> list[DeletionResult]:
    """顺序执行删除操作，并记录各资料的结果。

    :param indexes: 需要处理的本地索引，保留提交顺序。
    :param operation: 单条删除服务方法。
    :returns: 逐项的成功或失败结果。
    """
    started = perf_counter()
    logger = logging.getLogger(operation.__module__)
    results = []
    for index in indexes:
        material_id = index.get_material_index()
        try:
            await operation(index)
        except (KeyError, ValueError, IngestionError) as error:
            logger.warning("批量删除项失败 operation=%s material_id=%d error_type=%s",
                           operation.__name__, material_id, type(error).__name__)
            results.append(DeletionResult(material_id, ResultStatus.FAILED, str(error)))
        else:
            results.append(DeletionResult(material_id, ResultStatus.SUCCESS))
    log_batch_results(logger, operation.__name__, (result.status for result in results), perf_counter() - started)
    return results


def log_batch_results(
    logger: logging.Logger, operation: str, statuses: Iterable[ResultStatus], elapsed: float,
) -> None:
    """将一次资料批量操作的结果汇总为同一条日志。

    :param logger: 业务操作所属模块的 logger。
    :param operation: 服务方法的稳定名称。
    :param statuses: 各项目的执行状态。
    :param elapsed: 整批耗时，单位为秒。
    """
    counts = Counter(statuses)
    logger.info(
        "批量结束 operation=%s total=%d success=%d skipped=%d not_required=%d failed=%d elapsed=%.3fs",
        operation, counts.total(), counts[ResultStatus.SUCCESS], counts[ResultStatus.SKIPPED],
        counts[ResultStatus.NOT_REQUIRED], counts[ResultStatus.FAILED], elapsed,
    )
