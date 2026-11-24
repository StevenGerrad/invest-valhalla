"""为应用入口配置按 UTC 日期和进程分流的标准库日志。"""

import logging
import os
import sys
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from threading import RLock
from time import gmtime
from typing import TextIO
from uuid import uuid4

_run_id: ContextVar[str] = ContextVar("log_run_id", default="-")
_scope_lock = RLock()
_FORMAT = "%(asctime)sZ %(levelname)s pid=%(process)d run_id=%(run_id)s %(name)s %(message)s"


@contextmanager
def log_run() -> Iterator[str]:
    """为当前任务和它启动的异步工作绑定可查询的运行标识。

    :returns: 当前上下文的运行 ID。退出时恢复调用方的上下文。
    """
    run_id = uuid4().hex
    token = _run_id.set(run_id)
    try:
        yield run_id
    finally:
        _run_id.reset(token)


@dataclass(frozen=True)
class _Settings:
    """保存已验证的级别和各类日志的保留期限。"""

    #: 应用日志的最低级别。
    level: int
    #: 应用日志保留的日历天数。
    app_retention_days: int
    #: 异常日志保留的日历天数。
    error_retention_days: int
    #: 访问日志保留的日历天数。
    access_retention_days: int


def _load_settings(config_path: str | Path | None, level: int | None) -> _Settings:
    """合并随包配置、本地覆盖与入口指定的日志级别。

    :param config_path: 可选的 TOML 覆盖文件。只读取 logging 节。
    :param level: 可选的标准库日志级别，每次启动时优先使用。
    :returns: 校验后的日志配置。
    :raises ValueError: 日志级别或保留期限无效。
    :raises OSError: 无法读取指定的配置文件。
    """
    values = tomllib.loads(files("core").joinpath("config.toml").read_text(encoding="utf-8"))["logging"]
    if config_path is not None:
        with Path(config_path).open("rb") as stream:
            overrides = tomllib.load(stream).get("logging", {})
        if not isinstance(overrides, dict):
            raise ValueError("logging 配置须为 TOML 表")
        values.update(overrides)
    if level is None:
        name = values["level"]
        level = logging.getLevelNamesMapping().get(name.upper()) if isinstance(name, str) else None
    if type(level) is not int or level < logging.DEBUG or level > logging.CRITICAL:
        raise ValueError("日志级别须在 DEBUG 和 CRITICAL 之间")
    retention = [values[key] for key in ("app_retention_days", "error_retention_days", "access_retention_days")]
    if any(type(days) is not int or days < 1 for days in retention):
        raise ValueError("日志保留期限须为正整数天数")
    return _Settings(level, *retention)


class _DailyFileHandler(logging.Handler):
    """按日期和进程写入独立文件，并在打开新一天的文件时清理历史。"""

    def __init__(self, log_dir: Path, category: str, level: int, retention_days: int) -> None:
        """定位日志目录并配置 UTC 格式，首次记录时才打开文件。

        :param log_dir: 当前应用的日志目录。
        :param category: 用于区分日志文件的类别。
        :param level: 该文件的最低级别。
        :param retention_days: 包含当日的保留天数。
        """
        super().__init__(level)
        self._log_dir = log_dir
        self._category = category
        self._retention_days = retention_days
        self._day: date | None = None
        self._stream: TextIO | None = None
        self._reported_failure = False
        formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = gmtime
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        """追加一条日志，日期变化时切换到当日文件。

        :param record: 标准库传入的日志记录。
        """
        try:
            day = datetime.fromtimestamp(record.created, UTC).date()
            if self._stream is None or day != self._day:
                self._open(day)
            record.run_id = _run_id.get()
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            # 文件不可用时仍允许应用继续工作，诊断信息不展开原始日志参数。
            self._report_failure()

    def _open(self, day: date) -> None:
        """切换到指定日期和当前进程的文件。

        :param day: 日志记录所在的 UTC 日期。
        :raises OSError: 无法创建目录或打开文件。
        """
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._log_dir.mkdir(parents=True, exist_ok=True)
        path = self._log_dir / f"{self._category}-{day.isoformat()}-{os.getpid()}.log"
        self._stream = path.open("a", encoding="utf-8", errors="backslashreplace")
        self._day = day
        self._prune(day)

    def _prune(self, day: date) -> None:
        """清理超过本类别保留期限的日志文件。

        :param day: 用于计算保留窗口的 UTC 日期。
        """
        # 比较日期差，保留当日以及配置窗口内的前几天。
        prefix = f"{self._category}-"
        try:
            for path in self._log_dir.glob(f"{prefix}*.log"):
                name = path.stem.removeprefix(prefix)
                date_text, separator, pid = name.rpartition("-")
                if separator and pid.isdecimal():
                    try:
                        expired = (day - date.fromisoformat(date_text)).days >= self._retention_days
                    except ValueError:
                        continue
                    if expired:
                        with suppress(OSError):
                            # 另一进程可能已经清理该文件，或仍持有打开的文件句柄。
                            path.unlink(missing_ok=True)
        except OSError:
            self._report_failure()

    def _report_failure(self) -> None:
        """向标准错误报告本类日志文件不可用，每个 handler 只报告一次。"""
        if not self._reported_failure:
            self._reported_failure = True
            with suppress(OSError, ValueError):
                print(f"无法写入或维护 {self._category} 日志，请检查日志目录。", file=sys.stderr)

    def close(self) -> None:
        """关闭本 handler 打开的文件，等待进行中的线程写入结束。"""
        with self.lock:
            if self._stream is not None:
                with suppress(OSError):
                    self._stream.close()
                self._stream = None
            super().close()


