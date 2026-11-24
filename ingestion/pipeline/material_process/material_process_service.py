"""声明已采集资料的加工与加工稿删除服务。"""

from typing import Protocol

from ...entity import MaterialIndex
from ..material.dto.material_service_dto import DeletionResult, MaterialSelectionParam
from .dto.material_process_service_dto import (
    BatchProcessMaterialParam,
    ProcessingResult,
    ProcessMaterialParam,
)


class MaterialProcessService(Protocol):
    """基于本地原始资料生成加工稿，并管理加工稿的删除。"""

    async def process_material(
        self,
        material_index: MaterialIndex,
        param: ProcessMaterialParam,
    ) -> ProcessingResult:
        """按指定策略加工已有原稿，保留原稿内容。

        :param material_index: 待加工资料的本地索引。
        :param param: 是否跳过已有加工稿的资料，默认跳过。
        :returns: 已加工、已跳过或无需加工的情况，以及对应的资料详情。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 无法读取原稿、完成加工或保存加工稿。
        """
        ...

    async def batch_process_material(self, param: BatchProcessMaterialParam) -> list[ProcessingResult]:
        """批量加工本地资料，单项失败后继续处理其他项。

        :param param: 待加工资料的索引序列及是否跳过已有加工稿的资料，默认跳过。
        :returns: 按输入顺序逐项返回加工情况。无目标时返回空列表。
        """
        ...

    async def delete_processed_material(self, material_index: MaterialIndex) -> None:
        """移除该资料的加工稿，保留原始资料及其登记信息。

        :param material_index: 目标资料的本地索引。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 无法删除加工稿。
        """
        ...

    async def batch_delete_processed_material(self, param: MaterialSelectionParam) -> list[DeletionResult]:
        """批量移除加工稿，保留原始资料并在单项失败后继续处理。

        :param param: 待移除加工稿的资料索引序列。
        :returns: 按输入顺序逐项返回删除情况。无目标时返回空列表。
        """
        ...
