"""共享日志配置：应用日志 → logs/valhalla.log（项目根目录）"""
import logging
from pathlib import Path

FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup(mid: int = 0, level: int = logging.INFO):
    """配置应用日志，输出到日志文件，终端完全不受影响"""
    from logging.handlers import RotatingFileHandler
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "valhalla.log"

    handler = RotatingFileHandler(
        str(log_file), maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATE_FMT))
    logging.basicConfig(level=level, handlers=[handler], force=True)

    # 屏蔽第三方库日志噪音，不输出到任何地方
    for noisy in ("jieba", "httpx", "huggingface_hub", "sentence_transformers",
                  "openai", "faiss", "milvus_lite.engine", "urllib3", "tqdm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # 抑制 jieba 的 pkg_resources 警告
    import warnings
    warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
