"""在本地文件中保存原始字幕、加工稿和可查询的资料索引。"""

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import TypedDict
from urllib.parse import quote
from uuid import uuid4

from ....entity import MaterialEntity, Platform, SubtitleMaterialEntity
from ...error import RepositoryConflictError
from ...material_repository import MaterialRepository
from ._files import discard_files, locked, read_index, write_json, write_text
from ._subtitle_codec import processed_json, raw_srt, read_processed, read_srt

logger = logging.getLogger(__name__)


class _MaterialDO(TypedDict):
    """保存索引中的资料元数据及这次提交所引用的稿件名称。"""

    #: 首次保存时间，带时区的 ISO 8601 字符串。
    created_at: str
    #: 最后一次修改时间，用于后续条件写入。
    updated_at: str
    #: 本地博主 ID。
    author_id: int
    #: 来源平台的枚举值。
    platform: str
    #: 平台内容标识。
    source_key: str
    #: 来源页面地址。
    source_url: str | None
    #: 平台内容标题。
    title: str | None
    #: 平台发布时间，未知时为 None。
    published_at: str | None
    #: 资料的扩展来源信息。
    metadata: dict[str, object]
    #: 原始 SRT 文件的 SHA-256 十六进制值。
    content_hash: str
    #: 原始字幕文件名，提交时一定有值。
    raw_file: str | None
    #: 加工稿文件名，只保存原稿时为 None。
    processed_file: str | None


