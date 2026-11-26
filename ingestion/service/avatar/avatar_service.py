"""声明数字人及其来源账号的管理服务。"""

from typing import Protocol

from ...entity import AvatarIndex, Platform
from .dto.avatar_service_dto import AvatarInfo, AvatarPlatformParam, CreateAvatarParam, UpdateAvatarParam


class AvatarService(Protocol):
    """维护数字人登记及平台账号，向交互层提供可用于后续操作的信息。"""

    async def list_avatars(self) -> list[AvatarInfo]:
        """列出全部已登记的数字人。

        :returns: 数字人信息列表。尚未登记时返回空列表。
        :raises IngestionError: 无法读取数字人登记。
        """
        ...

    async def get_avatar(self, avatar_index: AvatarIndex) -> AvatarInfo | None:
        """读取一个数字人的登记。

        :param avatar_index: 目标数字人的本地索引。
        :returns: 已登记的数字人信息。找不到时返回 None。
        :raises IngestionError: 无法读取数字人登记。
        """
        ...

    async def create_avatar(self, param: CreateAvatarParam) -> AvatarInfo:
        """创建数字人，并可同时登记各平台账号。

        :param param: 数字人名称和可选的平台账号列表。
        :returns: 含新分配本地 ID 的数字人信息。
        :raises ValueError: 名称或平台账号信息无效。
        :raises IngestionConflictError: 同一平台重复登记。
        :raises IngestionError: 无法保存新登记。
        """
        ...

    async def update_avatar(self, avatar_index: AvatarIndex, param: UpdateAvatarParam) -> AvatarInfo:
        """修改数字人的基本信息。

        :param avatar_index: 目标数字人的本地索引。
        :param param: 待更新的基本信息。
        :returns: 保存后的数字人信息。
        :raises KeyError: 找不到数字人登记。
        :raises ValueError: 基本信息无效。
        :raises IngestionError: 无法保存更新后的信息。
        """
        ...

    async def add_platform(self, avatar_index: AvatarIndex, param: AvatarPlatformParam) -> AvatarInfo:
        """为数字人登记一个来源平台账号。

        :param avatar_index: 目标数字人的本地索引。
        :param param: 待登记的平台和作者主页地址。
        :returns: 包含新账号的数字人信息。
        :raises KeyError: 找不到数字人登记。
        :raises ValueError: 平台账号信息无效。
        :raises IngestionConflictError: 数字人已登记该平台。
        :raises IngestionError: 无法保存平台登记。
        """
        ...

    async def update_platform(self, avatar_index: AvatarIndex, param: AvatarPlatformParam) -> AvatarInfo:
        """更新数字人在已登记平台上的作者主页地址。

        :param avatar_index: 目标数字人的本地索引。
        :param param: 已登记的平台和更新后的作者主页地址。
        :returns: 更新后的数字人信息。
        :raises KeyError: 找不到数字人或对应的平台登记。
        :raises ValueError: 作者主页地址无效。
        :raises IngestionError: 无法保存平台登记。
        """
        ...

    async def remove_platform(self, avatar_index: AvatarIndex, platform: Platform) -> None:
        """解除指定平台的账号登记，并保留已采集资料。

        :param avatar_index: 目标数字人的本地索引。
        :param platform: 要解除登记的平台。
        :raises KeyError: 找不到数字人或对应的平台登记。
        :raises IngestionError: 无法解除平台登记。
        """
        ...

    async def delete_avatar(self, avatar_index: AvatarIndex) -> None:
        """删除没有关联资料的数字人登记。

        :param avatar_index: 目标数字人的本地索引。
        :raises KeyError: 找不到数字人登记。
        :raises IngestionConflictError: 数字人仍有关联资料。
        :raises IngestionError: 无法删除数字人登记。
        """
        ...
