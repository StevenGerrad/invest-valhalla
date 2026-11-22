"""验证 HTML 正文选择、顺序及源码坐标。"""

import unittest

from integration.converter import WebParagraph, extract_web_text


class WebpageTest(unittest.TestCase):
    """使用静态 HTML 验证正文提取和段落引用位置。"""

    def test_main_retains_heading_and_source_coordinates(self) -> None:
        """选中 main 后保留其标题及嵌套 article，并记录首个文本块的坐标。"""
        html = (
            "<head><title>站点</title></head>\n"
            "<article><p>侧栏内容</p></article>\n"
            "<main><h1>报告</h1><nav><p>菜单</p></nav>\n"
            "  <article><p>现金<strong>流</strong> &amp; 收益</p>\n"
            "  <p>第二段<script>const label = '忽略'</script><br>换行</p></article></main>"
        )
        self.assertEqual(extract_web_text(html), (
            WebParagraph(1, "报告", 3, 10),
            WebParagraph(2, "现金流 & 收益", 4, 14),
            WebParagraph(3, "第二段 换行", 5, 5),
        ))

    def test_fallback_for_article_and_fragment(self) -> None:
        """优先使用有文字的 article，并兼容无语义容器和省略段落结束标签的片段。"""
        self.assertEqual(extract_web_text("站点<main></main><article><p>文章</article>"),
                         (WebParagraph(1, "文章", 1, 27),))
        self.assertEqual(extract_web_text("<div><p>甲<p>乙</div>"),
                         (WebParagraph(1, "甲", 1, 8), WebParagraph(2, "乙", 1, 12)))
        self.assertEqual(extract_web_text("<head><title>标题</title></head><nav>菜单</nav>"), ())