class MaterialRepositoryImpl(MaterialRepository):
    """管理本地字幕资料及其身份索引，以一次索引替换提交一份完整资料。"""

    def __init__(self, root: str | Path) -> None:
        """绑定采集模块的数据目录。

        :param root: 与数字人仓储共用的数据根目录。
        """
        self._root = Path(root).resolve()
        self._path = self._root / "materials.json"

    def get(self, author_id: int, platform: Platform, source_key: str) -> MaterialEntity | None:
        """按本地作者、平台和来源 ID 定位完整资料。

        :param author_id: 本地博主 ID。
        :param platform: 资料来源平台。
        :param source_key: 平台内容标识。
        :returns: 资料详情，查无记录时为 None。
        """
        with locked(self._root):
            records = read_index(self._path)["records"]
            material_id = _find_id(records, author_id, platform, source_key)
            material = self._decode(int(material_id), records[material_id]) if material_id is not None else None
        logger.debug("按来源读取资料 author_id=%d platform=%s material_id=%s", author_id, platform, material_id)
        return material

    def list_by_author(self, author_id: int) -> list[MaterialEntity]:
        """读取作者所有已保存的资料。

        :param author_id: 本地博主 ID。
        :returns: 完整资料列表，未采集时为空。
        """
        started = perf_counter()
        with locked(self._root):
            records = read_index(self._path)["records"]
            materials = [self._decode(int(key), row) for key, row in records.items() if row["author_id"] == author_id]
        logger.debug("读取博主资料 author_id=%d count=%d elapsed=%.3fs",
                     author_id, len(materials), perf_counter() - started)
        return materials

    def get_by_id(self, material_id: int) -> MaterialEntity | None:
        """按本地 ID 读取完整资料。

        :param material_id: 自增资料 ID。
        :returns: 完整资料，查无记录时为 None。
        """
        with locked(self._root):
            row = read_index(self._path)["records"].get(str(material_id))
            material = self._decode(material_id, row) if row is not None else None
        logger.debug("按 ID 读取资料 material_id=%d found=%s", material_id, material is not None)
        return material

    def reserve_id(self) -> int:
        """持久化预留一个自增 ID。

        :returns: 新的资料 ID，编号在重启后继续递增。
        """
        with locked(self._root):
            index = read_index(self._path)
            material_id = index["next_id"]
            index["next_id"] += 1
            write_json(self._path, index)
        logger.debug("资料 ID 已预留 material_id=%d", material_id)
        return material_id

    def save(self, material: MaterialEntity, *, expected_updated_at: datetime | None = None) -> None:
        """在稿件完整写入后提交新的索引，并清理已替换的文件。

        :param material: 完整的字幕资料实体。
        :param expected_updated_at: 有值时用于防止覆盖其他写入或恢复已删除资料。
        :raises OSError: 无法保存资料或当前文件仓储不支持该资料类型。
        :raises RepositoryConflictError: 资料身份、作者或版本与当前存储冲突。
        """
        started = perf_counter()
        if not isinstance(material, SubtitleMaterialEntity):
            logger.warning("仓储不支持资料类型 material_id=%d", material.id)
            raise OSError("文件仓储目前只支持字幕资料")
        try:
            text = raw_srt(material.raw_segments)
        except ValueError as error:
            logger.error("资料原稿无法序列化 material_id=%d error_type=%s", material.id, type(error).__name__)
            raise OSError("无法序列化原始字幕") from error
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with locked(self._root):
            index = read_index(self._path)
            records = index["records"]
            key = str(material.id)
            current = records.get(key)
            self._check_save(index, material, current, expected_updated_at)
            row = _material_row(material, current, digest)
            directory = self._directory(material.author_id, material.platform)
            prefix = f"{material.id}-{quote(material.source_key, safe='')}.{uuid4().hex}"
            staged: list[Path] = []
            try:
                # 新文件使用独立名称，索引提交前读者仍可读取旧稿。
                if not row["raw_file"]:
                    row["raw_file"] = f"{prefix}.srt"
                    staged.append(directory / "srt" / row["raw_file"])
                    write_text(staged[-1], text)
                if material.optimized_segments:
                    row["processed_file"] = f"{prefix}.json"
                    staged.append(directory / "processed" / row["processed_file"])
                    write_json(staged[-1], processed_json(material))
                records[key] = row
                write_json(self._path, index)
            except Exception as error:
                discard_files(staged)
                logger.error("资料未提交 material_id=%d staged_count=%d error_type=%s",
                             material.id, len(staged), type(error).__name__)
                raise

            if current is not None:
                retained = self._artifact_paths(row)
                discard_files([path for path in self._artifact_paths(current) if path not in retained])
        logger.debug("资料索引已提交 material_id=%d updated_at=%s processed=%s elapsed=%.3fs",
                     material.id, row["updated_at"], row["processed_file"] is not None, perf_counter() - started)

    def delete(self, material_id: int) -> None:
        """从索引中移除资料并清理两份稿件。

        :param material_id: 目标资料的本地 ID。
        :raises KeyError: 资料不存在。
        """
        with locked(self._root):
            index = read_index(self._path)
            row = index["records"].pop(str(material_id), None)
            if row is None:
                logger.debug("待删除资料不存在 material_id=%d", material_id)
                raise KeyError(f"找不到资料 ID {material_id}")
            artifacts = self._artifact_paths(row)
            write_json(self._path, index)
            discard_files(artifacts)
        logger.debug("资料索引已删除 material_id=%d", material_id)

    def _check_save(
        self, index: dict, material: SubtitleMaterialEntity, current: _MaterialDO | None,
        expected_updated_at: datetime | None,
    ) -> None:
        """检查资料 ID、来源唯一性和更新前读到的版本。

        :param index: 当前已持锁读取的资料索引。
        :param material: 需要保存的资料。
        :param current: 同一资料 ID 的当前记录，首次写入时为 None。
        :param expected_updated_at: 调用方读取时的修改时间。
        :raises RepositoryConflictError: 版本、作者或来源与当前记录冲突。
        """
        if not 0 < material.id < index["next_id"]:
            logger.warning("资料保存冲突 material_id=%d reason=unreserved_id", material.id)
            raise RepositoryConflictError("资料 ID 尚未由仓储分配")
        if expected_updated_at is not None and (
            current is None or datetime.fromisoformat(current["updated_at"]) != expected_updated_at
        ):
            logger.warning("资料保存冲突 material_id=%d reason=version_changed expected_updated_at=%s",
                           material.id, expected_updated_at)
            raise RepositoryConflictError(f"资料 {material.id} 已更新或删除，请重新读取后操作")
        if str(material.author_id) not in read_index(self._root / "avatars.json")["records"]:
            logger.warning("资料保存冲突 material_id=%d author_id=%d reason=missing_author", material.id, material.author_id)
            raise RepositoryConflictError(f"博主 {material.author_id} 已不存在")
        identity = (material.author_id, material.platform.value, material.source_key)
        if current is not None and _identity(current) != identity:
            logger.warning("资料保存冲突 material_id=%d reason=source_changed", material.id)
            raise RepositoryConflictError(f"资料 {material.id} 的来源标识不能变更")
        duplicate = _find_id(index["records"], material.author_id, material.platform, material.source_key)
        if duplicate is not None and duplicate != str(material.id):
            logger.warning("资料保存冲突 material_id=%d existing_id=%s reason=duplicate_source", material.id, duplicate)
            raise RepositoryConflictError("同一作者、平台和来源标识的资料已存在")

    def _directory(self, author_id: int, platform: Platform) -> Path:
        """定位一个作者在该平台上的稿件目录。

        :param author_id: 本地博主 ID。
        :param platform: 资料来源平台。
        :returns: 已按作者和平台命名的路径。
        """
        return self._root / str(author_id) / platform.value

    def _artifact_paths(self, row: _MaterialDO) -> list[Path]:
        """读取一条记录索引引用的稿件路径。

        :param row: 已保存的资料索引条目。
        :returns: 原始稿及可选的加工稿路径。
        :raises ValueError: 稿件文件名包含非法路径。
        """
        directory = self._directory(int(row["author_id"]), Platform(row["platform"]))
        paths = []
        for folder, name in (("srt", row["raw_file"]), ("processed", row["processed_file"])):
            if name is not None:
                if Path(name).name != name or "/" in name or "\\" in name or name in {"", ".", ".."}:
                    raise ValueError("稿件索引包含非法文件名")
                paths.append(directory / folder / name)
        return paths

    def _decode(self, material_id: int, row: _MaterialDO) -> SubtitleMaterialEntity:
        """从索引和两个独立文件还原一个完整的字幕实体。

        :param material_id: 本地资料 ID。
        :param row: 当前索引条目。
        :returns: 读回的字幕实体。
        :raises OSError: 索引或稿件无法读取。
        """
        try:
            raw_path, *optimized_paths = self._artifact_paths(row)
            raw = read_srt(raw_path.read_text(encoding="utf-8"))
            optimized, keywords = ([], ())
            if optimized_paths:
                optimized, keywords = read_processed(json.loads(optimized_paths[0].read_text(encoding="utf-8")))
            published_at = row["published_at"]
            return SubtitleMaterialEntity(
                id=material_id, created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                author_id=row["author_id"], platform=Platform(row["platform"]), source_key=row["source_key"],
                title=row["title"], source_url=row["source_url"], metadata=row["metadata"],
                published_at=datetime.fromisoformat(published_at) if published_at else None,
                content_hash=bytes.fromhex(row["content_hash"]), raw_segments=raw,
                optimized_segments=optimized, global_keywords=keywords,
            )
        except OSError as error:
            logger.error("资料稿件无法读取 material_id=%d error_type=%s errno=%s",
                         material_id, type(error).__name__, error.errno)
            raise
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError) as error:
            logger.error("资料索引或稿件格式无效 material_id=%d error_type=%s", material_id, type(error).__name__)
            raise OSError(f"资料 {material_id} 的索引或稿件格式无效") from error


