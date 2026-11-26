"""声明已采集资料的加工、查询和加工稿删除服务。"""

from typing import Protocol

from ...entity import AvatarIndex, MaterialIndex, Platform
from ...common.dto.material_dto import DeletionResult, MaterialSelectionParam, ProcessingResult
from .dto.material_process_service_dto import (
    BatchProcessMaterialParam,
    ProcessedMaterialDetail,
    ProcessMaterialParam,
)


class MaterialProcessService(Protocol):
    """基于本地原稿生成加工稿，并提供加工稿的查询和删除。"""

    async def get_processed_material(self, material_index: MaterialIndex) -> ProcessedMaterialDetail | None:
        """按本地资料索引读取已保存的加工稿。

        :param material_index: 目标资料的本地索引。
        :returns: 资料信息、加工字幕片段和全文关键词。资料不存在或尚无加工稿时返回 None。
        :raises IngestionError: 无法读取加工稿。
        """
        ...

    async def list_processed_materials(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[ProcessedMaterialDetail]:
        """列出指定博主已有加工稿的资料。

        :param avatar_index: 博主在项目内的索引。
        :param platform: 可选的来源平台。为 None 时查询该博主的所有来源。
        :returns: 已有加工稿的资料详情列表，每份稿件提供自己的片段和全文关键词。无匹配时返回空列表。
        :raises IngestionError: 无法读取加工稿列表。
        """
        ...

    async def process_material(
        self,
        material_index: MaterialIndex,
        param: ProcessMaterialParam,
    ) -> ProcessingResult:
        """按指定策略加工已有原稿，保留原稿内容。

        :param material_index: 待加工资料的本地索引。
        :param param: 是否跳过已有加工稿，以及可选的供应商和模型。
        :returns: 已加工、已跳过或无需加工的情况，以及对应的资料详情。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 无法读取原稿、完成加工或保存加工稿。
        """
        ...

    async def batch_process_material(self, param: BatchProcessMaterialParam) -> list[ProcessingResult]:
        """批量加工本地资料，单项失败后继续处理其他项。

        :param param: 待加工资料的索引序列，以及整批共用的跳过策略和可选模型。
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
