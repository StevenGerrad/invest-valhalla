"""定义服务用来定位领域实体的身份接口。"""

from abc import abstractmethod
from typing import Protocol


class AvatarIndex(Protocol):
    """提供数字人的本地标识，供服务定位已登记的数字人。"""

    @abstractmethod
    def get_avatar_index(self) -> int:
        """读取数字人的本地标识。

        :returns: 已登记数字人的本地 ID。
        """
        ...


class MaterialIndex(Protocol):
    """提供资料的本地标识，供服务定位已保存的资料。"""

    @abstractmethod
    def get_material_index(self) -> int:
        """读取资料的本地标识。

        :returns: 已保存资料的本地 ID。
        """
        ...