def _identity(row: _MaterialDO) -> tuple[int, str, str]:
    """取得资料索引中的来源标识。

    :param row: 本地索引条目。
    :returns: 作者 ID、平台值和来源内容标识。
    """
    return row["author_id"], row["platform"], row["source_key"]


def _find_id(records: dict[str, _MaterialDO], author_id: int, platform: Platform, source_key: str) -> str | None:
    """通过唯一来源键在轻量索引中查询资料 ID。

    :param records: 已加载的资料记录。
    :param author_id: 本地作者 ID。
    :param platform: 资料来源平台。
    :param source_key: 来源内容标识。
    :returns: 索引所用的资料 ID 字符串。未找到时为 None。
    """
    identity = (author_id, platform.value, source_key)
    return next((key for key, row in records.items() if _identity(row) == identity), None)


def _material_row(material: SubtitleMaterialEntity, current: _MaterialDO | None, digest: str) -> _MaterialDO:
    """构造准备写入索引的私有文件记录。

    :param material: 本次保存的完整实体。
    :param current: 已持久化的记录，首次保存时为 None。
    :param digest: 序列化后 SRT 的 SHA-256 十六进制摘要。
    :returns: 带审计时间、来源和稿件文件名的索引条目。
    """
    now = datetime.now(UTC)
    created = current["created_at"] if current is not None else now.isoformat()
    if current is not None:
        # 系统时间回拨或连续写入时仍生成不同的条件更新标记。
        now = max(now, datetime.fromisoformat(current["updated_at"]) + timedelta(microseconds=1))
    return {
        "created_at": created, "updated_at": now.isoformat(), "author_id": material.author_id,
        "platform": material.platform.value, "source_key": material.source_key, "source_url": material.source_url,
        "title": material.title, "published_at": material.published_at.isoformat() if material.published_at else None,
        "metadata": material.metadata, "content_hash": digest, "processed_file": None,
        "raw_file": current["raw_file"] if current is not None and current["content_hash"] == digest else None,
    }
