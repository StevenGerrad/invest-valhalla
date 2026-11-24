"""定义数字人登记的存储接口。"""

from typing import Protocol

from ..entity import AvatarEntity


class AvatarRepository(Protocol):
    """管理本地数字人登记，负责分配 ID 并交付已保存的领域实体。"""

    def delete(self, avatar_id: int) -> None:
        """删除指定的数字人登记。

        :param avatar_id: 数字人的本地 ID。
        :raises KeyError: 找不到该数字人。
        :raises RepositoryConflictError: 该数字人仍有关联资料。
        """
        ...

    def get(self, avatar_id: int) -> AvatarEntity | None:
        """查询指定数字人的登记。

        :param avatar_id: 数字人与本地作者共用的整数 ID。
        :returns: 对应的数字人实体，找不到时返回 None。
        """
        ...

    def list_all(self) -> list[AvatarEntity]:
        """列出数字人登记。

        :returns: 数字人实体列表，没有登记时返回空列表。
        """
        ...

    def create(self, name: str, source_urls: list[str]) -> AvatarEntity:
        """分配自增本地 ID 并登记数字人。

        :param name: 数字人的显示名称。
        :param source_urls: 各平台的作者主页地址，尚未登记主页时传空列表。
        :returns: 包含新分配 ID 的已保存实体。
        """
        ...

    def update(self, avatar: AvatarEntity) -> AvatarEntity:
        """按既有 ID 更新数字人的名称和平台主页。

        :param avatar: 包含已有本地 ID 和待更新登记信息的实体。
        :returns: 更新后的已保存实体。
        :raises KeyError: 该 ID 没有对应的数字人登记。
        """
        ...
