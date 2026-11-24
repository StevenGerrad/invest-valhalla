"""定义采集资料的存储接口。"""

from datetime import datetime
from typing import Protocol

from ..entity import MaterialEntity, Platform


class MaterialRepository(Protocol):
    """提供完整资料实体的查询与保存，存储格式由具体实现管理。"""

    def get(self, author_id: int, platform: Platform, source_key: str) -> MaterialEntity | None:
        """按作者和平台内容标识查询一份资料。

        :param author_id: 作者在项目内的数字人 ID。
        :param platform: 来源平台枚举，例如 Platform.BILIBILI。
        :param source_key: 平台内的内容标识，例如 BV 号。
        :returns: 完整的资料实体，找不到时返回 None。
        """
        ...

    def list_by_author(self, author_id: int) -> list[MaterialEntity]:
        """读取指定作者的全部资料。

        :param author_id: 作者在项目内的数字人 ID。
        :returns: 完整的资料实体列表，没有资料时返回空列表。
        """
        ...

    def get_by_id(self, material_id: int) -> MaterialEntity | None:
        """按本地 ID 查询完整资料。

        :param material_id: 本地资料 ID。
        :returns: 完整的资料实体，找不到时返回 None。
        """
        ...

    def reserve_id(self) -> int:
        """预留一个资料 ID，供调用方构造待保存实体。

        :returns: 唯一的本地自增 ID。保存失败时允许出现编号间隙。
        """
        ...

    def save(self, material: MaterialEntity, *, expected_updated_at: datetime | None = None) -> None:
        """保存一份完整的资料实体。

        :param material: 由具体资料子类表示的实体。
        :param expected_updated_at: 有值时仅在当前记录的修改时间仍等于此值时更新。
        :raises RepositoryConflictError: 来源已登记，或待更新记录已改变。
        """
        ...

    def delete(self, material_id: int) -> None:
        """删除整份资料及它的所有稿件。

        :param material_id: 本地资料 ID。
        :raises KeyError: 找不到该资料。
        """
        ...
