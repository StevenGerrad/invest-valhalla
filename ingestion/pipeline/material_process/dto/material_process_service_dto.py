"""定义资料加工服务的输入参数和执行情况。"""

from collections.abc import Sequence
from dataclasses import dataclass

from ....entity import MaterialIndex
from ...constant.result_status import ResultStatus
from ...material.dto.material_service_dto import MaterialDetail


@dataclass(frozen=True)
class ProcessMaterialParam:
    """指定加工一份已保存资料时的策略。"""

    #: 为 True 时跳过已有加工稿的资料，为 False 时重新加工。
    skip_existing: bool = True


@dataclass(frozen=True)
class BatchProcessMaterialParam:
    """指定一次批量加工的资料和共用策略。"""

    #: 按提交顺序排列的本地资料索引。
    material_indexes: Sequence[MaterialIndex]
    #: 为 True 时跳过批次中已有加工稿的资料，为 False 时重新加工这些资料。
    skip_existing: bool = True


@dataclass(frozen=True)
class ProcessingResult:
    """交付一份资料的加工情况。失败状态用于批量加工。"""

    #: 此次加工对应的本地资料 ID。
    material_id: int
    #: 加工成功、跳过、无需加工或批量项失败。
    status: ResultStatus
    #: 加工后或直接复用的资料详情。失败时为 None。
    material: MaterialDetail | None = None
    #: 可展示的失败原因。其他情况下为 None。
    error: str | None = None
