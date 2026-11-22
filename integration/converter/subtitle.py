"""定义可按时间引用的字幕片段及 SRT 序列化。"""

import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SubtitleSegment:
    """表示一个字幕片段，起止位置均为相对于输入媒体起点的秒数。"""

    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        """校验时间轴和字幕文本，供调用方直接构造或接收转录结果。

        :raises ValueError: 时间非有限值、范围无效或文本为空白。
        """
        if not (math.isfinite(self.start) and math.isfinite(self.end) and 0 <= self.start <= self.end):
            raise ValueError("字幕时间必须为有限秒数，且满足 0 <= start <= end")
        if not self.text.strip():
            raise ValueError("字幕文本不能为空")


def _srt_time(seconds: float) -> str:
    """将秒数舍入到最近的毫秒，生成 SRT 时间戳。

    :param seconds: 非负的有限秒数。
    :returns: 使用逗号分隔毫秒的 SRT 时间戳。
    """
    whole_seconds = int(seconds)
    carry, milliseconds = divmod(round((seconds - whole_seconds) * 1000), 1000)
    total_seconds = whole_seconds + carry
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def render_srt(segments: Iterable[SubtitleSegment]) -> str:
    """按调用方提供的顺序将字幕片段序列化为 SRT 文本。

    :param segments: 带有起止秒数的字幕片段。空序列生成空字符串。
    :returns: 使用 LF 换行的 SRT 文本，可由调用方保存为 UTF-8 文件。
    """
    cues = []
    for index, segment in enumerate(segments, start=1):
        # SRT 用空行分隔字幕块，移除正文中的空白行以保留片段边界。
        text = "\n".join(line for line in segment.text.splitlines() if line.strip())
        cues.append(f"{index}\n{_srt_time(segment.start)} --> {_srt_time(segment.end)}\n{text}\n\n")
    return "".join(cues)
