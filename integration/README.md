# 通用能力接入

从 Python 调用 B 站内容拉取、音频转换、语音转录、SRT 导出、网页正文提取和文本模型。调用方负责把这些操作组织成采集或推理流程。

## 安装

在项目根目录使用 Python 3.12 和 uv，按需安装对应能力。需要组合使用时，在同一条 `uv sync` 命令中为每组依赖添加一个 `--extra`。

| 能力 | 安装方式 |
|---|---|
| B 站拉取和扫码登录 | `uv sync --locked --extra bilibili` |
| Whisper 转录和可选的繁简转换 | `uv sync --locked --extra transcription` |
| DeepSeek 或 TokenHub 文本模型 | `uv sync --locked --extra llm` |
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

也可以用 `list_collection_videos` 读取合集，用 `get_video` 读取含作者 MID 的详情，或用 `download_audio(bvid, destination)` 下载音频。扫码登录由调用方展示 `start_qr_login` 返回的二维码，并用 `poll_qr_login` 查询状态。

登录后，由开发者或编码工具将会话写到项目根目录的 `.sessions/bilibili.json`。`BilibiliFetcher(session_dir=Path(".sessions"))` 会读取这个文件。旧版凭据文件仍可通过 `load_credential_file` 显式读取并传入客户端。

```json
{
  "saved_at": "2026-11-24T12:00:00+08:00",
  "credential": {"sessdata": "<会话值>"}
}
```

`credential` 可同时包含扫码结果中的 `bili_jct`、`buvid3`、`buvid4`、`dedeuserid` 和 `ac_time_value`。平台提供可信过期时间时，加上带时区的 `expires_at`。更新时先写同目录临时文件，再替换会话文件。会话缺失时接入层尝试公开接口，登录失效后重新扫码。

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

`ChatModelCatalog` 提供模型目录。可通过 `list_chat_models()` 查询已登记的供应商和模型组合，无需 API Key 或模型 SDK。实际调用时由供应商校验凭据和访问权限。

项目内的调用方可以直接使用 `create_configured_chat_backend(project_root=..., selection=...)`。通用能力接入从项目根目录的 `.env` 取得相应渠道的 API Key，运行环境中的非空同名变量优先。传入 `probe=True` 时会先发出一次探测请求。

```python
import os

from integration.llm import create_chat_backend, list_chat_models, resolve_chat_model

for item in list_chat_models():
    print(item.provider, item.model)

selection = resolve_chat_model(provider="deepseek", model="deepseek-flash")
backend = create_chat_backend(
    provider=selection.provider,
    model=selection.model,
    api_key=os.environ["DEEPSEEK_API_KEY"],
)
answer = backend.chat("你是一个简洁的助手。", "请用一句话总结这段资料。")
print(answer)
```

切换到 TokenHub 时，选择 `tokenhub` 与 `hy4-flash`，并传入 `TOKENHUB_API_KEY`。渠道与模型组合由 `config.toml` 的 `llm.providers` 配置，每个渠道的 `models` 可登记多条。流式调用使用 `chat_stream`，收到 `done` 表示正文完整。调用失败可捕获 `ChatBackendError` 并读取 `kind`。

`prepare_chat_backend(api_key=..., selection=...)` 会发出一次短提示请求，通过后返回同一个后端供正式调用。采集后加工在实际需要处理字幕时才发起探测，探测请求不发送字幕内容。

默认分页、下载超时、模型渠道和转换参数统一在 [config.toml](config.toml) 中维护。需要自行管理密钥的调用方可使用示例中的 `create_chat_backend()` 显式传入密钥。项目本地凭据按[开发规范](../docs/development/项目开发规范.md)保管。开发约定和代码索引见 [CLAUDE.md](CLAUDE.md)。
