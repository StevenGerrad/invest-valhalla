"""验证平台会话读取和平台错误转换。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from bilibili_api.exceptions import ResponseCodeException

from integration.fetcher.bilibili import (
    BilibiliCredential, BilibiliFetcher, BilibiliSessionError, load_session_credential,
)


class BilibiliSessionTest(IsolatedAsyncioTestCase):
    """使用占位凭据验证会话行为，避免发起真实登录或平台请求。"""

    def test_session_files(self) -> None:
        """区分缺失、格式错误、过期和有效文件，并屏蔽凭据。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bilibili.json"
            self.assertIsNone(load_session_credential(root))
            path.write_text('{"credential": "placeholder-secret"', encoding="utf-8")
            with self.assertRaises(BilibiliSessionError) as invalid:
                load_session_credential(root)
            self.assertNotIn("placeholder-secret", str(invalid.exception))

            data = {
                "saved_at": datetime.now(UTC).isoformat(), "expires_at": "2000-01-01T00:00:00+00:00",
                "credential": {"sessdata": "placeholder-secret"},
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(BilibiliSessionError, "已过期"):
                load_session_credential(root)

            del data["expires_at"]
            path.write_text(json.dumps(data), encoding="utf-8")
            credential = load_session_credential(root)
            self.assertEqual(credential, BilibiliCredential(sessdata="placeholder-secret"))
            self.assertNotIn("placeholder-secret", repr(credential))
            with patch("integration.fetcher.bilibili.client.load_session_credential", side_effect=AssertionError):
                BilibiliFetcher(credential, session_dir=root)

    async def test_login_required_does_not_expose_response(self) -> None:
        """测试未登录错误只留下可展示的登录提示。"""
        with patch("integration.fetcher.bilibili.client.user.User") as user:
            user.return_value.get_videos = AsyncMock(side_effect=ResponseCodeException(-101, "placeholder-secret"))
            with self.assertRaisesRegex(BilibiliSessionError, "要求登录") as error:
                await BilibiliFetcher().list_creator_videos(42)
        self.assertNotIn("placeholder-secret", str(error.exception))

    async def test_video_detail_contains_owner_mid(self) -> None:
        """验证视频详情使用平台作者标识，而不是用昵称推断归属。"""
        with patch("integration.fetcher.bilibili.client.video.Video") as video:
            video.return_value.get_info = AsyncMock(return_value={
                "bvid": "BV1xx411c7mD", "owner": {"name": "示例作者", "mid": 42},
            })
            detail = await BilibiliFetcher().get_video("BV1xx411c7mD")
        self.assertEqual(detail.author_mid, 42)
