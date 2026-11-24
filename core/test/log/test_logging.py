"""验证公共日志的级别分流、保留、运行标识和进程隔离。"""

import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core import configure_logging, log_run


class LoggingTest(TestCase):
    """通过独立命名空间和临时目录验证文件日志。"""

    def test_levels_and_nested_configuration(self) -> None:
        """验证重复配置只写一次，访问日志单独分流，退出后恢复调用方状态。"""
        with TemporaryDirectory() as directory:
            log_dir = Path(directory) / "logs"
            logger = logging.getLogger("core_test.app")
            access = logging.getLogger("core_test.app.access")
            original_state = (list(logger.handlers), logger.level, logger.propagate)
            with configure_logging(log_dir, logger_name=logger.name, access_logger_name=access.name):
                self.assertFalse(log_dir.exists())
                with configure_logging(log_dir, logger_name=logger.name), log_run() as run_id:
                    logger.debug("filtered")
                    logger.info("app-event")
                    logger.warning("warning-event")
                    access.info("access-event")
                logger.info("outer-event")

            app = _read_category(log_dir, "app")
            errors = _read_category(log_dir, "error")
            requests = _read_category(log_dir, "access")
            self.assertEqual(app.count("app-event"), 1)
            self.assertNotIn("filtered", app)
            self.assertIn("outer-event", app)
            self.assertIn("warning-event", app)
            self.assertIn("warning-event", errors)
            self.assertIn("access-event", requests)
            self.assertNotIn("access-event", app)
            self.assertNotIn("app-event", errors)
            self.assertIn(f"pid={os.getpid()} run_id={run_id}", errors)
            self.assertEqual((logger.handlers, logger.level, logger.propagate), original_state)

    def test_rotation_retention_and_override(self) -> None:
        """注入不同 UTC 日期的记录，验证切换文件与按保留期限清理。"""
        with TemporaryDirectory() as directory:
            log_dir = Path(directory)
            config = log_dir / "override.toml"
            config.write_text('[logging]\nlevel = "DEBUG"\napp_retention_days = 2\n', encoding="utf-8")
            logger = logging.getLogger("core_test.rotation")
            with configure_logging(log_dir, logger_name=logger.name, config_path=config):
                for day in (1, 2, 4):
                    record = logger.makeRecord(logger.name, logging.DEBUG, __file__, 1, f"day-{day}", (), None)
                    record.created = datetime(2030, 1, day, 0, 1, tzinfo=UTC).timestamp()
                    logger.handle(record)
            remaining = list(log_dir.glob("app-*.log"))
            self.assertEqual([item.name for item in remaining], [f"app-2030-01-04-{os.getpid()}.log"])
            self.assertIn("2030-01-04T00:01:00Z DEBUG", remaining[0].read_text(encoding="utf-8"))

    def test_processes_write_separate_files(self) -> None:
        """启动两个独立进程，确认同一目录下的应用日志不会竞争同一文件。"""
        script = """
import logging
import os
import sys
from core import configure_logging

with configure_logging(sys.argv[1], logger_name="worker"):
    logging.getLogger("worker").info("child")
print(os.getpid())
"""
        repo = Path(__file__).resolve().parents[3]
        with TemporaryDirectory() as directory:
            command = [sys.executable, "-c", script, directory]
            with (
                subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, text=True) as first,
                subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, text=True) as second,
            ):
                first_pid, _ = first.communicate(timeout=10)
                second_pid, _ = second.communicate(timeout=10)
                self.assertEqual(first.returncode, 0)
                self.assertEqual(second.returncode, 0)
            # Windows 的虚拟环境启动器可能另起 Python 进程，使用写入方实际报告的 PID。
            paths = list(Path(directory).glob("app-*.log"))
            self.assertEqual(len(paths), 2)
            self.assertEqual({int(path.stem.rsplit("-", 1)[1]) for path in paths}, {int(first_pid), int(second_pid)})
            self.assertTrue(all("child" in path.read_text(encoding="utf-8") for path in paths))


def _read_category(root: Path, category: str) -> str:
    """读取某一类别在测试中写入的日志。

    :param root: 测试日志目录。
    :param category: 日志类别。
    :returns: 该类别的日志文本。
    """
    return "\n".join(path.read_text(encoding="utf-8") for path in root.glob(f"{category}-*.log"))
