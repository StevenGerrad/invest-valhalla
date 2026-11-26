"""提供采集服务共用的仓储调用和错误转换。"""

import asyncio
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from ..storage.error import RepositoryConflictError
from .error import IngestionConflictError, IngestionError

logger = logging.getLogger(__name__)
_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


async def repository_call(operation: Callable[_Params, _Result], *args: _Params.args,
                          **kwargs: _Params.kwargs) -> _Result:
    """在线程中执行同步仓储调用，并转换存储层异常。

    :param operation: 要调用的仓储方法。
    :param args: 按位置传递给该方法的参数。
    :param kwargs: 按名称传递给该方法的参数。
    :returns: 仓储方法的返回值。
    :raises IngestionConflictError: 记录触发冲突或在操作期间已改变。
    :raises IngestionError: 无法正常读写本地存储。
    """
    try:
        return await asyncio.to_thread(operation, *args, **kwargs)
    except RepositoryConflictError as error:
        logger.debug("仓储操作冲突 operation=%s", getattr(operation, "__qualname__", type(operation).__name__))
        raise IngestionConflictError(str(error)) from error
    except OSError as error:
        logger.error("仓储操作失败 operation=%s error_type=%s errno=%s",
                     getattr(operation, "__qualname__", type(operation).__name__), type(error).__name__, error.errno)
        raise IngestionError("无法读写采集模块的本地存储") from error