@dataclass
class _ActiveScope:
    """跟踪同一命名空间的日志配置及其嵌套使用次数。"""

    #: 进入配置前的 logger 级别。
    level: int
    #: 进入配置前是否传播给上级 logger。
    propagate: bool
    #: 本次配置安装的 handler。
    handlers: list[_DailyFileHandler]
    #: 当前持有该配置的上下文数量。
    count: int = 1


_active_scopes: dict[str, _ActiveScope] = {}


@contextmanager
def _attach(
    logger_name: str, log_dir: Path, categories: Sequence[tuple[str, int, int]], level: int,
) -> Iterator[None]:
    """安装指定命名空间的 handler，并在最后一个使用者退出时解除。

    :param logger_name: 要配置的非根 logger。
    :param log_dir: 日志输出目录。
    :param categories: 依次声明类别、级别与保留天数。
    :param level: 命名空间允许进入 handler 的最低级别。
    :returns: 使用该配置的上下文。嵌套调用复用已配置的 handler。
    """
    logger = logging.getLogger(logger_name)
    with _scope_lock:
        scope = _active_scopes.get(logger_name)
        if scope is None:
            handlers = [_DailyFileHandler(log_dir, *category) for category in categories]
            scope = _ActiveScope(logger.level, logger.propagate, handlers)
            _active_scopes[logger_name] = scope
            logger.setLevel(level)
            logger.propagate = False
            for handler in handlers:
                logger.addHandler(handler)
        else:
            scope.count += 1
    try:
        yield
    finally:
        with _scope_lock:
            scope.count -= 1
            if scope.count == 0:
                for handler in scope.handlers:
                    logger.removeHandler(handler)
                    handler.close()
                logger.setLevel(scope.level)
                logger.propagate = scope.propagate
                del _active_scopes[logger_name]


@contextmanager
def configure_logging(
    log_dir: str | Path, *, logger_name: str, access_logger_name: str | None = None,
    config_path: str | Path | None = None, level: int | None = None,
) -> Iterator[None]:
    """为一个应用配置应用、异常及可选的访问日志。

    :param log_dir: 当前应用的日志目录。
    :param logger_name: 应用自身的非根 logger 名称。
    :param access_logger_name: 可选的独立访问 logger 名称。
    :param config_path: 覆盖随包配置的 TOML 文件。
    :param level: 应用日志级别覆盖。缺省使用配置中的值。
    :returns: 持有应用日志配置的上下文。
    :raises ValueError: 日志配置或命名空间无效。
    :raises OSError: 无法读取日志配置文件。
    """
    if not logger_name or logger_name == "root" or access_logger_name in {logger_name, "root", ""}:
        raise ValueError("日志配置需要不同的非根命名空间")
    settings = _load_settings(config_path, level)
    root = Path(log_dir).resolve()
    app_categories = (
        ("app", settings.level, settings.app_retention_days),
        ("error", logging.WARNING, settings.error_retention_days),
    )
    with _attach(logger_name, root, app_categories, min(settings.level, logging.WARNING)):
        if access_logger_name is None:
            yield
        else:
            access_categories = (("access", logging.INFO, settings.access_retention_days),)
            with _attach(access_logger_name, root, access_categories, logging.INFO):
                yield
