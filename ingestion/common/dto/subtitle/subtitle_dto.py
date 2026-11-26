"""定义字幕加工与资料查询共用的原稿、加工稿和片段。"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Self

from ....entity import SubtitleMaterialEntity, SubtitleSegment


@dataclass(frozen=True)
class SubtitleSegmentInfo:
    """展示一个可按源媒体时间定位的字幕片段，适用于原稿和加工稿。"""

    #: 相对于源媒体起点的开始时间，单位为秒。
    start_seconds: float
    #: 相对于源媒体起点的结束时间，单位为秒。
    end_seconds: float
    #: 片段的字幕正文。
    text: str

    @classmethod
    def from_entity(cls, segment: SubtitleSegment) -> Self:
        """将实体片段转换为由起止时间和正文组成的 DTO。

        :param segment: 带源媒体时间的字幕片段。
        :returns: 用于查询或加工请求的字幕片段。
        """
        return cls(segment.start_seconds, segment.end_seconds, segment.text)

    @classmethod
    def from_segments(cls, segments: Iterable[SubtitleSegment]) -> list[Self]:
        """按源稿顺序转换字幕片段。

        :param segments: 待转换的原稿或加工稿片段。
        :returns: 独立的 DTO 列表。没有片段时返回空列表。
        """
        return [cls.from_entity(segment) for segment in segments]


#: 原稿按时间顺序排列。已保存的空字幕表示为空列表。
type RawSubtitle = list[SubtitleSegmentInfo]


@dataclass(frozen=True)
class SubtitleProcessParam:
    """向字幕 Agent 提交一份原稿及其标题。"""

    #: 资料标题。未知时为 None。
    title: str | None
    #: 按开始时间排序的原始字幕。没有识别出语音时为空列表。
    raw_subtitle: RawSubtitle

    @classmethod
    def from_entity(cls, material: SubtitleMaterialEntity) -> Self:
        """从已保存的资料构造字幕加工输入。

        :param material: 提供标题和原稿的字幕资料。
        :returns: 可提交给字幕 Agent 的输入。
        """
        return cls(material.title, SubtitleSegmentInfo.from_segments(material.raw_segments))


@dataclass(frozen=True)
class ProcessedSubtitleSegmentInfo(SubtitleSegmentInfo):
    """为兼容既有资料详情，保留历史加工段落的语义信息。"""

    #: 段落标题。未提供时为 None。
    heading: str | None = None
    #: 段落关键词。未提供时为空元组。
    keywords: tuple[str, ...] = ()

    @classmethod
    def from_entity(cls, segment: SubtitleSegment) -> Self:
        """为既有资料详情保留字幕片段的历史段落信息。

        :param segment: 带可选历史段落信息的字幕片段。
        :returns: 包含起止时间、正文及历史标题和关键词的 DTO。
        """
        return cls(segment.start_seconds, segment.end_seconds, segment.text, segment.heading, segment.keywords)


@dataclass(frozen=True)
class ProcessedSubtitleInfo:
    """交付加工稿及其全文关键词，供调用方保存或展示。"""

    #: 按加工后的分段顺序排列的片段，沿用源媒体时间轴。
    segments: list[SubtitleSegmentInfo]
    #: 整份加工稿的关键词。未提取到关键词时为空列表。
    global_keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_entity(cls, material: SubtitleMaterialEntity) -> Self:
        """从已保存的资料提取加工稿正文及全文关键词。

        :param material: 提供加工片段和全文关键词的字幕资料。
        :returns: 加工稿 DTO。片段包含起止时间和正文。
        """
        return cls(SubtitleSegmentInfo.from_segments(material.optimized_segments), list(material.global_keywords))
