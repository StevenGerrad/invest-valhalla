"""声明远端资料浏览、本地资料查询和原始资料采集服务。"""

from typing import Protocol

from ...entity import AvatarIndex, MaterialIndex, Platform
from ...common.dto.material_dto import (
    BatchCollectMaterialParam,
    CollectMaterialParam,
    CollectionResult,
    DeletionResult,
    MaterialDetail,
    MaterialSelectionParam,
)
from .dto.material_service_dto import ListRemoteMaterialsParam, MaterialPage, RawMaterialDetail


class MaterialService(Protocol):
    """列出和采集原始资料，并提供本地资料的查询和删除。"""

    async def list_remote_materials(
        self,
        avatar_index: AvatarIndex,
        platform: Platform,
        param: ListRemoteMaterialsParam | None = None,
    ) -> MaterialPage:
        """分页列出数字人在指定来源上的可采集资料。

        :param avatar_index: 作者在项目内的数字人索引。
        :param platform: 要查询的来源平台。
        :param param: 分页和合集条件。为 None 时从首页读取常规投稿。
        :returns: 远端资料条目和下一页信息。
        :raises KeyError: 找不到数字人或指定平台的登记。
        :raises ValueError: 分页或合集条件无效。
        :raises IngestionError: 无法读取远端资料。
        """
        ...

    async def list_local_materials(
        self,
        avatar_index: AvatarIndex,
        platform: Platform | None = None,
    ) -> list[MaterialDetail]:
        """列出指定作者已采集的资料。

        :param avatar_index: 作者在项目内的数字人索引。
        :param platform: 可选的来源平台筛选条件。为 None 时列出所有来源。
        :returns: 资料详情列表。无匹配资料时返回空列表。
        :raises IngestionError: 无法读取本地资料。
        """
        ...

    async def get_material(self, material_index: MaterialIndex) -> MaterialDetail | None:
        """读取一份已采集资料的详情。

        :param material_index: 目标资料的本地索引。
        :returns: 对应资料详情。找不到时返回 None。
        :raises IngestionError: 无法读取本地资料。
        """
        ...

    async def get_raw_material(self, material_index: MaterialIndex) -> RawMaterialDetail | None:
        """按本地资料索引读取原稿。

        :param material_index: 目标资料的本地索引。
        :returns: 资料信息和原稿片段列表。没有原稿时返回 None，已保存的空字幕返回空片段列表。
        :raises IngestionError: 无法读取原稿。
        """
        ...

    async def list_raw_materials(
        self, avatar_index: AvatarIndex, platform: Platform | None = None,
    ) -> list[RawMaterialDetail]:
        """列出指定博主已采集的原稿。

        :param avatar_index: 博主在项目内的索引。
        :param platform: 可选的来源平台。为 None 时查询该博主的所有来源。
        :returns: 已有原稿的资料详情列表，每份原稿包含自己的片段列表。没有匹配时返回空列表。
        :raises IngestionError: 无法读取原稿列表。
        """
        ...

    async def collect_material(
        self,
        avatar_index: AvatarIndex,
        platform: Platform,
        param: CollectMaterialParam,
    ) -> CollectionResult:
        """按指定策略采集并保存一份资料的原始内容。

        :param avatar_index: 作者在项目内的数字人索引。
        :param platform: 所选资料的来源平台。
        :param param: 平台内容标识及是否跳过已有原稿的资料，默认跳过。
        :returns: 已采集或已跳过的情况，以及对应的资料详情。
        :raises KeyError: 找不到数字人或指定平台的登记。
        :raises ValueError: 平台内容标识无效。
        :raises IngestionError: 无法获取、转换或保存原始资料。
        """
        ...

    async def batch_collect_material(
        self,
        avatar_index: AvatarIndex,
        platform: Platform,
        param: BatchCollectMaterialParam,
    ) -> list[CollectionResult]:
        """批量采集原始资料，单项失败后继续处理其他项。

        :param avatar_index: 作者在项目内的数字人索引。
        :param platform: 所选资料共用的来源平台。
        :param param: 平台内容标识序列及是否跳过已有原稿的资料，默认跳过。
        :returns: 按输入顺序逐项返回采集情况。无目标时返回空列表。
        :raises KeyError: 找不到批次共用的数字人或平台登记。
        :raises ValueError: 平台内容标识序列无效。
        """
        ...

    async def delete_material(self, material_index: MaterialIndex) -> None:
        """删除本地资料，包括原始稿和加工稿。

        :param material_index: 待删除资料的本地索引。
        :raises KeyError: 找不到该资料。
        :raises IngestionError: 无法删除资料。
        """
        ...

    async def batch_delete_material(self, param: MaterialSelectionParam) -> list[DeletionResult]:
        """批量删除本地资料，单项失败后继续处理其他项。

        :param param: 待删除资料的索引序列。
        :returns: 按输入顺序逐项返回删除情况。无目标时返回空列表。
        """
        ...
