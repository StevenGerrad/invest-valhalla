# 技术方案

> 当前版本: v0.2 (向 v0.3 演进中) | 最后更新: 2026-05-23
>
> 领域模型见 [domain-model.md](domain-model.md)，产品方案见 [product.md](product.md)。

## 系统架构

```
CLI (cli.py)  /  未来 Web UI
│
├── BiliClient (bilibili.py)      bilibili-api-python → B 站 API
│   ├── 视频列表 (user.get_videos / ChannelSeries)
│   └── DASH 音频流 URL (video.get_download_url)
│
├── Downloader (downloader.py)    httpx + FFmpeg
│   ├── 流式下载 .m4s
│   └── 转码 16kHz mono s16 .wav
│
├── Transcriber (transcriber.py)  faster-whisper + OpenCC + hotwords
│   ├── turbo 模型 (809M) 本地离线推理
│   ├── 领域化 initial_prompt + hotwords 增强
│   └── OpenCC t2s 繁→简后处理
│
├── IndexManager (indexer.py)     JSON 文件索引
│   └── output/{mid}/index.json 增量读写 + 统计查询
│
└── (规划中)
    ├── Chunker    SRT → 语义段落切片
    ├── Embeddings bge-small-zh-v1.5 向量化
    ├── Retriever  混合检索 (向量 + BM25 + RRF)
    └── Generator  Ollama / Claude API RAG 问答
```

## 组件设计

### 现有组件

| 模块 | 文件 | 职责 | 对外接口 |
|------|------|------|----------|
| BiliClient | [bilibili.py](../bilibili_subtitle/bilibili.py) | B 站 API 封装：视频列表、系列视频、DASH 音频流 URL | `get_video_list()`, `iter_all_videos()`, `iter_series_videos()`, `get_best_audio_url()` |
| Downloader | [downloader.py](../bilibili_subtitle/downloader.py) | 音频下载 + FFmpeg 转码 | `download_audio()`, `convert_to_wav()` |
| Transcriber | [transcriber.py](../bilibili_subtitle/transcriber.py) | faster-whisper 转录 + OpenCC 繁简转换 + hotwords 增强 | `Transcriber.transcribe()`, `Transcriber.transcribe_to_srt()` |
| IndexManager | [indexer.py](../bilibili_subtitle/indexer.py) | JSON 索引读写 + 统计查询 | `load()`, `save()`, `add()`, `has()`, `list_videos()`, `stats()` |
| CLI | [cli.py](../bilibili_subtitle/cli.py) | argparse 入口 + 流程编排 | `main()` |

### 规划组件

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| Chunker | SRT 段落 → 语义 chunk 切片 | Layer 1 SRT 或 Layer 3 语义文本 | Layer 4 chunks JSONL |
| Embeddings | chunk 文本 → 向量 | chunk.text | 512-dim float32 向量 |
| Retriever | 用户问题 → 相关 chunk 列表 | 查询字符串 | top-k chunk + 相关性分数 |
| Generator | chunk 上下文 + 问题 → 回答 | prompt + context | 带引用来源的回答 |

### 职责边界

- 各组件通过明确的输入/输出契约解耦
- **BiliClient** 不关心下载和转录，**Transcriber** 不关心文本后续用途
- **Chunker** 可独立替换切分策略，**Embeddings** 可独立替换向量模型
- **Retriever** 可独立切换检索算法（纯向量 / 混合 / 纯关键词）

## 技术选型

### 语音转录: faster-whisper 1.2.1

**对比**:

| 方案 | 速度 (CPU) | 精度 | 依赖 | 结论 |
|------|-----------|------|------|------|
| openai-whisper | 1x | 基线 | PyTorch ~2GB | 太慢太重 |
| faster-whisper | 4x | 同 | CTranslate2 ~50MB | **选用** |
| SenseVoice | 7x | 中文更好 | FunASR 自有模型 | 备选，生态不成熟 |
| Whisper API | 即时 | 最优 | 网络+付费 | 备选，有隐私顾虑 |

**当前默认模型**: `turbo` (809M) — large-v3 蒸馏版，medium 的速度换 large 的质量。

**领域增强** (零新依赖):

