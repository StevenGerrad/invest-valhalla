"""声明采集后加工及同时读取原稿和加工稿的服务接口。"""

from typing import Protocol

from ...entity import AvatarIndex, MaterialIndex, Platform
from .dto.material_collect_and_process_service_dto import (
    BatchCollectAndProcessMaterialParam,
    CollectAndProcessMaterialParam,
    CollectAndProcessResult,
    RawAndProcessedMaterialDetail,
)


class MaterialCollectAndProcessService(Protocol):
    """编排原稿采集和后续加工，分别交付两个阶段的执行结果。

    默认按阶段跳过已有稿件。已有原稿时复用原稿，只有原稿时继续加工，
    两份稿件都有时跳过两步。关闭跳过策略后重新采集和加工。

    省略模型组合时，使用通用能力接入提供的默认模型。
    有待加工内容时，先探测所选模型的可用性，再提交字幕。
    加工阶段失败时保留已保存的原稿，供后续单独重试。
    """

    async def get_raw_and_processed_material(
        self, material_index: MaterialIndex,
    ) -> RawAndProcessedMaterialDetail | None:
        """按本地资料索引读取原稿及可用的加工稿。

        :param material_index: 目标资料的本地索引。
        :returns: 资料信息及各自独立分段的原稿与加工稿。资料不存在时返回 None，仅有原稿时 processed_subtitle 为 None。
        :raises IngestionError: 无法读取资料。
        """
        ...

    async def list_raw_and_processed_material(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[RawAndProcessedMaterialDetail]:
        """列出指定博主的原稿和各自可用的加工稿。

        :param avatar_index: 博主在项目内的索引。
        :param platform: 可选的来源平台。为 None 时查询该博主的所有来源。
        :returns: 原稿及其可用加工稿的组合详情列表，包含尚无加工稿的资料。没有匹配项时返回空列表。
        :raises IngestionError: 无法读取资料列表。
        """
        ...

    async def collect_and_process_material(
        self,
        avatar_index: AvatarIndex,
        platform: Platform,
        param: CollectAndProcessMaterialParam,
    ) -> CollectAndProcessResult:
        """采集一份资料的原稿，并按策略加工已保存的内容。

        :param avatar_index: 作者在项目内的数字人索引。
        :param platform: 所选资料的来源平台。
        :param param: 平台内容标识、模型选择及两个阶段共用的跳过策略。
        :returns: 该资料的采集和加工结果，包含跳过和无需加工的情况。
        :raises KeyError: 找不到数字人或指定平台的登记。
        :raises ValueError: 平台内容标识或模型选择无效。
        :raises IngestionError: 采集、模型探测、加工或保存失败。
        """
        ...

    async def batch_collect_and_process_material(
        self,
        avatar_index: AvatarIndex,
        platform: Platform,
        param: BatchCollectAndProcessMaterialParam,
    ) -> list[CollectAndProcessResult]:
        """批量采集资料并加工，逐项报告两个阶段的结果。

        原稿采集失败的条目跳过加工。单项失败后继续处理其他条目。
        批次共用参数无效时直接报错。

        :param avatar_index: 批次共用的数字人索引。
        :param platform: 批次共用的来源平台。
        :param param: 有序的来源标识、共用的模型选择及跳过策略。
        :returns: 按输入顺序排列的逐项结果。没有目标时返回空列表。
        :raises KeyError: 找不到批次共用的数字人或指定平台的登记。
        :raises ValueError: 批次共用的平台、参数结构或模型选择无效。
        :raises IngestionError: 无法读取批次共用的登记或配置。
        """
        ...
