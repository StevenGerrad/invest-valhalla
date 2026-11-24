"""实现本地数字人登记和平台账号维护。"""

import logging
from collections.abc import Callable
from dataclasses import replace
from time import perf_counter
from urllib.parse import urlsplit

from integration.fetcher.address import parse_bilibili_creator_url

from ingestion.entity import AvatarEntity, AvatarIndex, Platform
from ingestion.pipeline._support import repository_call
from ingestion.pipeline.error import IngestionConflictError, IngestionError
from ingestion.storage import AvatarRepository, MaterialRepository

from ..avatar_service import AvatarService
from ..dto.avatar_service_dto import (
    AvatarInfo,
    AvatarPlatformInfo,
    AvatarPlatformParam,
    CreateAvatarParam,
    UpdateAvatarParam,
)

logger = logging.getLogger(__name__)
_PLATFORM_HOME: dict[Platform, tuple[str, Callable[[str], int]]] = {
    Platform.BILIBILI: ("space.bilibili.com", parse_bilibili_creator_url),
}


class AvatarServiceImpl(AvatarService):
    """管理作者和平台登记，通过仓储处理持久化，通过 DTO 提供查询结果。"""

    def __init__(self, avatars: AvatarRepository, materials: MaterialRepository) -> None:
        """接收博主和资料仓储。

        :param avatars: 数字人登记仓储。
        :param materials: 用于检查删除前关联资料的仓储。
        """
        self._avatars = avatars
        self._materials = materials

    async def list_avatars(self) -> list[AvatarInfo]:
        """列出所有已登记博主。

        :returns: 博主信息列表，未登记时为空。
        :raises IngestionError: 无法读取博主信息。
        """
        started = perf_counter()
        avatars = [_avatar_info(avatar) for avatar in await repository_call(self._avatars.list_all)]
        logger.debug("博主列表 count=%d elapsed=%.3fs", len(avatars), perf_counter() - started)
        return avatars

    async def get_avatar(self, avatar_index: AvatarIndex) -> AvatarInfo | None:
        """查询指定博主。

        :param avatar_index: 博主本地索引。
        :returns: 博主信息，未找到时为 None。
        :raises IngestionError: 无法读取博主信息。
        """
        avatar_id = avatar_index.get_avatar_index()
        avatar = await repository_call(self._avatars.get, avatar_id)
        logger.debug("查询博主 avatar_id=%d found=%s", avatar_id, avatar is not None)
        return _avatar_info(avatar) if avatar is not None else None

    async def create_avatar(self, param: CreateAvatarParam) -> AvatarInfo:
        """创建博主并一次性登记已提交的平台账号。

        :param param: 博主名称及可选的平台账号。
        :returns: 含本地 ID 的登记信息。
        :raises ValueError: 名称或平台主页无效。
        :raises IngestionConflictError: 同一批登记重复指定平台。
        :raises IngestionError: 无法保存博主。
        """
        name = _name(param.name)
        accounts: dict[Platform, str] = {}
        # 所有账号校验完成后再创建记录，避免登记一部分后才发现冲突。
        for account in param.platforms:
            if account.platform in accounts:
                raise IngestionConflictError(f"平台 {account.platform} 已登记")
            accounts[account.platform] = _canonical_url(account)
        avatar = await repository_call(self._avatars.create, name, list(accounts.values()))
        logger.info("博主已登记 avatar_id=%d platform_count=%d", avatar.id, len(accounts))
        return _avatar_info(avatar)

    async def update_avatar(self, avatar_index: AvatarIndex, param: UpdateAvatarParam) -> AvatarInfo:
        """更新博主名称并保留平台账号。

        :param avatar_index: 博主本地索引。
        :param param: 新的博主名称。
        :returns: 更新后的登记信息。
        :raises KeyError: 找不到博主。
        :raises ValueError: 名称为空。
        :raises IngestionError: 无法读写登记。
        """
        avatar = await self._require_avatar(avatar_index)
        updated = await repository_call(self._avatars.update, replace(avatar, name=_name(param.name)))
        logger.info("博主名称已更新 avatar_id=%d", updated.id)
        return _avatar_info(updated)

    async def add_platform(self, avatar_index: AvatarIndex, param: AvatarPlatformParam) -> AvatarInfo:
        """为博主首次登记指定平台账号。

        :param avatar_index: 博主本地索引。
        :param param: 平台和主页地址。
        :returns: 更新后的登记信息。
        :raises KeyError: 找不到博主。
        :raises ValueError: 平台主页无效。
        :raises IngestionConflictError: 平台已登记。
        :raises IngestionError: 无法读写登记。
        """
        avatar = await self._require_avatar(avatar_index)
        accounts = _platform_accounts(avatar)
        if param.platform in accounts:
            logger.warning("平台登记冲突 avatar_id=%d platform=%s", avatar.id, param.platform.value)
            raise IngestionConflictError(f"平台 {param.platform} 已登记")
        accounts[param.platform] = _canonical_url(param)
        updated = await self._save_platforms(avatar, accounts)
        logger.info("已登记博主平台 avatar_id=%d platform=%s", avatar.id, param.platform.value)
        return updated

    async def update_platform(self, avatar_index: AvatarIndex, param: AvatarPlatformParam) -> AvatarInfo:
        """更改已登记平台的主页地址。

        :param avatar_index: 博主本地索引。
        :param param: 已登记的平台和新主页地址。
        :returns: 更新后的登记信息。
        :raises KeyError: 找不到博主或原平台登记。
        :raises ValueError: 平台主页无效。
        :raises IngestionError: 无法读写登记。
        """
        avatar = await self._require_avatar(avatar_index)
        accounts = _platform_accounts(avatar)
        if param.platform not in accounts:
            raise KeyError(f"平台 {param.platform} 尚未登记")
        accounts[param.platform] = _canonical_url(param)
        updated = await self._save_platforms(avatar, accounts)
        logger.info("已更新博主平台 avatar_id=%d platform=%s", avatar.id, param.platform.value)
        return updated

    async def remove_platform(self, avatar_index: AvatarIndex, platform: Platform) -> None:
        """解除平台登记并保留已采集资料。

        :param avatar_index: 博主本地索引。
        :param platform: 需要解除的平台。
        :raises KeyError: 找不到博主或原平台登记。
        :raises IngestionError: 无法读写登记。
        """
        avatar = await self._require_avatar(avatar_index)
        accounts = _platform_accounts(avatar)
        if platform not in accounts:
            raise KeyError(f"平台 {platform} 尚未登记")
        del accounts[platform]
        await self._save_platforms(avatar, accounts)
        logger.info("已解除博主平台登记 avatar_id=%d platform=%s", avatar.id, platform.value)

    async def delete_avatar(self, avatar_index: AvatarIndex) -> None:
        """删除没有关联资料的博主。

        :param avatar_index: 博主本地索引。
        :raises KeyError: 找不到博主。
        :raises IngestionConflictError: 博主仍有关联资料。
        :raises IngestionError: 无法读写登记。
        """
        avatar = await self._require_avatar(avatar_index)
        if await repository_call(self._materials.list_by_author, avatar.id):
            logger.warning("拒绝删除仍有关联资料的博主 avatar_id=%d", avatar.id)
            raise IngestionConflictError(f"博主 {avatar.id} 仍有关联资料")
        await repository_call(self._avatars.delete, avatar.id)
        logger.info("博主已删除 avatar_id=%d", avatar.id)

    async def _require_avatar(self, avatar_index: AvatarIndex) -> AvatarEntity:
        """读取需要修改的博主，缺失时报告明确的本地 ID。

        :param avatar_index: 博主本地索引。
        :returns: 仓储中的博主实体。
        :raises KeyError: 找不到博主。
        """
        avatar_id = avatar_index.get_avatar_index()
        avatar = await repository_call(self._avatars.get, avatar_id)
        if avatar is None:
            logger.debug("博主登记不存在 avatar_id=%d", avatar_id)
            raise KeyError(f"找不到博主 ID {avatar_id}")
        return avatar

    async def _save_platforms(self, avatar: AvatarEntity, accounts: dict[Platform, str]) -> AvatarInfo:
        """把平台映射转换回实体约定的主页地址列表并保存。

        :param avatar: 已登记的博主实体。
        :param accounts: 更新后的平台和主页对应关系。
        :returns: 更新后的登记信息。
        """
        return _avatar_info(await repository_call(
            self._avatars.update, replace(avatar, source_urls=list(accounts.values())),
        ))


