"""共享环境配置加载"""
import os
from pathlib import Path


def load_env(filepath: str | Path = ".env") -> dict[str, str]:
    """加载 KEY=VALUE 格式的配置文件，忽略注释和空行"""
    config: dict[str, str] = {}
    if not os.path.exists(filepath):
        return config
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k] = v
    return config
