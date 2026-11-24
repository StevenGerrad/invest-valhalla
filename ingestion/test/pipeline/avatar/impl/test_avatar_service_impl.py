"""验证博主服务的登记、解除绑定和删除规则。"""

from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from ingestion.entity import AvatarEntity, Platform
from ingestion.pipeline import AvatarPlatformParam, CreateAvatarParam, IngestionConflictError, UpdateAvatarParam
from ingestion.pipeline.avatar.impl.avatar_service_impl import AvatarServiceImpl
from ingestion.storage import AvatarRepository, MaterialRepository


class AvatarServiceTest(IsolatedAsyncioTestCase):
    """使用 Repository 接口替身验证服务规则。"""

    async def test_registration_and_deletion_rules(self) -> None:
        """重复平台不能保存，解除平台不删资料，存在资料时拒绝删除博主。"""
        avatars, materials = Mock(spec=AvatarRepository), Mock(spec=MaterialRepository)
        avatar = AvatarEntity(1, "作者", ["https://space.bilibili.com/42"])
        avatars.get.return_value = avatar
        avatars.create.return_value = avatar
        avatars.update.side_effect = lambda updated: updated
        materials.list_by_author.return_value = [Mock()]
        service = AvatarServiceImpl(avatars, materials)
        platform = AvatarPlatformParam(Platform.BILIBILI, "https://space.bilibili.com/42/video")
        with self.assertRaises(IngestionConflictError):
            await service.create_avatar(CreateAvatarParam("作者", [platform, platform]))
        avatars.create.assert_not_called()
        info = await service.create_avatar(CreateAvatarParam(" 作者 ", [platform]))
        avatars.create.assert_called_once_with("作者", ["https://space.bilibili.com/42"])
        self.assertEqual(info.get_avatar_index(), avatar.id)
        self.assertEqual((await service.update_avatar(info, UpdateAvatarParam("新名称"))).name, "新名称")
        with self.assertRaises(IngestionConflictError):
            await service.add_platform(info, platform)
        await service.remove_platform(info, Platform.BILIBILI)
        self.assertEqual(avatars.update.call_args.args[0].source_urls, [])
        materials.delete.assert_not_called()
        with self.assertRaises(IngestionConflictError):
            await service.delete_avatar(info)
        avatars.delete.assert_not_called()
