# 公共运行基础

日志使用 Python 标准库。应用入口使用 `configure_logging()` 配置自己的 logger，任务使用 `log_run()` 绑定运行 ID。各层通过 `logging.getLogger(__name__)` 记录事件。

新采集 CLI 将日志写到项目根目录的 `logs/ingestion/`。日志行包含 UTC 时间、级别、进程 ID、运行 ID、模块和事件。按 `run_id` 可查到一次命令的开始、服务阶段、批量结果、仓储异常和退出状态。

| 文件 | 记录内容 | 默认保留 |
|---|---|---|
| `app-YYYY-MM-DD-<pid>.log` | 应用事件，默认 `INFO` 及以上。 | 14 天 |
| `error-YYYY-MM-DD-<pid>.log` | `WARNING` 及以上事件。符合应用级别的事件也会写入应用日志。 | 90 天 |
| `access-YYYY-MM-DD-<pid>.log` | 应用入口启用独立访问 logger 后记录的访问事件。 | 30 天 |

每类日志在当天第一次写入时打开新文件，并清理该类超过保留期限的历史文件。文件名包含进程 ID，便于并行 CLI 进程分别写入。

日常排查从应用和异常日志查找对应的 `run_id`。需要查看文件锁等待、资料查询和索引提交时，将 [config.toml](config.toml) 的 `[logging].level` 设为 `DEBUG` 后重跑命令。日志用业务 ID 和错误类别定位问题，凭据、签名地址、字幕正文和模型输入输出都应留在各自的数据边界内。
