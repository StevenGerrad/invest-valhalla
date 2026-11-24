"""以本地 JSON 文件保存数字人登记。"""

import logging
from pathlib import Path
from time import perf_counter
from typing import TypedDict

from ....entity import AvatarEntity
from ...avatar_repository import AvatarRepository
from ...error import RepositoryConflictError
from ._files import locked, read_index, write_json

logger = logging.getLogger(__name__)


class _AvatarDO(TypedDict):
    """表示以本地 ID 为键的 JSON 登记中对应的值。"""

    #: 已登记的博主名称。
    name: str
    #: 已登记的平台来源主页。
    source_urls: list[str]


class AvatarRepositoryImpl(AvatarRepository):
    """维护数字人 JSON 登记及持久化自增序列。"""

    def __init__(self, root: str | Path) -> None:
        """设置新采集模块的数据根目录。

        :param root: 与资料仓储共用的目录。
        """
        self._root = Path(root).resolve()
        self._path = self._root / "avatars.json"

    def get(self, avatar_id: int) -> AvatarEntity | None:
        """读取指定博主的完整登记。

        :param avatar_id: 本地博主 ID。
        :returns: 已登记的博主。查无记录时返回 None。
        """
        with locked(self._root):
            data = read_index(self._path)["records"].get(str(avatar_id))
            avatar = _decode(avatar_id, data) if data is not None else None
        logger.debug("博主索引读取 avatar_id=%d found=%s", avatar_id, avatar is not None)
        return avatar

    def list_all(self) -> list[AvatarEntity]:
        """读取所有已登记的博主。

        :returns: 按本地 ID 顺序排列的博主登记。
        """
        started = perf_counter()
        with locked(self._root):
            records = read_index(self._path)["records"]
            avatars = [_decode(int(avatar_id), data) for avatar_id, data in records.items()]
        logger.debug("博主索引列表 count=%d elapsed=%.3fs", len(avatars), perf_counter() - started)
        return avatars

    def create(self, name: str, source_urls: list[str]) -> AvatarEntity:
        """分配博主 ID 并保存登记。

        :param name: 已校验的博主名称。
        :param source_urls: 已校验的来源主页。
        :returns: 新登记的博主。
        """
        with locked(self._root):
            index = read_index(self._path)
            avatar_id = index["next_id"]
            index["next_id"] += 1
            index["records"][str(avatar_id)] = _AvatarDO(name=name, source_urls=source_urls)
            write_json(self._path, index)
        logger.debug("博主索引已提交 operation=create avatar_id=%d", avatar_id)
        return AvatarEntity(avatar_id, name, list(source_urls))

    def update(self, avatar: AvatarEntity) -> AvatarEntity:
        """以完整实体更新现有博主登记。

        :param avatar: 带有原 ID 及更新字段的实体。
        :returns: 保存后的博主登记。
        :raises KeyError: 原登记不存在。
        """
        with locked(self._root):
            index = read_index(self._path)
            key = str(avatar.id)
            if key not in index["records"]:
                logger.debug("博主索引已不存在 operation=update avatar_id=%d", avatar.id)
                raise KeyError(f"找不到博主 ID {avatar.id}")
            index["records"][key] = _AvatarDO(name=avatar.name, source_urls=avatar.source_urls)
            write_json(self._path, index)
        logger.debug("博主索引已提交 operation=update avatar_id=%d", avatar.id)
        return avatar

    def delete(self, avatar_id: int) -> None:
        """删除没有关联资料的博主。

        :param avatar_id: 待删除博主的本地 ID。
        :raises KeyError: 找不到该博主。
        :raises RepositoryConflictError: 博主仍有关联资料。
        """
        with locked(self._root):
            index = read_index(self._path)
            key = str(avatar_id)
            if key not in index["records"]:
                logger.debug("博主索引已不存在 operation=delete avatar_id=%d", avatar_id)
                raise KeyError(f"找不到博主 ID {avatar_id}")
            # 与资料写入使用同一把锁，防止服务检查后又有新资料入库。
            materials = read_index(self._root / "materials.json")["records"]
            if any(record["author_id"] == avatar_id for record in materials.values()):
                logger.warning("博主索引删除冲突 avatar_id=%d reason=related_materials", avatar_id)
                raise RepositoryConflictError(f"博主 {avatar_id} 仍有关联资料")
            del index["records"][key]
            write_json(self._path, index)
        logger.debug("博主索引已提交 operation=delete avatar_id=%d", avatar_id)


def _decode(avatar_id: int, data: _AvatarDO) -> AvatarEntity:
    """还原 JSON 中的数字人记录。

    :param avatar_id: 索引中的本地 ID。
    :param data: 对应的登记对象。
    :returns: 具有独立平台列表的数字人实体。
    :raises OSError: 登记对象格式无效。
    """
    if (
        not isinstance(data, dict) or not isinstance(data.get("name"), str)
        or not isinstance(data.get("source_urls"), list)
        or not all(isinstance(url, str) for url in data["source_urls"])
    ):
        logger.error("博主索引记录格式无效 avatar_id=%d", avatar_id)
        raise OSError(f"博主 {avatar_id} 的登记格式无效")
    return AvatarEntity(avatar_id, data["name"], data["source_urls"])
