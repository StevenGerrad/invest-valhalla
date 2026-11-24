"""在资料实体与本地 SRT、纠错 JSON 之间转换。"""

import re
from collections.abc import Iterable

from integration.converter.subtitle import SubtitleSegment as SrtSegment
from integration.converter.subtitle import render_srt

from ....entity import SubtitleMaterialEntity, SubtitleSegment

_TIMING = re.compile(r"(\d+:\d{2}:\d{2},\d{3}) --> (\d+:\d{2}:\d{2},\d{3})")


def raw_srt(segments: Iterable[SubtitleSegment]) -> str:
    """将实体中的原始字幕片段转成统一的 SRT 格式。

    :param segments: 按时间排列的原始字幕片段。
    :returns: 使用 LF 换行的 SRT 文本。
    """
    return render_srt(SrtSegment(item.start_seconds, item.end_seconds, item.text) for item in segments)


def read_srt(text: str) -> list[SubtitleSegment]:
    """从已保存的 SRT 文本还原原稿时间轴。

    :param text: 使用毫秒级时间码的 SRT 正文。
    :returns: 原稿片段列表。空文本表示静音原稿。
    :raises ValueError: 片段结构或时间码无效。
    """
    result = []
    for block in re.split(r"\n[ \t]*\n", text.strip()):
        if not block:
            continue
        number, timing, body = block.split("\n", 2)
        match = _TIMING.fullmatch(timing)
        if not number.isdecimal() or match is None:
            raise ValueError("SRT 片段缺少有效编号或时间码")
        result.append(SubtitleSegment(_seconds(match[1]), _seconds(match[2]), body))
    return result


def _seconds(value: str) -> float:
    """将 SRT 时分秒和毫秒解析成秒。

    :param value: 格式为 HH:MM:SS,mmm 的时间码。
    :returns: 相对于源媒体起点的秒数。
    """
    hms, milliseconds = value.split(",")
    hours, minutes, seconds = map(int, hms.split(":"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError("SRT 分秒超出范围")
    return hours * 3600 + minutes * 60 + seconds + int(milliseconds) / 1000


def processed_json(material: SubtitleMaterialEntity) -> dict:
    """生成与旧纠错资料结构兼容的加工 JSON。

    :param material: 包含加工稿的字幕实体。
    :returns: 包含标题、分段及全文关键词的 JSON 对象。
    """
    return {
        "bvid": material.source_key,
        "title": material.title or "",
        "sections": [
            {"heading": item.heading, "start_time": item.start_seconds, "end_time": item.end_seconds,
             "text": item.text, "keywords": list(item.keywords)}
            for item in material.optimized_segments
        ],
        "global_keywords": list(material.global_keywords),
    }


def read_processed(data: dict) -> tuple[list[SubtitleSegment], tuple[str, ...]]:
    """解析本地加工稿及全文关键词。

    :param data: 包含 sections 和可选 global_keywords 的 JSON 对象。
    :returns: 还原的加工字幕和全文关键词。
    """
    sections = [
        SubtitleSegment(
            item["start_time"], item["end_time"], item["text"], item["heading"], tuple(item.get("keywords", ())),
        )
        for item in data["sections"]
    ]
    return sections, tuple(data.get("global_keywords", ()))
