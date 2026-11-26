"""定义资料采集并加工服务的参数与分阶段结果。"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from integration.llm import ChatModelInfo

from ....common.dto.material_dto import (
    BatchCollectMaterialParam,
    CollectionResult,
    CollectMaterialParam,
    MaterialDetail,
    ProcessingResult,
)
from ....common.dto.subtitle.subtitle_dto import ProcessedSubtitleInfo, RawSubtitle


@dataclass(frozen=True, init=False)
class CollectAndProcessMaterialParam(CollectMaterialParam):
    """指定一份待采集并加工的资料及两个阶段共用的策略。"""

    #: 加工使用的供应商和模型组合。为 None 时使用模型接入层提供的默认组合。
    model_selection: ChatModelInfo | None

    def __init__(
        self, source_key: str, model_selection: ChatModelInfo | None = None, skip_existing: bool = True,
    ) -> None:
        """复用采集参数，并沿用组合调用的参数顺序。

        :param source_key: 远端资料的平台内容标识。
        :param model_selection: 加工所用的供应商和模型。为 None 时使用默认组合。
        :param skip_existing: 是否分别跳过已有原稿或加工稿的阶段，默认跳过。
        """
        super().__init__(source_key, skip_existing)
        object.__setattr__(self, "model_selection", model_selection)


@dataclass(frozen=True, init=False)
class BatchCollectAndProcessMaterialParam(BatchCollectMaterialParam):
    """指定一个有序资料批次，以及该批次共用的模型和跳过策略。"""

    #: 整批加工共用的供应商和模型组合。为 None 时使用模型接入层提供的默认组合。
    model_selection: ChatModelInfo | None

    def __init__(
        self, source_keys: Sequence[str], model_selection: ChatModelInfo | None = None, skip_existing: bool = True,
    ) -> None:
        """复用批量采集参数，并沿用组合调用的参数顺序。

        :param source_keys: 按提交顺序排列的平台内容标识。
        :param model_selection: 整批加工共用的供应商和模型。为 None 时使用默认组合。
        :param skip_existing: 是否逐项、逐阶段跳过已有内容，默认跳过。
        """
        super().__init__(source_keys, skip_existing)
        object.__setattr__(self, "model_selection", model_selection)


@dataclass(frozen=True, kw_only=True)
class RawAndProcessedMaterialDetail(MaterialDetail):
    """在同一份资料详情中展示原稿和可用的加工稿。"""

    #: 当前资料的内容类型为字幕。
    content_type: str = field(default="subtitle", init=False)
    #: 按时间顺序排列的原始字幕。原稿没有识别出语音时为空列表。
    raw_subtitle: RawSubtitle
    #: 已保存的加工字幕及其全文关键词。尚无加工稿时为 None。
    processed_subtitle: ProcessedSubtitleInfo | None = None


@dataclass(frozen=True)
class CollectAndProcessResult:
    """分别返回同一份资料的采集结果和加工结果。"""

    #: 原稿采集阶段的结果，包含来源标识及可用的本地资料详情。
    collection: CollectionResult
    #: 加工阶段的结果。批量项采集失败而未进入加工阶段时为 None。
    processing: ProcessingResult | None = None