def _name(name: str) -> str:
    """清理显示名称的两端空白。

    :param name: 待登记名称。
    :returns: 非空的显示名称。
    :raises ValueError: 名称没有有效内容。
    """
    normalized = name.strip()
    if not normalized:
        raise ValueError("博主名称不能为空")
    return normalized


def _canonical_url(param: AvatarPlatformParam) -> str:
    """把来源主页归一为可直接跳转的账号地址。

    :param param: 声明的平台和主页地址。
    :returns: 规范的主页地址。
    :raises ValueError: 平台不受支持或地址无效。
    """
    home = _PLATFORM_HOME.get(param.platform)
    if home is None:
        raise ValueError(f"尚未支持平台 {param.platform}")
    host, parse_account_id = home
    return f"https://{host}/{parse_account_id(param.source_url)}"


def _platform_accounts(avatar: AvatarEntity) -> dict[Platform, str]:
    """由仓储中的主页地址还原现有平台账号。

    :param avatar: 带有平台主页列表的博主。
    :returns: 按登记顺序排列的平台主页映射。
    :raises IngestionError: 登记中存在无效主页或重复平台。
    """
    accounts = {}
    for url in avatar.source_urls:
        try:
            host = urlsplit(url).hostname
            platform = next((key for key, home in _PLATFORM_HOME.items() if home[0] == host), None)
            if platform is None:
                raise ValueError("平台主页地址不受支持")
            canonical = _canonical_url(AvatarPlatformParam(platform, url))
        except ValueError:
            raise IngestionError(f"博主 {avatar.id} 的平台主页登记无效") from None
        if platform in accounts:
            raise IngestionError(f"博主 {avatar.id} 有重复的平台登记")
        accounts[platform] = canonical
    return accounts


def _avatar_info(avatar: AvatarEntity) -> AvatarInfo:
    """转换博主实体并还原平台账号信息。

    :param avatar: 已登记的实体。
    :returns: 交互层可展示和引用的博主信息。
    """
    platforms = [AvatarPlatformInfo(platform, url) for platform, url in _platform_accounts(avatar).items()]
    return AvatarInfo(avatar.id, avatar.name, platforms)
