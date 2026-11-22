"""定义采集模块所需的数字人登记信息。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AvatarEntity:
    """表示作为本地作者登记的数字人及其平台主页。

    本地 ID 的分配和登记文件格式由存储实现负责。
    """

    #: 数字人与本地作者共用的自增 ID，对应 PostgreSQL BIGINT 主键。
    id: int
    #: 数字人面向使用者展示的名称。
    name: str
    #: 可直接打开的各个平台的作者主页地址。空列表表示尚未登记主页。
    source_urls: list[str]
