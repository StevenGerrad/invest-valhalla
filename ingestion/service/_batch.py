"""复用材料服务的逐项删除和批量结果日志。"""

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from time import perf_counter

from ..common.constant.result_status import ResultStatus
from ..common.dto.material_dto import DeletionResult
from ..entity import MaterialIndex
from .error import IngestionError


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
            # 单条删除方法决定实际删除哪些内容。这里记录失败，并继续处理后续资料。
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
