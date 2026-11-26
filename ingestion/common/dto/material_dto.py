"""定义多个采集服务共同使用的资料信息、操作参数和结果。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ...entity import MaterialIndex, Platform
from ..constant.result_status import ResultStatus


@dataclass(frozen=True)
class CollectMaterialParam:
    """指定一份远端资料及其原稿的采集策略。"""

    #: 平台内容标识，例如 B 站的 BV 号。
    source_key: str
    #: 为 True 时跳过已有原稿的资料，为 False 时重新采集。
    skip_existing: bool = True


@dataclass(frozen=True)
class BatchCollectMaterialParam:
    """指定一次批量采集的资料和共用的原稿采集策略。"""

    #: 按提交顺序排列的平台内容标识。
    source_keys: Sequence[str]
    #: 为 True 时跳过批次中已有原稿的资料，为 False 时重新采集这些资料。
    skip_existing: bool = True


@dataclass(frozen=True)
class MaterialSelectionParam:
    """指定同一次批量删除资料或加工稿涉及的本地资料。"""

    #: 按提交顺序排列的本地资料索引。
    material_indexes: Sequence[MaterialIndex]


@dataclass(frozen=True, kw_only=True)
class MaterialDetail(MaterialIndex):
    """展示本地资料的公共信息，具体查询 DTO 补充各自的正文结构。"""

    #: 资料的本地 ID。
    id: int
    #: 资料首次保存时间，带时区。
    created_at: datetime
    #: 资料最后修改时间，带时区。
    updated_at: datetime
    #: 作者的本地数字人 ID。
    author_id: int
    #: 资料所属的来源平台。
    platform: Platform
    #: 平台内容标识，例如 B 站的 BV 号。
    source_key: str
    #: 资料类型标识，例如 subtitle。
    content_type: str
    #: 资料标题。未知时为 None。
    title: str | None = None
    #: 原始资料链接。未知时为 None。
    source_url: str | None = None
    #: 平台公布的发布时间，带时区。未知时为 None。
    published_at: datetime | None = None

    def get_material_index(self) -> int:
        """取得后续查询、加工或删除所需的资料标识。

        :returns: 资料的本地 ID。
        """
        return self.id


@dataclass(frozen=True)
class CollectionResult:
    """交付一份资料的采集情况。失败状态用于批量采集。"""

    #: 此次采集对应的平台内容标识。
    source_key: str
    #: 采集成功、因已有原稿而跳过或批量项失败。
    status: ResultStatus
    #: 新保存或复用的资料详情。失败时为 None。
    material: MaterialDetail | None = None
    #: 可展示的失败原因。其他情况下为 None。
    error: str | None = None


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


@dataclass(frozen=True)
class DeletionResult:
    """交付批量删除中一份资料或其加工稿的执行情况。"""

    #: 请求删除的本地资料 ID。
    material_id: int
    #: 请求所指向的资料或加工稿删除成功或失败。
    status: ResultStatus
    #: 可展示的失败原因。删除成功时为 None。
    error: str | None = None
