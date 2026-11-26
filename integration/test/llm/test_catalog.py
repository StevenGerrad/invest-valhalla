"""验证模型目录与模型组合类型能够脱离供应商 SDK 使用。"""

import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from integration.llm import ChatModelCatalog, ChatModelInfo, list_chat_models, resolve_chat_model


class ChatModelCatalogTests(TestCase):
    """使用包内配置和模拟目录验证模型选择。"""

    def test_lists_configured_models_and_resolves_default(self) -> None:
        """确认项目当前的模型组合、默认值和单条件匹配。"""
        deepseek = ChatModelInfo("deepseek", "deepseek-flash")
        tokenhub = ChatModelInfo("tokenhub", "hy4-flash")
        self.assertEqual(list_chat_models(), (deepseek, tokenhub))
        self.assertEqual(resolve_chat_model(), deepseek)
        self.assertEqual(resolve_chat_model(provider="tokenhub"), tokenhub)
        self.assertEqual(resolve_chat_model(model="hy4-flash"), tokenhub)
        with self.assertRaisesRegex(ValueError, "未在目录中登记"):
            resolve_chat_model(provider="deepseek", model="hy4-flash")

    def test_multiple_models_require_unambiguous_selection(self) -> None:
        """同一供应商可登记多个模型，同名模型可由不同供应商提供。"""
        catalog = ChatModelCatalog({
            "providers": {
                "first": {"models": ["shared", "other"]},
                "second": {"model": "shared"},
            },
        })
        self.assertEqual(len(catalog.list_models()), 3)
        with self.assertRaisesRegex(ValueError, "请同时指定"):
            catalog.resolve(provider="first")
        with self.assertRaisesRegex(ValueError, "请同时指定"):
            catalog.resolve(model="shared")
        self.assertEqual(catalog.resolve(provider="second", model="shared"), ChatModelInfo("second", "shared"))

    def test_rejects_duplicate_model_for_same_provider(self) -> None:
        """拒绝在同一供应商下重复登记同名模型。"""
        with self.assertRaisesRegex(ValueError, "重复登记"):
            ChatModelCatalog({"providers": {"first": {"models": ["shared", "shared"]}}})

    def test_catalog_and_ingestion_import_without_sdk(self) -> None:
        """确认没有可选依赖时仍可查询目录，并交给两种采集 DTO。"""
        project_root = Path(__file__).resolve().parents[3]
        script = (
            "from integration.llm import ChatModelInfo, list_chat_models; "
            "from ingestion.service import CollectAndProcessMaterialParam, BatchCollectAndProcessMaterialParam; "
            "selection = list_chat_models()[0]; "
            "assert isinstance(selection, ChatModelInfo); "
            "assert CollectAndProcessMaterialParam('bv', model_selection=selection).model_selection is selection; "
            "assert BatchCollectAndProcessMaterialParam(('bv',), model_selection=selection).model_selection is selection"
        )
        subprocess.run([sys.executable, "-S", "-c", script], cwd=project_root, check=True, timeout=15)
