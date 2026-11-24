"""定义存储实现向调用方报告的错误。"""


class RepositoryConflictError(RuntimeError):
    """表示存储记录与操作要求的状态不一致。"""
