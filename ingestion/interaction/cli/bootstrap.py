"""装配新采集 CLI 所需的仓储和通用能力。"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from core import configure_logging, log_run
from integration.converter import SubtitleSegment, WhisperTranscriber, extract_audio
from integration.llm import create_configured_chat_backend

from ...service.avatar.impl.avatar_service_impl import AvatarServiceImpl
from ...service.error import IngestionError
from ...service.material.impl.bilibili_subtitle.bilibili_subtitle_material_service_impl import (
    BilibiliSubtitleMaterialServiceImpl,
)
from ...service.material_process.impl.subtitle.subtitle_material_process_service_impl import (
    SubtitleMaterialProcessServiceImpl,
)
from ...storage.impl.local_file.avatar_repository_impl import AvatarRepositoryImpl
from ...storage.impl.local_file.material_repository_impl import MaterialRepositoryImpl
from .command import main

if TYPE_CHECKING:
    from integration.fetcher.bilibili import BilibiliContentSource
    from integration.llm import ChatBackend, ChatModelInfo


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
        """首次确实需要加工时向通用能力接入取得默认模型。

        :returns: 当前 CLI 调用共用的文本模型。
        :raises ChatBackendError: 模型接入未配置或无法初始化。
        """
        return create_configured_chat_backend(project_root=root)

    def selected_backend(selection: ChatModelInfo) -> ChatBackend:
        """向通用能力接入取得已经探测的指定模型。

        :param selection: 本次使用的供应商和模型组合。
        :returns: 已成功探测的模型后端。
        :raises ChatBackendError: 无法初始化或探测所选模型。
        """
        return create_configured_chat_backend(project_root=root, selection=selection, probe=True)

    process_service = SubtitleMaterialProcessServiceImpl(materials, backend, selected_backend=selected_backend)
    material_service = BilibiliSubtitleMaterialServiceImpl(
        avatars, materials, source, extract_audio, transcribe, material_process_service=process_service,
    )
    logging_config = root / "core" / "config.toml"
    with configure_logging(
        root / "logs" / "ingestion",
        logger_name="ingestion",
        config_path=logging_config if logging_config.is_file() else None,
    ), log_run():
        return main(
            argv, avatar_service=AvatarServiceImpl(avatars, materials),
            material_service=material_service,
            material_process_service=process_service,
            material_collect_and_process_service=material_service,
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
