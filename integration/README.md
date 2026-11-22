# 通用能力接入

从 Python 调用 B 站内容拉取、音频转换、语音转录、SRT 导出、网页正文提取和文本模型。调用方负责把这些操作组织成采集或推理流程。

## 安装

在项目根目录使用 Python 3.12 和 uv，按需安装对应能力。需要组合使用时，在同一条 `uv sync` 命令中为每组依赖添加一个 `--extra`。

| 能力 | 安装方式 |
|---|---|
| B 站拉取和扫码登录 | `uv sync --locked --extra bilibili` |
| Whisper 转录和可选的繁简转换 | `uv sync --locked --extra transcription` |
| DeepSeek 或 TokenHub 文本模型 | `uv sync --locked --extra agent` |
| 网页正文提取和 SRT 导出 | 使用 Python 标准库。 |
| 音频提取 | 安装 FFmpeg，并确保 `ffmpeg` 可从 PATH 调用，或显式配置其路径。 |

## B 站内容拉取

```python
import asyncio

from integration.fetcher.bilibili import BilibiliFetcher


async def main():
    fetcher = BilibiliFetcher()
    page = await fetcher.list_creator_videos(322005137, page_size=5)
    for item in page.items:
        print(item.bvid, item.title, item.source_url)


asyncio.run(main())
```

也可以用 `list_collection_videos` 读取合集，用 `get_video` 读取详情，或用 `download_audio(bvid, destination)` 下载音频。需要登录时，使用 `load_credential_file` 读取已有凭据并传给 `BilibiliFetcher`。扫码登录由调用方展示 `start_qr_login` 返回的二维码，并用 `poll_qr_login` 查询状态。

## 内容转换

```python
from pathlib import Path

from integration.converter import WhisperTranscriber, extract_audio, render_srt

wav_path = extract_audio("example.m4s", "example.wav")
segments = WhisperTranscriber().transcribe(wav_path, language="zh", simplify_chinese=True)
Path("example.srt").write_text(render_srt(segments), encoding="utf-8")
```

`extract_web_text(html)` 接收已经取得的 HTML 字符串，返回带源行列位置的段落。

## 文本模型

当前分支的 [模型包入口](llm/__init__.py) 会在导入时抛出 `TypeError`。下面是入口修复后的调用方式。

```python
import os

from integration.llm import create_chat_backend

backend = create_chat_backend(provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"])
answer = backend.chat("你是一个简洁的助手。", "请用一句话总结这段资料。")
print(answer)
```

切换到 TokenHub 时，使用 `provider="tokenhub"` 并传入 `TOKENHUB_API_KEY`。流式调用使用 `chat_stream`，收到 `done` 表示正文完整。调用失败可捕获 `ChatBackendError` 并读取 `kind`。

默认分页、下载超时、模型渠道和转换参数统一在 [config.toml](config.toml) 中维护。密钥由调用方注入，项目本地凭据按[开发规范](../docs/spec/项目开发规范.md)保管。开发约定和代码索引见 [CLAUDE.md](CLAUDE.md)。
