"""从已读取的 HTML 中提取带源码位置的正文段落。"""

from dataclasses import dataclass
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset({
    "address", "article", "blockquote", "body", "caption", "dd", "div", "dl", "dt",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
})
_IGNORED_TAGS = frozenset({
    "aside", "button", "dialog", "footer", "form", "head", "iframe", "nav", "noscript",
    "script", "style", "svg", "template", "title",
})


@dataclass(frozen=True)
class WebParagraph:
    """表示可引用的正文段落及其在传入 HTML 中的定位。

    index 从 1 开始，表示提取结果中的段落序号。source_line 从 1 开始，
    source_column 从 0 开始，两者定位到该段首个含正文的源码文本块起点。
    """

    index: int
    text: str
    source_line: int
    source_column: int


class _BodyParser(HTMLParser):
    """按 HTML 块边界收集正文候选段落，保留源码坐标和语义区域。"""

    def __init__(self) -> None:
        """初始化段落缓冲区，启用 HTML 实体解码。"""
        super().__init__(convert_charrefs=True)
        self._ignored: list[str] = []
        self._main_depth = 0
        self._article_depth = 0
        self._parts: list[str] = []
        self._position: tuple[int, int] | None = None
        self._blocks: list[tuple[int, str, tuple[int, int]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """记录语义区域，并在进入块元素前结束上一段。

        :param tag: HTMLParser 归一化为小写的标签名。
        :param attrs: HTMLParser 提供的属性列表。
        """
        if tag in _IGNORED_TAGS:
            self._ignored.append(tag)
            return
        if self._ignored:
            return
        if tag in _BLOCK_TAGS:
            self._finish_block()
        if tag == "main":
            self._main_depth += 1
        elif tag == "article":
            self._article_depth += 1
        elif tag == "br":
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        """结束当前块，并按需退出被排除的子树或语义区域。

        :param tag: HTMLParser 归一化为小写的标签名。
        """
        if self._ignored:
            if tag == self._ignored[-1]:
                self._ignored.pop()
            return
        if tag in _BLOCK_TAGS:
            self._finish_block()
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        elif tag == "article" and self._article_depth:
            self._article_depth -= 1

    def handle_data(self, data: str) -> None:
        """累积同一段落的文本，记录首个非空文本块的位置。

        :param data: HTMLParser 解码后的文本。
        """
        if self._ignored:
            return
        if self._position is None and data.strip():
            self._position = self.getpos()
        self._parts.append(data)

    def _finish_block(self) -> None:
        """归一化段落空白并记录其所属区域，随后清空段落缓冲区。"""
        if self._position is not None:
            # 保留行内标签两侧的原始文本衔接，只归一化已有的连续空白。
            text = " ".join("".join(self._parts).split())
            priority = 2 if self._main_depth else int(bool(self._article_depth))
            self._blocks.append((priority, text, self._position))
        self._parts.clear()
        self._position = None

    def paragraphs(self) -> tuple[WebParagraph, ...]:
        """选择有正文的最高优先级区域，并按源码顺序为段落编号。

        :returns: 依次优先选取 main、article 或普通正文得到的段落。
        """
        self._finish_block()
        # 空的语义容器不妨碍回退到页面中其他可用文本。
        preferred = max((priority for priority, _, _ in self._blocks), default=0)
        selected = ((text, position) for priority, text, position in self._blocks
                    if priority == preferred)
        return tuple(WebParagraph(index, text, *position)
                     for index, (text, position) in enumerate(selected, start=1))


def extract_web_text(html: str) -> tuple[WebParagraph, ...]:
    """提取静态 HTML 正文，保留每段在 HTML 源码中的位置。

    :param html: 调用方按网页字符编码解码后的 HTML 字符串。
    :returns: 依次优先选取 main、article 或普通正文得到的段落。无正文时返回空元组。
    """
    parser = _BodyParser()
    parser.feed(html)
    parser.close()
    return parser.paragraphs()
