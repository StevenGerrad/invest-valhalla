# CLAUDE.md

> 产品方案: [docs/product.md](docs/product.md) | 技术方案: [docs/architecture.md](docs/architecture.md) | 使用说明: [README.md](README.md)

## 项目概述

B 站 UP 主视频 → 下载音频 → 本地 AI 转录 → SRT 字幕 + JSON 索引。

## 环境

- Python 3.12.10 `.venv/`，FFmpeg 8.1.1 (winget)
- 详见 [requirements.txt](requirements.txt)

### 运行时暗坑

```
# pip 必须绕过 Windows 系统代理
no_proxy="*" pip install xxx

# HuggingFace 国内需镜像
HF_ENDPOINT=https://hf-mirror.com python ...

# B 站 API 匿名请求频繁触发 412 → 用登录态
```

## 命令速查

```bash
# 登录 (仅一次)
python -m bilibili_subtitle.cli --login

# UP 主全量
python -m bilibili_subtitle.cli --mid 322005137 --pages 3 --skip-existing

# 系列/合集
python -m bilibili_subtitle.cli --mid 322005137 --series 5488551

# 查询
python -m bilibili_subtitle.cli --mid 322005137 --list
python -m bilibili_subtitle.cli --mid 322005137 --stats
python -m bilibili_subtitle.cli --mid 322005137 --search 投资
```

## 编码约定

- `bilibili-api-python` 全部异步，用 `sync()` 包装为同步
- B 站请求间隔 >= 3s，遇到 412 等待 30s 重试
- 凭证文件 `.env` 不入 git
- FFmpeg 路径自动探测 (winget 路径优先，fallback PATH)
- 转录默认 `small` 模型，`base` 精度不够不推荐
- 中间音频文件默认删除，`--keep-audio` 保留
- 字段需归一化：空间 API 返回 `length`/`created`/`play`，系列 API 返回 `duration`/`ctime`/`stat.view`

## 代码结构

```
bilibili_subtitle/
├── __init__.py         # 版本 0.1.0
├── bilibili.py         # BiliClient: 视频列表 + 系列 + DASH
├── downloader.py       # httpx 下载 + FFmpeg
├── transcriber.py      # faster-whisper + OpenCC
├── indexer.py          # IndexManager: JSON 索引
└── cli.py              # argparse CLI
```

## 已知问题

- `iter_all_videos` 在系列模式下 `ChannelSeriesType.SEASON` 的 `get_meta()` 返回 total=0，实际从 `get_channel_videos_season` 获取
- Windows 终端 GBK 编码输不出中文表情，脚本需 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`
- `--limit` 不计算跳过的视频，仅计算实际处理的
