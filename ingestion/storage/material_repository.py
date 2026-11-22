"""定义采集资料的存储接口。"""

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

    def save(self, material: MaterialEntity) -> None:
        """保存一份完整的资料实体。

        :param material: 由具体资料子类表示的实体。
        """
        ...
