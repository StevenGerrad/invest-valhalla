# 技术方案

## 架构总览

```
bilibili-api-python + 登录态 → DASH 音频流 .m4s → FFmpeg → faster-whisper → OpenCC → .srt + index.json
```

## 数据流

```
CLI (cli.py)
  ├── BiliClient (bilibili.py)
  │     ├── 视频列表: user.get_videos() / ChannelSeries.get_videos()
  │     └── DASH 流: video.get_download_url() → 音频 .m4s URL
  ├── Downloader (downloader.py)
  │     ├── httpx 流式下载 .m4s
  │     └── FFmpeg 转 16kHz mono s16 .wav
  ├── Transcriber (transcriber.py)
  │     ├── faster-whisper (CTranslate2) — 本地离线推理
  │     └── OpenCC (t2s) — 繁体→简体后处理
  └── IndexManager (indexer.py)
        └── output/{mid}/index.json — 增量写入
```

## 技术选型

### B 站 API 层：bilibili-api-python (v17.4.1)

**为什么选它：**
- 内置 WBI 签名、自动 buvid 生成、登录管理
- 覆盖视频列表 (`user.get_videos`) 和 DASH 流 (`video.get_download_url`)
- B 站 DASH 天然音画分离，直接取音频流 URL 下载 `.m4s`，不需要 yt-dlp

**备选方案：** 手搓 requests + WBI 签名。更轻量，但需要自己维护签名算法（B 站偶尔变更）和风控绕过。

### 音频下载：httpx + FFmpeg

**为什么不用 yt-dlp：**
- yt-dlp 先下完整视频再抽音频，浪费带宽
- DASH 音频流 URL 可直接下载，不需要 subprocess 调用外部工具
- FFmpeg 是必须依赖（.m4s → .wav），不必再引入 yt-dlp

### 语音转写：faster-whisper (v1.2.1)

**为什么不选其他方案：**

| 方案 | 速度 (CPU) | 精度 | 依赖 | 结论 |
|------|-----------|------|------|------|
| openai-whisper | 1x | 基线 | PyTorch ~2GB | 太慢太重 |
| faster-whisper | 4x | 同 | CTranslate2 ~50MB | **选用** |
| SenseVoice | 7x | 中文更好 | 自有模型 | 备选，生态不成熟 |
| Whisper API | 即时 | 最优 | 网络+付费 | 备选，有隐私顾虑 |

**模型选择（实测）：**
- `small` (244M): 10x 实时率，质量可用，推荐日常使用
- `medium` (769M): 4x 实时率，质量更好，适合重要内容
- `base` (74M): 太快但精度不足，不推荐

### 繁简转换：OpenCC

Whisper 训练数据繁简混合，即使加了 `initial_prompt="以下是普通话的句子。"`，仍有部分繁体输出。OpenCC `t2s` 作为后处理兜底。

## 模块设计

```
bilibili_subtitle/
├── __init__.py        # 版本号
├── bilibili.py        # BiliClient: 视频列表/系列/DASH流
├── downloader.py      # download_audio / convert_to_wav
├── transcriber.py     # Transcriber: whisper + OpenCC
├── indexer.py         # IndexManager: JSON 索引读写
└── cli.py             # argparse 入口 + 流程编排
```

## 存储估算 (1389 个视频)

| 保留方案 | 大小 |
|---------|------|
| 文本 + 向量库 | 0.9 GB |
| + 音频 .m4s | 14.3 GB |
| + 全部 (含 .wav) | 46 GB |

## 关键设计决策

- **同步包装异步**：`bilibili-api-python` 全异步，用 `sync()` 包装避免引入 asyncio 复杂度
- **增量索引**：JSON 文件而非 SQLite — 数据量小（百级），零依赖，人可读
- **中间文件不保留**：默认删 .m4s 和 .wav，仅留 .srt——wav 可随时从 m4s 用 FFmpeg 重建
