# 产品方案

## 产品目标

B 站 UP 主视频 → 结构化字幕 → 向量知识库 → 数字人 Agent → RAG 问答 + 测评。

## 核心场景

| 场景 | 描述 |
|------|------|
| 批量转录 | 一键将 UP 主数百个视频转为 SRT 字幕 |
| 系列处理 | 指定某个系列/合集单独处理 |
| 增量更新 | 定期运行，只下新视频，跳过已有 |
| 字幕索引 | 按日期、标题、播放量浏览/搜索已有字幕 |
| 知识问答 | 基于视频知识库的 RAG 问答，引用具体视频和时间点 |
| 数字人对话 | 以 UP 主口吻进行多轮对话，保持人设一致性 |
| 质量测评 | 自动化评估检索质量、生成质量和数字人一致性 |

## 产品演进路线

### v0.1 — 数据基础 ✅
- [x] 视频列表爬取 + DASH 音频下载
- [x] faster-whisper 本地转录 (small 模型)
- [x] 繁体→简体转换 (OpenCC)
- [x] 按 UP 主分类输出 + JSON 索引
- [x] `--list` / `--stats` / `--search` 索引查询
- [x] `--series` 系列视频处理
- [x] 二维码登录 + 凭据管理

### v0.2 — 转录提质 ✅
- [x] turbo 默认模型 (809M, large-v3 蒸馏)
- [x] hotwords 领域增强 + domain prompt
- [x] Layer 3 LLM 语义纠错 + 话题分段 (DeepSeek V4 Flash)
- [x] Layer 3 批内并行 (4 并发) + 视频间 I/O 预下载
- [x] `.env` 通用凭据管理

### v0.3 — 代码架构重构 (当前)
- [x] 子包拆分: `ingest/` `rag/` `agent/` `eval/` `core/`
- [x] 统一领域模型 (Pydantic models)
- [x] `--bvid` 单视频拉取 (仅脚本)

### v0.4 — RAG + Agent + 测评 (当前)
- [ ] Milvus Lite 向量库 + bge-small-zh-v1.5 embedding
- [ ] 混合检索 (向量 + BM25 + RRF) + Parent Document Retriever
- [ ] 数字人 persona "史诗级韭菜" + 多轮对话 + 查询改写
- [ ] 检索测评 (Recall@K / MRR / NDCG)
- [ ] 生成测评 (LLM-as-Judge: 忠实度/相关性/完整性)
- [ ] 数字人一致性测评 (第一人称/风格/边界)

### v0.5 — 高级检索
- [ ] LightRAG 图增强检索 (增量追加, 跨视频多跳推理)
- [ ] Contextual Retrieval (chunk 嵌入时附加上下文前缀)

### v1.0 — 愿景
- [ ] Web UI 管理面板
- [ ] 定时任务自动增量
- [ ] 多 UP 主支持 + 跨 UP 主查询
- [ ] 知识图谱自动构建 + 标签共现网络
