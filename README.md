# Valhalla

Valhalla 将博主公开发布的内容采集到本地，为后续可追溯的数字人训练和推理准备资料。当前可浏览 B 站投稿和合集、下载音频、生成带时间戳的字幕，以及使用模型纠错和整理字幕。

## 安装

需要 Python 3.12、uv，以及可从 PATH 调用的 FFmpeg。在项目根目录安装采集和加工所需的依赖。

```powershell
uv sync --locked --python 3.12 --extra bilibili --extra transcription --extra llm
uv run --locked python -m ingestion.interaction.cli --help
```

## 快速开始

按采集模块的说明登记博主。B 站登录会话放在 `.sessions/bilibili.json`，模型 API Key 可通过项目根目录的 `.env` 或环境变量提供。 [博主登记与 CLI 用法](ingestion/README.md) · [会话与模型配置](integration/README.md)

```powershell
uv run --locked python -m ingestion.interaction.cli avatar list
uv run --locked python -m ingestion.interaction.cli material list-remote --avatar-id 1 --platform bilibili --page 1
uv run --locked python -m ingestion.interaction.cli material list-local --avatar-id 1
```

从远端列表选择 BV 号，将其传给 `material collect` 或 `material collect-and-process`。随后用命令输出的本地资料 ID 调用 `material show --material-id <ID>`。原始 SRT、加工 JSON 和资料索引保存在 `data/ingestion/`。运行日志保存在 `logs/ingestion/`。 [采集与加工示例](ingestion/README.md) · [日志排查](core/README.md)

## 项目文档

- [公共运行基础](core/README.md)
- [通用能力接入](integration/README.md)
- [数据采集](ingestion/README.md)
- [架构与开发入口](CLAUDE.md)
