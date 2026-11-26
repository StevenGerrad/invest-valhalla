"""从集中配置读取已登记的文本模型及其供应商。"""

from dataclasses import dataclass

from ..config import load_config_section


@dataclass(frozen=True)
class ChatModelInfo:
    """描述可交给模型接入层调用的一组供应商和模型标识。"""

    #: 集中配置中的供应商标识，例如 deepseek。
    provider: str
    #: 该供应商接收的模型标识，例如 deepseek-flash。
    model: str


_DEFAULT_CHAT_MODEL = ChatModelInfo(provider="deepseek", model="deepseek-flash")


class ChatModelCatalog:
    """管理一次读取的模型目录，供调用方查询和解析模型选择。"""

    def __init__(self, config: dict | None = None) -> None:
        """加载配置中的供应商和模型组合。

        :param config: 可选的 llm 配置节。为 None 时读取包内集中配置。
        :raises ValueError: 模型目录无法读取或格式无效。
        """
        try:
            config = load_config_section("llm") if config is None else config
        except (KeyError, OSError) as error:
            raise ValueError("无法读取文本模型目录配置") from error
        self._models = _registered_chat_models(config)

    def list_models(self) -> tuple[ChatModelInfo, ...]:
        """列出当前目录中登记的模型组合，无需密钥或网络请求。

        :returns: 按声明顺序排列的模型组合。
        """
        return self._models

    def resolve(self, *, provider: str | None = None, model: str | None = None) -> ChatModelInfo:
        """从目录解析唯一的供应商和模型组合。

        两项都省略时选择 DeepSeek Flash。只传一项时，该项须匹配唯一的组合。

        :param provider: 可选的供应商标识。
        :param model: 可选的模型标识。
        :returns: 唯一匹配的已登记组合。
        :raises ValueError: 未匹配到组合，或匹配到多个组合。
        """
        if provider is None and model is None:
            provider, model = _DEFAULT_CHAT_MODEL.provider, _DEFAULT_CHAT_MODEL.model
        matches = [
            item for item in self._models
            if (provider is None or item.provider == provider) and (model is None or item.model == model)
        ]
        if not matches:
            raise ValueError("所选供应商与模型未在目录中登记")
        if len(matches) > 1:
            raise ValueError("选择匹配多个模型组合，请同时指定供应商和模型")
        return matches[0]


def list_chat_models() -> tuple[ChatModelInfo, ...]:
    """列出项目登记的供应商和模型组合。

    此目录表示已经接入的模型。查询只读取本地配置，账号权限和模型服务状态由实际调用确认。

    :returns: 按配置声明顺序排列的模型组合。
    :raises ValueError: 模型目录无法读取或格式无效。
    """
    return ChatModelCatalog().list_models()


def resolve_chat_model(*, provider: str | None = None, model: str | None = None) -> ChatModelInfo:
    """从模型目录解析一组供应商和模型标识。

    两个参数都省略时使用 DeepSeek Flash。只传一个参数时，该参数须匹配唯一的组合。

    :param provider: 可选的供应商标识。
    :param model: 可选的模型标识。
    :returns: 已在目录登记的完整模型组合。
    :raises ValueError: 目录无效、找不到组合，或输入匹配了多个组合。
    """
    return ChatModelCatalog().resolve(provider=provider, model=model)


def _registered_chat_models(config: dict) -> tuple[ChatModelInfo, ...]:
    """从同一份供应商配置提取模型组合，供目录和客户端共用。

    :param config: 已读入的 llm 配置节。
    :returns: 按供应商和模型的配置顺序排列的组合。
    :raises ValueError: 供应商表、模型列表或标识无效。
    """
    providers = config.get("providers") if isinstance(config, dict) else None
    if not isinstance(providers, dict) or not providers:
        raise ValueError("文本模型目录缺少供应商配置")

    registered = []
    for provider, settings in providers.items():
        if not isinstance(provider, str) or not provider or provider != provider.strip() or not isinstance(settings, dict):
            raise ValueError("文本模型目录中的供应商配置无效")
        # 兼容原有单模型配置。新配置使用列表声明同一供应商注册的多个模型。
        models = settings["models"] if "models" in settings else [settings.get("model")]
        if not isinstance(models, list) or not models or any(
            not isinstance(model, str) or not model or model != model.strip() for model in models
        ):
            raise ValueError("供应商的模型列表须包含有效的模型标识")
        if len(set(models)) != len(models):
            raise ValueError("同一个供应商重复登记了同一模型")
        registered.extend(ChatModelInfo(provider, model) for model in models)
    return tuple(registered)
