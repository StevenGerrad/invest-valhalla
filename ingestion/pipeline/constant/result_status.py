"""定义采集服务共用的结果状态。"""

from enum import StrEnum


class ResultStatus(StrEnum):
    """描述资料采集、加工或删除的执行情况。"""

    #: 请求的操作已成功完成。
    SUCCESS = "success"
    #: 因已有原稿或加工稿而跳过。
    SKIPPED = "skipped"
    #: 此资料无需加工。
    NOT_REQUIRED = "not_required"
    #: 批量操作中的单项执行失败。
    FAILED = "failed"
