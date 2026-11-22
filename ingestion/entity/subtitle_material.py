"""定义字幕资料及可按时间定位的正文片段。"""

import math
from dataclasses import dataclass, field

from .material import MaterialEntity


@dataclass(frozen=True)
class SubtitleSegment:
    """表示原始或优化字幕中可独立引用的一个带时间片段。"""

    #: 片段相对源媒体起点的开始时间，单位为秒。
    start_seconds: float
    #: 片段相对源媒体起点的结束时间，单位为秒。
    end_seconds: float
    #: 片段的正文，保留文本内的换行。
    text: str
    #: Agent 可为优化片段附带的标题。缺省表示没有标题。
    heading: str | None = None
    #: Agent 可为优化片段附带的关键词。没有关键词时为空元组。
    keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """确保片段能在源媒体的时间轴上定位。

        :raises ValueError: 起止时间不是有限秒数，或不满足 0 <= 开始 <= 结束。
        """
        if not (
            math.isfinite(self.start_seconds)
            and math.isfinite(self.end_seconds)
            and 0 <= self.start_seconds <= self.end_seconds
        ):
            raise ValueError("字幕时间必须是有限秒数且满足 0 <= 开始 <= 结束")


@dataclass(frozen=True, kw_only=True)
class SubtitleMaterialEntity(MaterialEntity):
    """在同一份资料中提供原始字幕和 Agent 优化字幕的片段列表。"""

    #: 按字幕顺序保存的原始正文片段。
    raw_segments: list[SubtitleSegment]
    #: 按字幕顺序保存的优化正文片段。为空表示暂无优化稿。
    optimized_segments: list[SubtitleSegment] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        """提供字幕资料的类型标识。

        :returns: 固定的字幕类型标识 subtitle。
        """
        return "subtitle"

    def __post_init__(self) -> None:
        """校验来源平台和两份字幕列表。

        :raises TypeError: 来源平台或字幕片段的类型无效。
        """
        super().__post_init__()
        # 在实体边界校验两份稿件，避免把原始 SRT 或未解析的字典当作字幕列表。
        for name, segments in (
            ("raw_segments", self.raw_segments),
            ("optimized_segments", self.optimized_segments),
        ):
            if not isinstance(segments, list) or not all(
                isinstance(segment, SubtitleSegment) for segment in segments
            ):
                raise TypeError(f"{name} 必须是 SubtitleSegment 列表")
