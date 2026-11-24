"""定义数字人登记服务的输入参数和返回信息。"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from ....entity import AvatarIndex, Platform


@dataclass(frozen=True)
class AvatarPlatformParam:
    """描述数字人在一个平台上的作者账号。"""

    #: 该作者账号所属的平台。
    platform: Platform
    #: 可直接打开作者主页的地址。
    source_url: str


@dataclass(frozen=True)
class CreateAvatarParam:
    """提交新数字人的名称和可选的平台账号。"""

    #: 数字人的显示名称。
    name: str
    #: 初次登记的平台账号。为空表示稍后补充账号。
    platforms: Sequence[AvatarPlatformParam] = ()


@dataclass(frozen=True)
class UpdateAvatarParam:
    """提交需要修改的数字人基本信息。"""

    #: 更新后的数字人显示名称。
    name: str


@dataclass(frozen=True)
class AvatarPlatformInfo:
    """展示数字人已登记的平台账号。"""

    #: 该作者账号所属的平台。
    platform: Platform
    #: 可直接打开的作者主页地址。
    source_url: str


@dataclass(frozen=True)
class AvatarInfo(AvatarIndex):
    """展示数字人的登记信息，并提供后续操作所需的索引。"""

    #: 数字人的本地 ID。
    id: int
    #: 数字人的显示名称。
    name: str
    #: 已登记的平台账号列表。没有登记账号时为空列表。
    platforms: list[AvatarPlatformInfo] = field(default_factory=list)

    def get_avatar_index(self) -> int:
        """取得后续查询或修改所需的数字人标识。

        :returns: 数字人的本地 ID。
        """
        return self.id
