"""验证通用能力接入从项目配置取得密钥并选择已登记的模型。"""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from integration.llm import ChatBackendError, ChatErrorKind, ChatModelInfo, create_configured_chat_backend


class ConfiguredChatBackendTest(TestCase):
    """使用临时密钥文件和模型接入替身验证调用边界。"""

    def test_reads_global_key_file_and_preserves_existing_default(self) -> None:
        """默认渠道的密钥可以来自根目录文件，密钥中的等号会保留。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "# 测试配置\nDEEPSEEK_API_KEY=file=key\n", encoding="utf-8-sig",
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("integration.llm.client.create_chat_backend") as create,
            ):
                backend = create_configured_chat_backend(project_root=root)
        self.assertIs(backend, create.return_value)
        create.assert_called_once_with(api_key="file=key", provider="deepseek", model="deepseek-flash")

    def test_explicit_selection_and_environment_key_take_priority(self) -> None:
        """显式模型使用自己的渠道密钥，运行环境优先于全局密钥文件。"""
        selection = ChatModelInfo("tokenhub", "hy4-flash")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "VALHALLA_LLM_PROVIDER=deepseek\nTOKENHUB_API_KEY=file-key\n", encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"TOKENHUB_API_KEY": "runtime-key"}, clear=True),
                patch("integration.llm.client.prepare_chat_backend") as prepare,
            ):
                backend = create_configured_chat_backend(project_root=root, selection=selection, probe=True)
        self.assertIs(backend, prepare.return_value)
        prepare.assert_called_once_with(api_key="runtime-key", selection=selection)

    def test_environment_key_works_without_global_file(self) -> None:
        """缺少 .env 时仍可使用已有的运行环境配置。"""
        with (
            TemporaryDirectory() as directory,
            patch.dict(os.environ, {"VALHALLA_LLM_PROVIDER": "tokenhub", "TOKENHUB_API_KEY": "env-key"}, clear=True),
            patch("integration.llm.client.create_chat_backend") as create,
        ):
            create_configured_chat_backend(project_root=directory)
        create.assert_called_once_with(api_key="env-key", provider="tokenhub", model="hy4-flash")

    def test_reports_only_missing_variable_name(self) -> None:
        """缺少对应渠道密钥时报告变量名，不带出其他渠道的密钥。"""
        with (
            TemporaryDirectory() as directory,
            patch.dict(os.environ, {"TOKENHUB_API_KEY": "unrelated-key"}, clear=True),
            patch("integration.llm.client.create_chat_backend") as create,
            self.assertRaises(ChatBackendError) as caught,
        ):
            create_configured_chat_backend(project_root=directory)
        self.assertIs(caught.exception.kind, ChatErrorKind.CONFIGURATION)
        self.assertIn("DEEPSEEK_API_KEY", str(caught.exception))
        self.assertNotIn("unrelated-key", str(caught.exception))
        create.assert_not_called()

    def test_reports_missing_model_sdk(self) -> None:
        """模型 SDK 未安装时通过接入错误给出依赖提示。"""
        with (
            TemporaryDirectory() as directory,
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}, clear=True),
            patch.dict(sys.modules, {"integration.llm.client": None}),
            self.assertRaisesRegex(ChatBackendError, "agent 可选依赖"),
        ):
            create_configured_chat_backend(project_root=directory)
