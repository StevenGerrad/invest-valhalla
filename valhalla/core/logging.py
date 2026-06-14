"""共享日志配置：access → app → error 三层，按天轮转

  logs/app-YYYY-MM-DD.log      INFO+,  保留 14 天
  logs/error-YYYY-MM-DD.log    WARNING+, 保留 90 天
  logs/access-YYYY-MM-DD.log   请求级,  保留 30 天
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── 按天轮转 handler (自定义实现, 文件名自描述) ────

class DailyRotatingHandler(logging.Handler):
    """每天午夜自动切新文件，文件名格式: {prefix}-YYYY-MM-DD.log"""

    def __init__(self, prefix: str, backup_days: int = 14, encoding: str = "utf-8",
                 fmt: str | None = None):
        super().__init__()
        self._prefix = prefix
        self._backup_days = backup_days
        self._encoding = encoding
        self._current_date: str | None = None
        self._file = None
        if fmt:
            self.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    def _path(self, date_str: str) -> Path:
        return LOG_DIR / f"{self._prefix}-{date_str}.log"

    def _open(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today == self._current_date and self._file:
            return
        if self._file:
            self._file.close()
        self._current_date = today
        self._file = open(self._path(today), "a", encoding=self._encoding)

    def emit(self, record: logging.LogRecord):
        self._open()
        self._cleanup()
        msg = self.format(record)
        if self._file:
            self._file.write(msg + "\n")
            self._file.flush()

    def _cleanup(self):
        """删除超过保留天数的旧文件"""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._backup_days)
        for f in sorted(LOG_DIR.glob(f"{self._prefix}-*.log")):
            try:
                date_str = f.stem.split("-", 1)[1]
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    f.unlink()
            except (ValueError, IndexError):
                pass

    def close(self):
        if self._file:
            self._file.close()
        super().close()


# ── 公共 API ──────────────────────────────────────

def setup(level: int = logging.INFO):
    """配置三层日志，终端不受影响"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    std_fmt = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"

    # 1. app handler
    app_h = DailyRotatingHandler("app", backup_days=14, fmt=std_fmt)
    app_h.setLevel(logging.INFO)
    root.addHandler(app_h)

    # 2. error handler
    err_h = DailyRotatingHandler("error", backup_days=90, fmt=std_fmt)
    err_h.setLevel(logging.WARNING)
    root.addHandler(err_h)

    # 3. access handler (独立 logger, 不传播)
    acc_h = DailyRotatingHandler("access", backup_days=30, fmt="%(asctime)s %(message)s")
    acc_h.setLevel(logging.INFO)
    acc_logger = logging.getLogger("valhalla.api.access")
    acc_logger.addHandler(acc_h)
    acc_logger.propagate = False

    # 屏蔽第三方库噪音
    for noisy in ("jieba", "httpx", "huggingface_hub", "sentence_transformers",
                  "openai", "faiss", "milvus_lite", "urllib3", "tqdm",
                  "pymilvus", "grpc", "uvicorn"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    import warnings
    warnings.filterwarnings("ignore", message="pkg_resources is deprecated")


def access_logger() -> logging.Logger:
    return logging.getLogger("valhalla.api.access")
