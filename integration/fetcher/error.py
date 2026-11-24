"""定义数据拉取能力向调用方报告的错误。"""


class FetchError(RuntimeError):
    """表示接入层无法获取资料，消息可以展示给用户。"""
