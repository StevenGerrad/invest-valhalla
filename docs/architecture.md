# 技术方案

> 当前版本: v0.4 (RAG + Agent + 测评) | 最后更新: 2026-05-24
>
> 领域模型见 [domain-model.md](domain-model.md)，产品方案见 [product.md](product.md)。

## 系统架构

```
                    ┌──────────────────────────┐
                    │          core             │
                    │  models.py  端口协议       │
                    │  (最内层，不依赖任何人)      │
                    └──────────▲───────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────┴──────┐  ┌─────┴──────┐         │
     │    ingest     │  │    rag     │         │
     │  数据获取      │  │  检索+生成  │         │
     └───────────────┘  └─────▲──────┘         │
                              │                │
                     ┌────────┴──────┐         │
                     │    agent      │         │
                     │  数字人对话    │         │
                     └────────▲──────┘         │
                              │                │
                     ┌────────┴──────┐         │
                     │     eval      │─────────┘
                     │   观测/测评    │
                     └───────────────┘

依赖方向 (──→ = "depends on"):
  ingest ──→ core
  rag    ──→ core
  agent  ──→ rag + core
  eval   ──→ rag + agent + core
```

```
valhalla/
│
├── ingest/                  # 📥 数据获取与维护
│   ├── bilibili.py          #   BiliClient: B 站 API 封装
│   ├── downloader.py        #   音频下载 + FFmpeg 转码
│   ├── transcriber.py       #   faster-whisper + OpenCC + hotwords
│   ├── indexer.py           #   IndexManager: JSON 索引
│   ├── processor.py         #   SubtitleProcessor: Layer 3 LLM 纠错
│   ├── prompts.py           #   Layer 3 纠错 prompt 模板
│   └── __main__.py          #   CLI: --mid --pages --llm-process
│
├── rag/                     # 🔍 检索增强生成
│   ├── chunker.py           #   processed JSON → 多层 chunks
│   ├── embeddings.py        #   bge-small-zh-v1.5 向量化
│   ├── store.py             #   Milvus Lite 向量库管理
│   ├── retriever.py         #   混合检索 (向量+BM25+RRF) + parent doc
│   ├── generator.py         #   RAG 回答生成 + source 引用
│   └── __main__.py          #   CLI: --ask "PE是什么？"
│
├── agent/                   # 🤖 数字人对话
│   ├── persona.py           #   数字人 system prompt 定义
│   ├── conversation.py      #   多轮对话 + 查询改写 + session 管理
│   └── __main__.py          #   CLI: --chat
│
├── eval/                    # 📊 质量测评
│   ├── retrieval.py         #   Recall@K / MRR / NDCG
│   ├── generation.py        #   LLM-as-Judge (忠实度/相关性/完整性)
│   ├── persona.py           #   数字人一致性评分
│   ├── benchmark.py         #   测试集 + 综合报告
│   └── __main__.py          #   CLI: --eval
│
└── core/                    # 🧱 共享基础设施
    ├── models.py            #   Pydantic 领域模型
    ├── llm.py               #   ChatBackend Protocol + DeepSeekBackend
    └── env.py               #   load_env() 配置加载

依赖方向: eval → rag → core  |  agent → rag → core  |  ingest → core
                              core 不依赖任何人
```

## 技术选型

### 语音转录: faster-whisper 1.2.1 (turbo 模型)

默认 `turbo` (809M)，CPU 实时率 ~3x。通过 domain prompt + 38 个 hotwords 增强金融术语识别。OpenCC t2s 繁转简兜底。

### 音频下载: httpx + FFmpeg

B 站 DASH 音画天然分离，直接下载音频流 URL。FFmpeg 转 16kHz mono s16 WAV，转后即删。

### 语义纠错 (Layer 3): DeepSeek V4 Flash

把 Whisper 输出分批发给 LLM 纠错 + 去口语化 + 话题分段。批内 4 并发调 API。含缓存 (按 segment hash) + JSON 解析失败降级。

### 向量库: Milvus Lite

嵌入式，`pip install pymilvus`，HNSW 索引 + 内置 BM25 混合检索。每个 UP 主独立 db 文件。上限 ~1M 向量/文件。

