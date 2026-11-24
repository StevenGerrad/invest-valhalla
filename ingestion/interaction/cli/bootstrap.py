"""装配新采集 CLI 所需的仓储和通用能力。"""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from core import configure_logging, log_run
from integration.config import load_config_section
from integration.converter import SubtitleSegment, WhisperTranscriber, extract_audio
from valhalla.core.env import load_env

from ...pipeline.avatar.impl.avatar_service_impl import AvatarServiceImpl
from ...pipeline.error import IngestionError
from ...pipeline.material.impl.bilibili_subtitle.bilibili_subtitle_material_service_impl import (
    BilibiliSubtitleMaterialServiceImpl,
)
from ...pipeline.material_process.impl.subtitle.subtitle_material_process_service_impl import (
    SubtitleMaterialProcessServiceImpl,
)
from ...storage.impl.local_file.avatar_repository_impl import AvatarRepositoryImpl
from ...storage.impl.local_file.material_repository_impl import MaterialRepositoryImpl
from .command import main

if TYPE_CHECKING:
    from integration.fetcher.bilibili import BilibiliContentSource
    from integration.llm import ChatBackend


def run_cli(argv: Sequence[str] | None = None, *, project_root: str | Path | None = None) -> int:
    """用独立的本地存储运行新采集命令。

    :param argv: 命令参数。为 None 时使用当前进程参数。
    :param project_root: 指定数据和会话的项目目录。省略时从当前工作目录定位。
    :returns: 命令解析及服务操作的退出码。
    """
    root = Path(project_root).resolve() if project_root is not None else _project_root(Path.cwd())
    data_dir = root / "data" / "ingestion"
    avatars, materials = AvatarRepositoryImpl(data_dir), MaterialRepositoryImpl(data_dir)

    @cache
    def source() -> BilibiliContentSource:
        """首次访问远端时加载 B 站依赖和本地会话。

        :returns: 当前 CLI 调用共用的 B 站内容能力。
        :raises IngestionError: B 站可选依赖未安装。
        """
        try:
            from integration.fetcher.bilibili import BilibiliFetcher
        except ImportError:
            raise IngestionError("请先安装 bilibili 可选依赖") from None
        return BilibiliFetcher(session_dir=root / ".sessions")

    @cache
    def transcriber() -> WhisperTranscriber:
        """在首次实际转录时初始化转录能力，供同一批资料复用。

        :returns: 共用的 Whisper 转录器。
        """
        return WhisperTranscriber()

    def transcribe(path: Path) -> tuple[SubtitleSegment, ...]:
        """把采集到的 WAV 转为带时间的原始字幕。

        :param path: 待转录的本地 WAV 文件。
        :returns: 使用简体中文归一化的原始片段。
        """
        return transcriber().transcribe(path, simplify_chinese=True)

    @cache
    def backend() -> ChatBackend:
        """首次确实需要加工时加载配置和模型能力。

        :returns: 当前 CLI 调用共用的文本模型。
        :raises IngestionError: 模型依赖缺失，或未配置可用的 API Key。
        """
        return _chat_backend(root)

    logging_config = root / "core" / "config.toml"
    with configure_logging(
        root / "logs" / "ingestion",
        logger_name="ingestion",
        config_path=logging_config if logging_config.is_file() else None,
    ), log_run():
        return main(
            argv, avatar_service=AvatarServiceImpl(avatars, materials),
            material_service=BilibiliSubtitleMaterialServiceImpl(avatars, materials, source, extract_audio, transcribe),
            material_process_service=SubtitleMaterialProcessServiceImpl(materials, backend),
        )


def _project_root(current: Path) -> Path:
    """从工作目录向上定位源代码项目，为安装后运行保留当前目录默认值。

    :param current: 启动命令时的目录。
    :returns: 源代码项目根目录，或作为运行目录的 current。
    """
    for directory in (current, *current.parents):
        if (
            (directory / "pyproject.toml").is_file()
            and (directory / "ingestion").is_dir()
            and (directory / "integration").is_dir()
        ):
            return directory
    return current


def _chat_backend(root: Path) -> ChatBackend:
    """从调用环境或根目录的长期配置选择模型渠道和密钥。

    :param root: 项目根目录。
    :returns: 配置选定渠道的模型能力。
    :raises IngestionError: 无法加载凭据或模型能力。
    """
    try:
        from integration.llm import create_chat_backend
    except ImportError:
        raise IngestionError("请先安装 agent 可选依赖") from None
    model_config = load_config_section("llm")
    try:
        settings = load_env(root / ".env")
    except (OSError, ValueError):
        raise IngestionError("无法读取项目根目录的 .env") from None
    # 运行环境的显式值优先，模型渠道及参数仍由 integration 的共享配置定义。
    provider = (
        os.environ.get("VALHALLA_LLM_PROVIDER") or settings.get("VALHALLA_LLM_PROVIDER")
        or model_config["default_provider"]
    ).strip().lower()
    if provider not in model_config["providers"]:
        raise IngestionError("VALHALLA_LLM_PROVIDER 指定的模型渠道未配置")
    key_name = f"{provider.upper()}_API_KEY"
    key = os.environ.get(key_name) or settings.get(key_name)
    if not key:
        raise IngestionError(f"请在运行环境或 .env 中设置 {key_name}")
    try:
        return create_chat_backend(api_key=key, provider=provider)
    except ValueError:
        raise IngestionError("无法初始化文本模型，请检查模型渠道配置") from None
