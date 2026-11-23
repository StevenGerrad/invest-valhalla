"""定义采集服务向交互层报告的操作异常。"""


class IngestionError(RuntimeError):
    """报告采集服务无法完成的操作，例如读取来源或持久化失败。"""


class IngestionConflictError(IngestionError):
    """报告与当前登记或资料状态冲突的操作。"""
