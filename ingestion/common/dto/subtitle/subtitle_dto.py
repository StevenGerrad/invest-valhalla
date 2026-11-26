"""定义字幕加工与资料查询共用的原稿、加工稿和片段。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubtitleSegmentInfo:
    """展示一个可按源媒体时间定位的字幕片段，适用于原稿和加工稿。"""

    #: 相对于源媒体起点的开始时间，单位为秒。
    start_seconds: float
    #: 相对于源媒体起点的结束时间，单位为秒。
    end_seconds: float
    #: 片段的字幕正文。
    text: str


#: 原稿按时间顺序排列。已保存的空字幕表示为空列表。
type RawSubtitle = list[SubtitleSegmentInfo]


@dataclass(frozen=True)
class SubtitleProcessParam:
    """向字幕 Agent 提交一份原稿及其标题。"""

    #: 资料标题。未知时为 None。
    title: str | None
    #: 按开始时间排序的原始字幕。没有识别出语音时为空列表。
    raw_subtitle: RawSubtitle


@dataclass(frozen=True)
class ProcessedSubtitleSegmentInfo(SubtitleSegmentInfo):
    """表示可按源媒体时间引用的加工段落及其语义信息。"""

    #: 段落标题。未提供时为 None。
    heading: str | None = None
    #: 段落关键词。未提供时为空元组。
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessedSubtitleInfo:
    """交付加工稿及其全文关键词，供调用方保存或展示。"""

    #: 按加工后的分段顺序排列的片段，沿用源媒体时间轴。
    segments: list[ProcessedSubtitleSegmentInfo]
    #: 整份加工稿的关键词。未提取到关键词时为空列表。
    global_keywords: list[str] = field(default_factory=list)