### Embedding: bge-small-zh-v1.5

95MB，512-dim，sentence-transformers 加载，中文 MTEB 中上。备选: bge-large-zh-v1.5。

### LLM 调用: ChatBackend Protocol

所有 LLM 调用通过 `ChatBackend` Protocol 解耦。当前实现: DeepSeek V4 Flash (openai SDK 兼容)。切换后端只改一行。

### 索引存储: JSON 文件

index.json 管理视频元数据。~200KB 解析毫秒级，零依赖。

## 组件设计

### ingest/ — 数据获取与维护

| 模块 | 职责 |
|------|------|
| BiliClient | B 站 API: 视频列表、系列、DASH 音频流 URL |
| downloader | httpx 流式下载 + FFmpeg 转码 |
| Transcriber | faster-whisper + OpenCC + hotwords |
| IndexManager | JSON 索引读写 + 统计查询 |
| SubtitleProcessor | Layer 3: 分批 LLM 纠错 + 缓存 + 降级 |

### rag/ — 检索增强生成

| 模块 | 职责 |
|------|------|
| Chunker | processed JSON sections → 三层混合 chunks (section + keyword + video_summary) |
| Embedder | bge-small-zh-v1.5 封装，单例懒加载 |
| VectorStore | Milvus Lite CRUD + 元数据过滤搜索 |
| Retriever | 混合检索 (HNSW + BM25 + RRF) + parent doc 扩展 + video_id 去重 |
| Generator | context 组装 + RAG prompt + LLM 生成 + source 引用 |

### agent/ — 数字人对话

| 模块 | 职责 |
|------|------|
| Persona | UP 主 "史诗级韭菜" 人设 system prompt |
| ConversationAgent | 多轮对话管理 + 查询改写 + session 持久化 |

### eval/ — 质量测评

| 模块 | 职责 |
|------|------|
| RetrievalEval | Recall@K / Precision@K / MRR / NDCG |
| GenerationEval | LLM-as-Judge: 忠实度 / 相关性 / 完整性 / 引用准确度 |
| PersonaEval | 第一人称一致性 / 风格匹配 / 边界遵守 |
| Benchmark | 三类测试用例（事实/多跳/全局）+ 综合报告 |

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 同步包装异步 | `sync()` | bilibili-api-python 全异步，避免引入 asyncio |
| 中间文件不保留 | 默认删 .m4s/.wav | WAV 可从 m4s 重建，只保留 SRT |
| 索引格式 | JSON | 数据量小，零依赖，人可读 |
| Layer 3 可选 | 可跳过 LLM 纠错 | 降低最小可用门槛 |
| 数据正模与 API 分离 | list/dict 存数据，边界处转换 | 不受外部 API 格式约束 |
| Agent 框架 | 暂不引入，手写 ~100 行 | 当前线性对话不需要框架 |
| 向量库 | Milvus Lite (嵌入式) | HNSW + 内置 BM25，零运维 |
| 测评方式 | LLM-as-Judge + 自动构造测试集 | 零人工标注 |

## 存储估算

基于 1,389 个视频全量处理:

| 保留方案 | 组成 | 大小 |
|---------|------|------|
| 纯文本 (SRT + 索引) | Layer 1 + 2 | ~300MB |
| + 语义文本 | + Layer 3 | ~320MB |
| + 向量库 | + chunks + Milvus Lite | ~1.5GB |
| + 音频 .m4s | + 下载音频 | ~14GB |

## 演进路线

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1 | 视频列表 + DASH + small 转录 + JSON 索引 | ✅ |
| v0.2 | turbo + hotwords + Layer 3 LLM 纠错 | ✅ |
| v0.3 | 代码重构 (ingest/rag/agent/eval/core 子包) | ✅ |
| v0.4 | RAG 管道 + 数字人 Agent + 测评体系 | 🔜 进行中 |
| v0.5 | LightRAG 图检索 + Contextual Retrieval | 规划中 |
| v1.0 | Web UI、定时增量、多 UP 主、知识图谱 | 愿景 |
