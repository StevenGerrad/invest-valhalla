"""






验证字幕时间定位及 SRT 格式边界。"""

import unittest

from integration.converter import SubtitleSegment, render_srt


class SubtitleTest(unittest.TestCase):
    """验证时间戳格式和字幕正文的块分隔约定。"""

    def test_render_srt_rounds_over_second_boundary(self) -> None:
        """毫秒舍入可以跨整秒进位，正文空行不会分割字幕片段。"""
        segments = (SubtitleSegment(59.9997, 61.001, "第一行\r\n\r\n第二行"),)
        self.assertEqual(render_srt(segments), "1\n00:01:00,000 --> 00:01:01,001\n第一行\n第二行\n\n")
        self.assertEqual(render_srt(()), "")

    def test_rejects_invalid_times(self) -> None:
        """拒绝无法用于引用的负值、反向范围和非有限时间戳。"""
        for start, end in ((-1, 0), (3, 2), (float("nan"), 2), (0, float("inf"))):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                SubtitleSegment(start, end, "正文")
