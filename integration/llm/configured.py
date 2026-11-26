"""通过项目的全局密钥配置创建文本模型后端。"""

import os
from pathlib import Path

from ..config import load_config_section
from .catalog import ChatModelCatalog, ChatModelInfo
from .contracts import ChatBackend, ChatBackendError, ChatErrorKind


def create_configured_chat_backend(
    *, project_root: str | Path, selection: ChatModelInfo | None = None, probe: bool = False,
) -> ChatBackend:
    """从项目配置创建模型后端，按需先验证模型可以调用。

    密钥由运行环境和项目根目录的 .env 提供，非空环境变量优先。
    明确给定的模型组合优先于默认渠道配置。

    :param project_root: 保存全局密钥配置的项目根目录。
    :param selection: 已登记的供应商和模型。为 None 时使用现有默认渠道的模型。
    :param probe: 为 True 时先向所选模型发出一次探测请求。
    :returns: 可供调用方直接使用的模型后端。
    :raises ChatBackendError: 无法读取配置、选定模型、加载依赖或通过探测。
    """
    settings = _read_environment_file(Path(project_root) / ".env")
    selected = _resolve_configured_model(settings, selection)
    key_name = f"{selected.provider.upper()}_API_KEY"
    api_key = os.environ.get(key_name, "").strip() or settings.get(key_name, "")
    if not api_key:
        raise ChatBackendError(
            ChatErrorKind.CONFIGURATION, selected.provider, selected.model,
            detail=f"请在运行环境或项目根目录的 .env 中设置 {key_name}",
        )

    try:
        # 只有调用方创建后端时才加载供应商 SDK，模型目录仍可独立使用。
        from .client import create_chat_backend, prepare_chat_backend
    except ImportError:
        raise ChatBackendError(
            ChatErrorKind.CONFIGURATION, selected.provider, selected.model,
            detail="请先安装 agent 可选依赖",
        ) from None

    if probe:
        return prepare_chat_backend(api_key=api_key, selection=selected)
    return create_chat_backend(api_key=api_key, provider=selected.provider, model=selected.model)


def _read_environment_file(path: Path) -> dict[str, str]:
    """读取现有全局密钥文件使用的 KEY=VALUE 格式。

    :param path: 项目根目录的 .env 文件路径。
    :returns: 文件中的配置。文件缺失时返回空字典，仍可使用环境变量。
    :raises ChatBackendError: 文件存在但无法读取或解码。
    """
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError):
        raise ChatBackendError(ChatErrorKind.CONFIGURATION, detail="无法读取项目根目录的 .env") from None

    settings = {}
    for line in lines:
        # 只拆分第一个等号，保留密钥值自身可能含有的等号。
        name, separator, value = line.partition("=")
        name = name.strip()
        if separator and name and not name.startswith("#"):
            settings[name] = value.strip()
    return settings


def _resolve_configured_model(settings: dict[str, str], selection: ChatModelInfo | None) -> ChatModelInfo:
    """根据显式选择或默认配置取得已登记的模型组合。

    :param settings: 从全局密钥文件读取的配置项。
    :param selection: 调用方明确选择的模型组合，或者 None。
    :returns: 在模型目录中校验过的供应商与模型。
    :raises ChatBackendError: 公共模型配置无效，或所选组合未登记。
    """
    try:
        config = load_config_section("llm")
        catalog = ChatModelCatalog(config)
        if selection is not None:
            return catalog.resolve(provider=selection.provider, model=selection.model)

        # 独立加工的现有调用允许指定默认渠道，沿用该渠道登记的第一个模型。
        provider = (
            os.environ.get("VALHALLA_LLM_PROVIDER", "").strip()
            or settings.get("VALHALLA_LLM_PROVIDER")
            or config["default_provider"]
        )
        provider = provider.strip().lower()
        return next(item for item in catalog.list_models() if item.provider == provider)
    except (AttributeError, KeyError, OSError, StopIteration, TypeError, ValueError):
        raise ChatBackendError(ChatErrorKind.CONFIGURATION, detail="所选供应商或模型未在模型目录中配置") from None
