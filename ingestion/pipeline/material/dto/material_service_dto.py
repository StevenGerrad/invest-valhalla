"""定义资料浏览、采集和删除的参数与返回类型，以及共用的资料详情。"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from ....entity import MaterialIndex, Platform
from ...constant.result_status import ResultStatus


@dataclass(frozen=True)
class ListRemoteMaterialsParam:
    """指定远端资料的分页和合集范围。"""

    #: 从 1 开始的页码。
    page: int = 1
    #: 每页条目数。为 None 时使用来源平台的默认值。
    page_size: int | None = None
    #: 平台合集标识。为 None 时读取作者的常规投稿。
    collection_key: str | None = None


@dataclass(frozen=True)
class CollectMaterialParam:
    """指定一份远端资料及其原始内容的采集策略。"""

    #: 平台内容标识，例如 B 站的 BV 号。
    source_key: str
    #: 为 True 时跳过已有原稿的资料，为 False 时重新采集。
    skip_existing: bool = True


@dataclass(frozen=True)
class BatchCollectMaterialParam:
    """指定一次批量采集的资料和共用策略。"""

    #: 按提交顺序排列的平台内容标识。
    source_keys: Sequence[str]
    #: 为 True 时跳过批次中已有原稿的资料，为 False 时重新采集这些资料。
    skip_existing: bool = True


@dataclass(frozen=True)
class MaterialSelectionParam:
    """指定同一次批量删除操作涉及的资料。"""

    #: 按提交顺序排列的本地资料索引。
    material_indexes: Sequence[MaterialIndex]


@dataclass(frozen=True)
class MaterialListItem:
    """描述远端列表中可供选择的资料。"""

    #: 平台内容标识，供调用方选择采集目标。
    source_key: str
    #: 平台显示的标题。未知时为 None。
    title: str | None = None
    #: 原始资料的链接。未知时为 None。
    source_url: str | None = None
    #: 平台公布的发布时间，带时区。未知时为 None。
    published_at: datetime | None = None


@dataclass(frozen=True)
class MaterialPage:
    """返回指定账号的一页远端资料。"""

    #: 当前页的资料，按来源平台给出的顺序排列。
    items: list[MaterialListItem]
    #: 下一页的页码。没有后续资料时为 None。
    next_page: int | None


@dataclass(frozen=True, kw_only=True)
class MaterialDetail(MaterialIndex):
    """展示本地资料的公共信息，具体子类补充各自的正文结构。"""

    #: 资料的本地 ID。
    id: int
    #: 资料首次保存时间，带时区。
    created_at: datetime
    #: 资料最后修改时间，带时区。
    updated_at: datetime
    #: 作者的本地数字人 ID。
    author_id: int
    #: 资料所属的来源平台。
    platform: Platform
    #: 平台内容标识，例如 B 站的 BV 号。
    source_key: str
    #: 资料类型标识，例如 subtitle。
    content_type: str
    #: 资料标题。未知时为 None。
    title: str | None = None
    #: 原始资料链接。未知时为 None。
    source_url: str | None = None
    #: 平台公布的发布时间，带时区。未知时为 None。
    published_at: datetime | None = None

    def get_material_index(self) -> int:
        """取得后续查询、加工或删除所需的资料标识。

        :returns: 资料的本地 ID。
        """
        return self.id


@dataclass(frozen=True)
class SubtitleSegmentInfo:
    """展示一个可通过源媒体时间轴定位的字幕片段。"""

    #: 相对于媒体起点的开始时间，单位为秒。
    start_seconds: float
    #: 相对于媒体起点的结束时间，单位为秒。
    end_seconds: float
    #: 当前片段的字幕正文。
    text: str
    #: 加工稿可能提供的标题。未提供时为 None。
    heading: str | None = None
    #: 加工稿可能提供的关键词。未提供时为空元组。
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SubtitleMaterialDetail(MaterialDetail):
    """展示字幕资料的原始片段和加工后的片段。"""

    #: 字幕资料的固定类型标识。
    content_type: str = field(default="subtitle", init=False)
    #: 原始字幕片段，按字幕顺序排列。
    raw_segments: list[SubtitleSegmentInfo]
    #: 加工后的字幕片段。没有加工稿时为空列表。
    optimized_segments: list[SubtitleSegmentInfo] = field(default_factory=list)


@dataclass(frozen=True)
class CollectionResult:
    """交付一份资料的采集情况。失败状态用于批量采集。"""

    #: 此次采集对应的平台内容标识。
    source_key: str
    #: 采集成功、因已有原稿而跳过或批量项失败。
    status: ResultStatus
    #: 新保存或复用的资料详情。失败时为 None。
    material: MaterialDetail | None = None
    #: 可展示的失败原因。其他情况下为 None。
    error: str | None = None


@dataclass(frozen=True)
class DeletionResult:
    """交付批量删除中一份资料或其加工稿的执行情况。"""

    #: 请求删除的本地资料 ID。
    material_id: int
    #: 请求所指向的资料或加工稿删除成功或失败。
    status: ResultStatus
    #: 可展示的失败原因。删除成功时为 None。
    error: str | None = None
