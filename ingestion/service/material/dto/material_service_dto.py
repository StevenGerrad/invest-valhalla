"""定义远端资料浏览及原稿查询专用的参数与返回类型。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from ....common.dto.material_dto import MaterialDetail
from ....common.dto.subtitle.subtitle_dto import RawSubtitle, SubtitleSegmentInfo
from ....entity import SubtitleMaterialEntity


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
class RawMaterialDetail(MaterialDetail):
    """返回资料的来源信息及原始字幕。"""

    #: 当前原稿的内容类型为字幕。
    content_type: str = field(default="subtitle", init=False)
    #: 按时间顺序排列的原始片段。已采集但没有识别出语音时为空列表。
    raw_subtitle: RawSubtitle

    @classmethod
    def from_entity(cls, material: SubtitleMaterialEntity) -> Self:
        """生成资料的来源信息和原始字幕详情。

        :param material: 已保存的字幕资料，可包含空原稿。
        :returns: 包含公共资料信息和原稿片段的详情。
        """
        return cls._from_entity(material, raw_subtitle=SubtitleSegmentInfo.from_segments(material.raw_segments))
