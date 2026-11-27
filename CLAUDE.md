# Valhalla 开发说明

当前实现由三个一级模块组成。各模块的 README 面向使用者，CLAUDE.md 说明代码职责和测试位置。 [项目使用入口](README.md) · [系统架构划分](docs/spec/系统架构划分.md)

## 代码结构

| 位置 | 职责 |
|---|---|
| `core/` | 公共运行机制。当前提供日志配置、运行 ID 和日志文件管理。 [逐文件说明](core/CLAUDE.md) |
| `integration/` | 封装 B 站、FFmpeg、Whisper 和文本模型接入。 [逐文件说明](integration/CLAUDE.md) |
| `ingestion/` | 负责博主登记、资料采集、字幕加工、查询、本地仓储和 CLI。 [逐文件说明](ingestion/CLAUDE.md) |
| `docs/spec/` | 当前系统架构、模块边界和设计目标。 |
| `docs/development/` | 项目开发规范、代码规范和 Python 约定。 |
| `pyproject.toml` 和 `uv.lock` | 项目元数据、可选依赖和锁定版本。 |
| `data/ingestion/` 和 `logs/ingestion/` | 采集模块运行时的本地资料与日志，由 Git 忽略。 |

CLI 的入口是 `ingestion.interaction.cli`。`ingestion` 通过 `integration` 调用外部能力，通过 Repository 接口读写资料，使用 `core` 记录每次操作。模型和平台配置按所属模块集中维护。 [项目开发规范](docs/development/项目开发规范.md)

## 验证

测试位于各一级模块的 `test/`，目录与被测源码对应。使用 Python 3.12 和锁定依赖运行。

```powershell
uv sync --locked --python 3.12 --extra bilibili --extra transcription --extra llm
$testFiles = @(rg --files core integration ingestion -g 'test_*.py')
uv run --locked python -m unittest @testFiles
```

[项目代码规范](docs/development/项目代码规范.md) · [Python 代码规范](docs/development/Python代码规范.md)
