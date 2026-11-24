"""解析平台公开主页地址，供登记和远端查询共用。"""

from enum import StrEnum
from urllib.parse import urlsplit


class CollectionKind(StrEnum):
    """区分 B 站新版合集与旧版系列。"""

    #: 新版合集。
    SEASON = "season"
    #: 旧版系列。
    SERIES = "series"


def parse_bilibili_creator_url(source_url: str) -> int:
    """从 B 站空间地址提取作者 MID。

    :param source_url: 作者主页或其空间子页面的 HTTP(S) 地址。
    :returns: B 站分配的正整数作者 ID。
    :raises ValueError: 地址不属于 B 站空间，或缺少有效 MID。
    """
    url = urlsplit(source_url.strip())
    mid = url.path.split("/")[1] if url.path.startswith("/") else ""
    # 限定站点和数字路径，避免把相似域名或其他页面的标识当作账号。
    if (
        url.scheme not in {"http", "https"}
        or url.netloc.lower() != "space.bilibili.com"
        or not mid.isascii()
        or not mid.isdecimal()
        or int(mid) < 1
    ):
        raise ValueError("B 站主页地址须为 https://space.bilibili.com/<MID>")
    return int(mid)


def parse_bilibili_collection_key(collection_key: str) -> tuple[CollectionKind, int]:
    """解析 CLI 和服务共用的 B 站合集标识。

    :param collection_key: 正整数 ID，或带 season:、series: 前缀的 ID。
    :returns: 平台合集类型与 ID。无前缀时使用新版合集。
    :raises ValueError: 合集类型或 ID 无效。
    """
    kind, separator, collection_id = collection_key.strip().partition(":")
    if not separator:
        kind, collection_id = "season", kind
    if kind not in CollectionKind or not collection_id.isascii() or not collection_id.isdecimal():
        raise ValueError("B 站合集标识须为正整数、season:<ID> 或 series:<ID>")
    if int(collection_id) < 1:
        raise ValueError("B 站合集 ID 须为正整数")
    return CollectionKind(kind), int(collection_id)
