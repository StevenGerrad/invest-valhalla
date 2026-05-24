# CLAUDE.md

> 产品方案: [docs/product.md](docs/product.md) | 领域模型: [docs/domain-model.md](docs/domain-model.md) | 技术方案: [docs/architecture.md](docs/architecture.md) | 使用说明: [README.md](README.md)

## 项目概述

B 站 UP 主视频 → 下载音频 → 本地 AI 转录 → LLM 语义纠错 → 向量知识库 → RAG 问答 + 数字人 Agent。

## 环境

- Python 3.12.10 `.venv/`，FFmpeg 8.1.1 (winget)
- 详见 [requirements.txt](requirements.txt)
- DeepSeek API Key 配置在 `.env` (gitignored)，格式: `DEEPSEEK_API_KEY=sk-xxx`

### 运行时暗坑

```
# pip 必须绕过 Windows 系统代理（有时需要 unset 旧值）
unset no_proxy && export NO_PROXY="*" && export no_proxy="*" && python -m pip install xxx

# HuggingFace 国内需镜像
HF_ENDPOINT=https://hf-mirror.com python ...

# B 站 API 匿名请求频繁触发 412 → 用登录态
```

## 命令速查

```bash
# === 数据流水线 ===
# 登录 (仅一次)
python -m valhalla.cli --login

# UP 主全量 (含 LLM 纠错)
python -m valhalla.cli --mid 322005137 --pages 4 --limit 100 --skip-existing --llm-process

# 系列/合集
python -m valhalla.cli --mid 322005137 --series 5488551

# 查询
python -m valhalla.cli --mid 322005137 --list
python -m valhalla.cli --mid 322005137 --stats
python -m valhalla.cli --mid 322005137 --search 投资

# === RAG ===
# 构建向量索引
python -m valhalla.rag build --mid 322005137

# 纯检索测试
python -m valhalla.rag search --mid 322005137 PE估值 仓位管理

# RAG 问答
python -m valhalla.rag ask --mid 322005137 PE估值有哪三种方法？

# === 数字人对话 ===
python -m valhalla.agent --mid 322005137

# === 测评 ===
python -m valhalla.eval --mid 322005137 --n 10
```

## 编码约定

- `bilibili-api-python` 全部异步，用 `sync()` 包装为同步
- B 站请求间隔 >= 3s，遇到 412 等待 30s 重试
- 凭证文件 `.env` 不入 git
- FFmpeg 路径自动探测 (winget 路径优先，fallback PATH)
- 转录默认 `turbo` 模型（large-v3 蒸馏，medium 速度 + large 质量），`base` 精度不够不推荐
- 中间音频文件默认删除，`--keep-audio` 保留
- 字段需归一化：空间 API 返回 `length`/`created`/`play`，系列 API 返回 `duration`/`ctime`/`stat.view`
- **数据正模与 API 格式分离**：数据以最自然的形式存储（如 list），仅在调用外部 API 前转换（如 `" ".join()` 为 faster-whisper 的 hotwords 字符串）。典型案例见 [transcriber.py:13](valhalla/transcriber.py#L13) `DOMAIN_HOTWORDS: list[str]` → [transcriber.py:72](valhalla/transcriber.py#L72) `" ".join(hotwords)`。未来入库/配置化时 list 可直接映射，无需重构。

## 代码结构

```
valhalla/
├── core/                    # 🧱 共享基础设施
│   ├── models.py            #   Pydantic 领域模型
│   ├── llm.py               #   ChatBackend Protocol + DeepSeekBackend
│   └── env.py               #   load_env() 配置加载
├── ingest/                  # 📥 数据获取与维护
│   ├── bilibili.py          #   BiliClient: 视频列表 + 系列 + DASH
│   ├── downloader.py        #   httpx 下载 + FFmpeg
│   ├── transcriber.py       #   faster-whisper + OpenCC + hotwords
│   ├── indexer.py           #   IndexManager: JSON 索引
│   ├── processor.py         #   SubtitleProcessor: Layer 3 LLM 纠错
│   └── prompts.py           #   Layer 3 纠错 prompt 模板
├── rag/                     # 🔍 检索增强生成
│   ├── chunker.py           #   processed JSON → 多层 chunks
│   ├── embeddings.py        #   bge-small-zh-v1.5 向量化
│   ├── store.py             #   Milvus Lite 向量库
│   ├── retriever.py         #   混合检索 (HNSW+BM25+RRF)
│   ├── generator.py         #   RAG 回答生成 + source 引用
│   └── __main__.py          #   CLI: build / search / ask
├── agent/                   # 🤖 数字人对话
│   ├── persona.py           #   数字人 system prompt
│   ├── conversation.py      #   多轮对话 + 查询改写
│   └── __main__.py          #   CLI: --chat
├── eval/                    # 📊 质量测评
│   ├── retrieval.py         #   Recall@K / MRR / NDCG
│   ├── generation.py        #   LLM-as-Judge 评分
│   ├── persona_eval.py      #   数字人一致性评估
│   ├── benchmark.py         #   测试集 + 综合报告
│   └── __main__.py          #   CLI: --eval
├── cli.py                   # 顶层兼容入口 (→ ingest)
└── __init__.py              # 版本号
```

## 已知问题

- `iter_all_videos` 在系列模式下 `ChannelSeriesType.SEASON` 的 `get_meta()` 返回 total=0，实际从 `get_channel_videos_season` 获取
- Windows 终端 GBK 编码输不出中文表情，脚本需 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`
- `--limit` 不计算跳过的视频，仅计算实际处理的
