"""提供本地文件仓储共用的进程间锁和原子写入。"""

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

if os.name == "nt":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)


@contextmanager
def locked(root: Path) -> Iterator[None]:
    """在同一数据目录的各仓储实例间串行化索引和文件操作。

    :param root: 新采集模块使用的数据根目录。
    :returns: 持有操作系统文件锁的上下文。
    :raises OSError: 无法创建目录或取得锁。
    """
    started = perf_counter()
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock_file = (root / ".storage.lock").open("a+b")
    except OSError as error:
        logger.error("无法打开仓储锁 error_type=%s errno=%s", type(error).__name__, error.errno)
        raise
    with lock_file as lock:
        # 各实例打开独立句柄并锁定同一个字节，退出或进程结束时释放锁。
        try:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError as error:
            logger.error("无法取得仓储锁 error_type=%s errno=%s elapsed=%.3fs",
                         type(error).__name__, error.errno, perf_counter() - started)
            raise
        logger.debug("已取得仓储锁 elapsed=%.3fs", perf_counter() - started)
        yield


def read_index(path: Path) -> dict:
    """读取带自增序列的索引文件。

    :param path: 索引文件路径。
    :returns: 已保存的索引。首次使用时返回空索引。
    :raises OSError: 索引损坏或无法读取。
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict) or type(value.get("next_id")) is not int
            or value["next_id"] < 1 or not isinstance(value.get("records"), dict)
        ):
            raise ValueError("索引结构无效")
        return value
    except FileNotFoundError:
        return {"next_id": 1, "records": {}}
    except ValueError as error:
        logger.error("仓储索引无法解析 index=%s error_type=%s", path.name, type(error).__name__)
        raise OSError(f"无法解析采集索引 {path.name}") from error
    except OSError as error:
        logger.error("仓储索引无法读取 index=%s error_type=%s errno=%s", path.name, type(error).__name__, error.errno)
        raise


def write_json(path: Path, value: object) -> None:
    """把索引或加工稿完整序列化后原子替换目标。

    :param path: JSON 文件路径。
    :param value: 可序列化的待保存内容。
    :raises OSError: 文件无法写入。
    """
    try:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    except (TypeError, ValueError) as error:
        raise OSError(f"无法序列化 {path.name}") from error
    write_text(path, payload + "\n")


def write_text(path: Path, value: str) -> None:
    """在同一目录暂存文件，完整写入后再替换目标。

    :param path: 文本文件路径。
    :param value: 需要以 UTF-8 保存的内容。
    :raises OSError: 写入、同步或替换失败。
    """
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", newline="\n",
                                         prefix=".write-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError as error:
        logger.error("仓储文件提交失败 suffix=%s error_type=%s errno=%s",
                     path.suffix, type(error).__name__, error.errno)
        raise
    finally:
        if temporary is not None:
            discard_files([temporary])


def discard_files(paths: list[Path]) -> None:
    """清理索引已不引用的稿件或未提交的文件。

    :param paths: 可以安全清理的文件列表。
    """
    for path in paths:
        # 索引提交后清理失败只会留下孤立文件，不能把已提交的操作改报为失败。
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("仓储遗留文件清理失败 file=%s error_type=%s errno=%s",
                           path.name, type(error).__name__, error.errno)
