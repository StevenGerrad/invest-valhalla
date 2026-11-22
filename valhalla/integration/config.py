"""加载通用能力接入模块的集中配置。"""

import tomllib
from importlib.resources import files
from pathlib import Path


def load_config_section(name: str, override: str | Path | None = None) -> dict:
    """读取指定配置节，并按需合并本地覆盖项。

    :param name: 统一 TOML 文件中的节名，如 bilibili。
    :param override: 本地覆盖文件路径。为 None 时使用包内默认配置。
    :returns: 合并后的该节配置字典。
    :raises KeyError: 包内默认配置缺少指定节。
    """
    # 通过包资源定位默认文件，保证从任意工作目录启动都能读取同一份默认配置。
    config_file = files(__package__).joinpath("config.toml")
    defaults = tomllib.loads(config_file.read_text(encoding="utf-8"))
    if override is None:
        return defaults[name]
    with Path(override).open("rb") as file:
        overrides = tomllib.load(file)
    # 只合并同名节，避免其他能力的配置进入当前适配器。未覆盖的键沿用默认值。
    return defaults[name] | overrides.get(name, {})
