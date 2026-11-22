"""定义不同类型采集资料共用的抽象实体。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from .platform import Platform


@dataclass(frozen=True)
class MaterialEntity(ABC):
    """定义采集资料的身份、来源及审计信息。

    各资料子类负责自己的内容结构。ID 分配、时间维护和文件布局由存储实现负责。
    """

    #: 项目内自增的资料 ID，对应 PostgreSQL BIGINT 主键。更新资料时保留此 ID。
    id: int
    #: 此条资料首次保存的时间，带时区。后续更新时保留。
    created_at: datetime
    #: 此条资料最后修改的时间，带时区。首次保存时与 created_at 相同。
    updated_at: datetime
    #: 作者在项目内的数字人 ID，用于跨平台归集和查询同一作者的资料。
    author_id: int
    #: 内容发布的平台枚举，与平台内容标识一起用于定位来源。
    platform: Platform
    #: 平台内的内容标识，例如 B 站视频的 BV 号。两份稿件共用这个标识。
    source_key: str
    #: 可用于回查原始内容的页面链接。为 None 表示尚未取得链接。
    source_url: str | None = None
    #: 平台提供的内容标题。为 None 表示无标题或尚未取得标题。
    title: str | None = None
    #: 平台公布的内容发布时间。为 None 表示发布时间未知。
    published_at: datetime | None = None
    #: 可序列化为 JSON 对象的来源扩展信息，例如播放量和导入方式。无扩展信息时为空字典。
    metadata: dict[str, object] = field(default_factory=dict)
    #: 原始稿的二进制内容哈希，与未来存储的原始稿行对应。为 None 表示尚未计算。
    content_hash: bytes | None = None

    @property
    @abstractmethod
    def content_type(self) -> str:
        """标识子类所表示的资料类型。

        :returns: 用于区分和还原资料子类的类型标识。
        """
        ...

    def __post_init__(self) -> None:
        """验证来源平台已经解析为枚举成员。

        :raises TypeError: platform 不是 Platform 枚举成员。
        """
        if not isinstance(self.platform, Platform):
            raise TypeError("platform 必须是 Platform 枚举成员")
