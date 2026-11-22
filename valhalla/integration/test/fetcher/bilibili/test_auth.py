"""离线验证 B 站扫码状态和登录凭据。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bilibili_api.login_v2 import QrCodeLoginEvents

from valhalla.integration.fetcher.bilibili import auth as bilibili_auth


class BilibiliAuthTests(unittest.IsolatedAsyncioTestCase):
    """验证扫码状态转换和凭据读写约定，通过模拟 SDK 响应隔离网络依赖。"""

    async def test_qr_statuses_and_credentials(self):
        """验证凭据在登录成功后才返回，并且对象的 repr 输出隐藏凭据。"""
        auth = SimpleNamespace(
            generate_qrcode=AsyncMock(),
            get_qrcode_picture=lambda: SimpleNamespace(content=b"image"),
            get_credential=lambda: bilibili_auth.Credential(sessdata="test-secret"),
            check_state=AsyncMock(side_effect=[
                QrCodeLoginEvents.SCAN, QrCodeLoginEvents.CONF, QrCodeLoginEvents.DONE,
            ]),
        )
        with patch.object(bilibili_auth, "QrCodeLogin", return_value=auth):
            challenge = await bilibili_auth.start_qr_login()
        self.assertEqual(challenge.image_png, b"image")
        waiting_statuses = (
            bilibili_auth.QrLoginStatus.WAITING_FOR_SCAN,
            bilibili_auth.QrLoginStatus.WAITING_FOR_CONFIRMATION,
        )
        for status in waiting_statuses:
            result = await bilibili_auth.poll_qr_login(challenge.session)
            self.assertEqual(result.status, status)
            self.assertIsNone(result.credential)
        result = await bilibili_auth.poll_qr_login(challenge.session)
        self.assertEqual(result.status, bilibili_auth.QrLoginStatus.AUTHENTICATED)
        self.assertEqual(result.credential.sessdata, "test-secret")
        self.assertNotIn("test-secret", repr(result.credential))
        self.assertNotIn("test-secret", repr(result))
        # 成功后再次查询应复用终态。如果 SDK 被再次调用，模拟状态序列会耗尽。
        self.assertIs(await bilibili_auth.poll_qr_login(challenge.session), result)
        self.assertEqual(auth.check_state.await_count, 3)

    async def test_expired_qr_and_credential_file(self):
        """验证过期状态固定，以及旧版凭据文件能在离线状态下解析。"""
        login = SimpleNamespace(check_state=AsyncMock(return_value=QrCodeLoginEvents.TIMEOUT))
        session = bilibili_auth.QrLoginSession(login)
        result = await bilibili_auth.poll_qr_login(session)
        self.assertEqual(result.status, bilibili_auth.QrLoginStatus.EXPIRED)
        self.assertIsNone(result.credential)
        self.assertIs(await bilibili_auth.poll_qr_login(session), result)
        login.check_state.assert_awaited_once()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bilibili.env"
            # 凭据值内含等号，验证解析器只把第一个等号当作字段分隔符。
            path.write_text("# credentials\nSESSDATA=test-secret=value\nBILI_JCT=test-token\n", encoding="utf-8")
            credential = bilibili_auth.load_credential_file(path)
        self.assertEqual(credential.sessdata, "test-secret=value")
        self.assertNotIn("test-token", repr(credential))
