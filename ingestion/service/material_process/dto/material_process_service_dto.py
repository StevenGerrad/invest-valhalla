"""定义资料加工服务的输入参数和执行情况。"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Self

from integration.llm import ChatModelInfo

from ....entity import MaterialIndex, SubtitleMaterialEntity
from ....common.dto.material_dto import MaterialDetail
from ....common.dto.subtitle.subtitle_dto import ProcessedSubtitleInfo


@dataclass(frozen=True)
class ProcessMaterialParam:
    """指定加工一份已保存资料时的策略。"""

    #: 为 True 时跳过已有加工稿的资料，为 False 时重新加工。
    skip_existing: bool = True
    #: 本次指定的供应商和模型。为 None 时使用调用入口的既有模型配置。
    model_selection: ChatModelInfo | None = None


@dataclass(frozen=True)
class BatchProcessMaterialParam:
    """指定一次批量加工的资料和共用策略。"""

    #: 按提交顺序排列的本地资料索引。
    material_indexes: Sequence[MaterialIndex]
    #: 为 True 时跳过批次中已有加工稿的资料，为 False 时重新加工这些资料。
    skip_existing: bool = True
    #: 整批共用的供应商和模型。为 None 时使用调用入口的既有模型配置。
    model_selection: ChatModelInfo | None = None


@dataclass(frozen=True, kw_only=True)
class ProcessedMaterialDetail(MaterialDetail):
    """返回资料的来源信息及已保存的加工稿。"""

    #: 当前加工稿的内容类型为字幕。
    content_type: str = field(default="subtitle", init=False)
    #: 已保存的加工字幕及其全文关键词。
    processed_subtitle: ProcessedSubtitleInfo

    @classmethod
    def from_entity(cls, material: SubtitleMaterialEntity) -> Self:
        """生成只携带加工稿的资料详情。

        :param material: 服务已确认存在加工稿的字幕资料。
        :returns: 公共资料信息、加工片段和全文关键词。
        """
        return cls._from_entity(material, processed_subtitle=ProcessedSubtitleInfo.from_entity(material))
