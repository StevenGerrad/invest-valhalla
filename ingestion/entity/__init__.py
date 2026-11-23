"""采集流程与存储接口共享的领域实体。"""

from .avatar import AvatarEntity
from .index import AvatarIndex, MaterialIndex
from .material import MaterialEntity
from .platform import Platform
from .subtitle_material import SubtitleMaterialEntity, SubtitleSegment

__all__ = [
    "AvatarEntity",
    "AvatarIndex",
    "MaterialEntity",
    "MaterialIndex",
    "Platform",
    "SubtitleMaterialEntity",
    "SubtitleSegment",
]
