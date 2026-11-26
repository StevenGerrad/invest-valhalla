"""导出数据采集服务接口与交互层共享的类型。"""

from .avatar.avatar_service import AvatarService
from .avatar.dto.avatar_service_dto import (
    AvatarInfo,
    AvatarPlatformInfo,
    AvatarPlatformParam,
    CreateAvatarParam,
    UpdateAvatarParam,
)
from ..common.dto.material_dto import (
    BatchCollectMaterialParam,
    CollectionResult,
    CollectMaterialParam,
    DeletionResult,
    MaterialDetail,
    MaterialSelectionParam,
    ProcessingResult,
)
from ..common.dto.subtitle.subtitle_dto import ProcessedSubtitleInfo, RawSubtitle, SubtitleSegmentInfo
from ..common.constant.result_status import ResultStatus
from .error import IngestionConflictError, IngestionError
from .material.dto.material_collect_and_process_service_dto import (
    BatchCollectAndProcessMaterialParam,
    CollectAndProcessMaterialParam,
    CollectAndProcessResult,
    RawAndProcessedMaterialDetail,
)
from .material.dto.material_service_dto import (
    ListRemoteMaterialsParam, MaterialListItem, MaterialPage, RawMaterialDetail, SubtitleMaterialDetail,
)
from .material.material_collect_and_process_service import MaterialCollectAndProcessService
from .material.material_service import MaterialService
from .material_process.dto.material_process_service_dto import (
    BatchProcessMaterialParam,
    ProcessedMaterialDetail,
    ProcessMaterialParam,
)
from .material_process.material_process_service import MaterialProcessService

__all__ = [
    "AvatarInfo",
    "AvatarPlatformInfo",
    "AvatarPlatformParam",
    "AvatarService",
    "BatchCollectAndProcessMaterialParam",
    "BatchCollectMaterialParam",
    "BatchProcessMaterialParam",
    "CollectAndProcessMaterialParam",
    "CollectAndProcessResult",
    "CollectMaterialParam",
    "CollectionResult",
    "CreateAvatarParam",
    "DeletionResult",
    "IngestionConflictError",
    "IngestionError",
    "ListRemoteMaterialsParam",
    "MaterialCollectAndProcessService",
    "MaterialDetail",
    "MaterialListItem",
    "MaterialPage",
    "MaterialProcessService",
    "MaterialSelectionParam",
    "MaterialService",
    "ProcessedMaterialDetail",
    "ProcessedSubtitleInfo",
    "ProcessMaterialParam",
    "ProcessingResult",
    "RawAndProcessedMaterialDetail",
    "RawMaterialDetail",
    "RawSubtitle",
    "ResultStatus",
    "SubtitleMaterialDetail",
    "SubtitleSegmentInfo",
    "UpdateAvatarParam",
]
