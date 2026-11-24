"""启动采集模块的命令行入口。"""

from .bootstrap import run_cli


if __name__ == "__main__":
    raise SystemExit(run_cli())
