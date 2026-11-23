"""导出数据采集服务接口与交互层共享的类型。"""

from .avatar_service import AvatarService
from .constant.result_status import ResultStatus
from .dto.avatar_service_dto import (
    AvatarInfo,
    AvatarPlatformInfo,
    AvatarPlatformParam,
    CreateAvatarParam,
    UpdateAvatarParam,
)
from .dto.material_process_service_dto import (
    BatchProcessMaterialParam,
    ProcessingResult,
    ProcessMaterialParam,
)
from .dto.material_service_dto import (
    BatchCollectMaterialParam,
    CollectMaterialParam,
    CollectionResult,
    DeletionResult,
    ListRemoteMaterialsParam,
    MaterialDetail,
    MaterialListItem,
    MaterialPage,
    MaterialSelectionParam,
    SubtitleMaterialDetail,
    SubtitleSegmentInfo,
)
from .error import IngestionConflictError, IngestionError
from .material_process_service import MaterialProcessService
from .material_service import MaterialService

__all__ = [
    "AvatarInfo",
    "AvatarPlatformInfo",
    "AvatarPlatformParam",
    "AvatarService",
    "BatchCollectMaterialParam",
    "BatchProcessMaterialParam",
    "CollectMaterialParam",
    "CollectionResult",
    "CreateAvatarParam",
    "DeletionResult",
    "IngestionConflictError",
    "IngestionError",
    "ListRemoteMaterialsParam",
    "MaterialDetail",
    "MaterialListItem",
    "MaterialPage",
    "MaterialProcessService",
    "MaterialSelectionParam",
    "MaterialService",
    "ProcessMaterialParam",
    "ProcessingResult",
    "ResultStatus",
    "SubtitleMaterialDetail",
    "SubtitleSegmentInfo",
    "UpdateAvatarParam",
]