| 机制 | 位置 | 作用 |
|------|------|------|
| `initial_prompt` | [transcriber.py:9](../bilibili_subtitle/transcriber.py#L9) | 告知模型这是股票投资内容，引导语境 |
| `hotwords` | [transcriber.py:13](../bilibili_subtitle/transcriber.py#L13) | 38 个金融术语，提升专有名词识别率 |

> 设计原则: hotwords 以 `list[str]` 为正模，调用 faster-whisper 前以 `" ".join()` 转为 API 所需格式。数据模型不受外部 API 格式约束。详见 [CLAUDE.md](../CLAUDE.md) 编码约定。

### 音频下载: httpx + FFmpeg

**为什么不选 yt-dlp**: B 站 DASH 音画天然分离，直接下载音频流 URL 即可，不需要先下完整视频再抽音频。FFmpeg 是必须依赖 (.m4s→.wav)，不必再引入 yt-dlp。

**FFmpeg 路径探测**: 优先 winget 安装路径，fallback PATH。

### B 站 API: bilibili-api-python 17.4.1

内置 WBI 签名、自动 buvid 生成、登录管理。全异步接口，用 `sync()` 包装为同步调用。

### 繁简转换: OpenCC

Whisper 训练数据繁简混合，即使加了 `initial_prompt` 引导，仍有部分繁体输出。OpenCC `t2s` 作为后处理兜底。

### 索引存储: JSON 文件

1389 个视频的索引条目约 200KB，JSON 解析毫秒级，零依赖，人可直接读写。超过 5000 视频或需要跨 UP 主查询时再迁移 SQLite。

### 向量化 + 检索 + 生成 (规划中)

| 层 | 选型 | 理由 |
|------|------|------|
| Embedding | `bge-small-zh-v1.5` (95MB, 512-dim) | 中文效果好，轻量本地运行。备选: `bge-large-zh-v1.5` |
| 向量库 | ChromaDB | 嵌入式、零配置、Python 原生、支持元数据过滤。180K chunks 完全胜任 |
| 检索 | 向量 + BM25 + RRF 融合 | 向量覆盖语义泛化，BM25 覆盖术语精确匹配 (PE/ROE 等) |
| 生成 | Ollama Qwen2.5-7B (本地) / Claude API (云端) | 双模式: 默认本地 (隐私免费)，可选云端 (更高质量) |

### 未来候选替换

| 当前 | 替换触发条件 | 候选 |
|------|-------------|------|
| Whisper turbo | 中文准确率不够 | SenseVoice (FunASR) |
| JSON 索引 | 数据量 > 5000 视频或需跨 UP 主查询 | SQLite |
| ChromaDB | chunks > 500K 或查询延迟 > 1s | LanceDB |
| bge-small | 领域术语召回率不足 | bge-large-zh-v1.5 |
| Ollama Qwen | 需要更高质量回答 | Claude API / DeepSeek API |

## 存储估算

基于 1389 个视频，平均 15 分钟/视频：

| 保留方案 | 组成 | 大小 |
|---------|------|------|
| 纯文本 (SRT + 索引) | Layer 1 + 2 | ~300MB |
| + 语义文本 | + Layer 3 | ~320MB |
| + 向量库 | + Layer 4 chunks + ChromaDB | ~1GB |
| + 音频 .m4s | + 下载音频 | ~14GB |
| + 全部 (含 .wav) | + 转码中间文件 | ~46GB |

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 同步包装异步 | `sync()` | bilibili-api-python 全异步，避免引入 asyncio 复杂度 |
| 中间文件不保留 | 默认删 .m4s/.wav | WAV 可从 m4s 用 FFmpeg 重建，只保留 SRT 为最终产物 |
| 索引格式 | JSON | 数据量小，零依赖，人可读 |
| Layer 3 可选 | 可跳过 LLM 整理 | 降低最小可用门槛，渐进式增强 |
| 数据正模与 API 分离 | list/dict 存数据，边界处转换 | 不受外部 API 格式约束，方便配置化和入库 |
| Chunk 格式 | JSONL | 流式读写，一行一条，易增量追加 |

## 演进路线

| 版本 | 内容 | 状态 |
|------|------|------|
| **v0.1** | 视频列表 + DASH 下载 + small 模型转录 + JSON 索引 | ✅ |
| **v0.2** | turbo 默认模型、hotwords 领域增强、`--bvid` 单视频 | ✅ |
| **v0.3** | Layer 3 LLM 语义整理、Layer 4 向量入库、混合检索 | 规划中 |
| **v0.4** | 交互式 RAG 问答 CLI | 规划中 |
| **v1.0** | Web UI、定时增量、知识图谱 | 愿景 |
