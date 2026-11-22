"""暴露采集服务层使用的存储接口。"""

from .avatar_repository import AvatarRepository
from .material_repository import MaterialRepository

__all__ = ["AvatarRepository", "MaterialRepository"]
