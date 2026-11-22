"""定义采集资料支持的来源平台。"""

from enum import StrEnum


class Platform(StrEnum):
    """限定采集资料的来源平台。成员值用于配置和持久化。"""

    #: 哔哩哔哩平台，存储标识为 bilibili。
    BILIBILI = "bilibili"
