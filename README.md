# B站 UP 主视频字幕生成器

爬取 B 站 UP 主视频，下载音频，使用本地 AI 模型自动生成 SRT 字幕。

## 使用 uv 安装

在项目根目录用 uv 创建 Python 3.12 环境。按所需功能选择依赖组合。

```powershell
# 新版 B 站拉取适配器
uv sync --locked --python 3.12 --extra bilibili

# 旧字幕采集、语义处理、RAG 和 Web 入口
uv sync --locked --python 3.12 --all-extras
uv run --locked --all-extras python -m valhalla.cli --help
```

新版 B 站接口位于 `integration.fetcher.bilibili`。用 `BilibiliFetcher` 分页读取投稿或合集、查询视频详情，或按 BV 号下载音频。用 `start_qr_login` 和 `poll_qr_login` 发起扫码登录并读取状态。现有凭据文件可通过 `load_credential_file` 显式读取。

通用能力接入统一使用 `integration/config.toml`。`[bilibili]` 节配置默认分页大小和下载超时。可以通过 `BilibiliConfig.load(path)` 读取一份同结构的模块级覆盖文件，再把配置交给 `BilibiliFetcher`。凭据请通过独立的本地凭据文件或扫码登录传入。

### 大模型接入

安装依赖后，通过 `integration.llm` 调用文本模型。

```powershell
uv sync --locked --python 3.12 --extra agent
```

`integration/config.toml` 的 `[llm]` 节集中管理默认渠道和超时。各渠道的服务地址、模型及扩展请求参数列在 `[llm.providers.*]` 下。以下示例从进程环境读取由调用方设置的 `TOKENHUB_API_KEY`。

```python
import os

from integration.llm import create_chat_backend

backend = create_chat_backend(provider="tokenhub", api_key=os.environ["TOKENHUB_API_KEY"])
print(backend.chat("你是一个简洁的助手。", "请用一句话解释市盈率。"))
```

使用 DeepSeek 时，将渠道改为 `deepseek`，并传入对应的 Key。省略 `provider` 时使用集中配置的默认渠道。流式调用使用 `chat_stream()`，依次消费事件。收到 `done` 表示正文完整。调用失败时可捕获 `ChatBackendError`，通过 `kind` 判断错误类别。

通用能力接入的单元测试集中在 `integration/test/`，子路径与被测源码对应。递归列出测试文件后，将路径交给 `unittest`。

```powershell
$testFiles = Get-ChildItem -Path integration/test -Recurse -File -Filter 'test_*.py' |
    ForEach-Object { Resolve-Path -LiteralPath $_.FullName -Relative }
uv run --locked --extra agent --extra bilibili python -m unittest @testFiles
```

## 快速开始

```bash
# 1. 安装环境
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt    # 国内: set HF_ENDPOINT=https://hf-mirror.com

# 2. 登录 B 站 (仅一次)
python -m valhalla.cli --login

# 3. 生成字幕
python -m valhalla.cli --mid <UP主ID> --pages 5
```

## 使用方式

```bash
# 处理 UP 主最新 60 个视频
python -m valhalla.cli --mid 322005137 --pages 2

# 处理指定系列/合集 (URL 中 lists/ 后的数字)
python -m valhalla.cli --mid 322005137 --series 5488551

# 增量模式 (跳过已有字幕)
python -m valhalla.cli --mid 322005137 --pages 3 --skip-existing

# 查看已有字幕
python -m valhalla.cli --mid 322005137 --list
python -m valhalla.cli --mid 322005137 --stats
python -m valhalla.cli --mid 322005137 --search 投资

# 完整参数
python -m valhalla.cli \
    --mid 322005137 \
    --pages 5 \
    --limit 10 \
    --model medium \
    --skip-existing \
    --keep-audio
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mid` | UP 主用户 ID (必填) | - |
| `--series` | 系列/合集 ID | - |
| `--pages` | 爬取页数 (每页 30 个) | 1 |
| `--limit` | 最多处理视频数 (0=全部) | 0 |
| `--model` | Whisper 模型 (tiny/base/small/medium/large) | small |
| `--output-dir` | 资料根目录 | data |
| `--skip-existing` | 跳过已有字幕 | false |
| `--keep-audio` | 保留下载的音频 | false |
| `--dry-run` | 仅列出视频不处理 | false |
| `--login` | 二维码登录 | - |

## 输出结构

```
data/{mid}/
├── index.json             # 元数据索引
├── srt/
│   └── {bvid}.srt         # 原始字幕
└── processed/
    └── {bvid}.json        # 启用语义处理后生成的纠错结果
```

## 依赖

- Python 3.12+
- FFmpeg (winget: `winget install Gyan.FFmpeg`)
- 详见 [requirements.txt](requirements.txt)
