# 领域模型

> 描述系统的核心业务概念、实体关系和数据形态。不涉及技术选型（用什么模型/数据库），只定义"是什么"。

## 实体

```
UP主 (Uploader)
  mid: int                 # B 站用户 ID，唯一标识
  name: str                # 昵称
  │
  │ 1 : N
  ▼
视频 (Video)
  bvid: str                # BV 号，全局唯一
  title: str               # 标题
  author: str              # UP 主名称
  duration_seconds: int    # 视频时长
  published_ts: int        # 发布时间戳 (UTC)
  published_date: str      # 发布日期 YYYY-MM-DD
  play_count: int          # 播放量
  │
  ├── 1 : 1 ──→ 字幕 (Subtitle)
  │               bvid: str              # 关联视频
  │               segments: [Segment]    # 时间戳 + 文本段
  │               segment_count: int
  │
  ├── 1 : 1 ──→ 语义文本 (ProcessedText)   [可选]
  │               bvid: str
  │               sections: [Section]      # 结构化段落
  │               concepts: [Concept]      # 提取的术语
  │               quality_score: float     # 转录质量评估
  │
  └── 1 : N ──→ 检索分段 (Chunk)
                  chunk_id: str          # 全局唯一标识
                  bvid: str              # 回溯视频
                  text: str              # 段落正文 (embedding 输入)
                  heading: str           # 所属段落标题
                  start_time: float      # 视频内起始秒数
                  end_time: float        # 视频内结束秒数
                  keywords: [str]        # 辅助检索加权
                  prev_chunk_id: str     # 前一 chunk (上下文扩展链)
                  next_chunk_id: str     # 后一 chunk (上下文扩展链)
```

### 值对象

```python
Segment = {
    "start": float,   # 起始秒数
    "end": float,     # 结束秒数
    "text": str,      # 字幕文本
}

Section = {
    "section_id": int,
    "heading": str,           # 段落标题
    "start_time": float,
    "end_time": float,
    "text": str,              # 去口语化、带标点的正文
    "keywords": [str],        # 关键词列表
    "summary": str,           # 段落摘要
}

Concept = {
    "term": str,              # 术语名
    "definition": str,        # 在视频中的定义/解释
    "mentioned_at": float,    # 提及的时间点
}
```

## 实体关系

```
UP主 ──1:N──→ 视频 ──1:1──→ 字幕 ──1:N──→ Segment (时间片段)
                │
                ├──1:1──→ 语义文本 ──1:N──→ Section (话题段落)
                │                              │
                │                              └── 切分依据
                │                                     ↓
                └──1:N──→ 检索分段 (Chunk) ←── 可来自 Section 或直接来自 Segment

Chunk ←→ Chunk:  prev/next_chunk_id 双向链表，检索时扩展上下文窗口
Chunk ←→ Video:  bvid 回溯源视频元数据
```

## 数据流水线

视频的音频数据经历四个处理阶段，每个阶段产出独立的数据形态：

```
原始音频
  │  转录 (faster-whisper)
  ▼
[1] 原始字幕 ──── 不可重建的真源 ──── SRT 格式，逐段时间戳 + 文本
  │              含口语化特征和识别错误
  │
  │  提取元数据
  ▼
[2] 视频索引 ──── 视频→字幕的映射目录 ── 元数据 + 处理状态追踪
  │              可从 [1] 重建
  │
  │  LLM 整理 (可选)
  ▼
[3] 语义文本 ──── 结构化"文章级"文本 ── 纠错 + 去口语化 + 话题分割
  │              可从 [1] 重建
  │
  │  切分
  ▼
[4] 检索分段 ──── 适合向量化的短文本单元 ── 300~500 字，带双向链表
  │              可从 [3] 或 [1] 重建
  │
  │  embedding
  ▼
  向量数据库 ──── 支持语义搜索的向量索引
```

**重建依赖链**: `[1]` 是唯一真源，`[2][3][4]` 均为派生数据。`[4]` 可降级从 `[1]` 直接生成（跳过 `[3]`），代价是检索质量下降。

**增量更新**: 新视频到达时，逐层追加：`[1]` 写入新 SRT → `[2]` 索引追加条目 → `[3]` 可选 LLM 处理 → `[4]` 追加 chunk + 向量增量入库。

## 检索与对话层 (v0.4 新增)

### Chunk（检索分段）

```python
Chunk = {
    "chunk_id": str,          # 全局唯一: {bvid}_{section_id}_{sub_id}
    "chunk_type": str,        # "section" | "section_fragment" | "keywords" | "video_summary"
    "bvid": str,              # 回溯视频
    "heading": str,           # 所属 section 标题
    "text": str,              # embedding 输入文本
    "start_time": float,      # 视频内起始秒
    "end_time": float,        # 视频内结束秒
    "keywords": [str],        # BM25 加权
    "published_date": str,    # 视频发布日期 (YYYY-MM-DD)
    "vector": [float],        # 512-dim, 入库时填充
}
```

三种 chunk_type 互补:
- `section`: 完整语义段落 (≤500 字)
- `section_fragment`: 长 section 的切分子段 (≤500 字，50 字重叠)
- `keywords`: section 标题 + 关键词拼接 (轻量，短查询匹配)
- `video_summary`: 所有 section heading 拼接 (视频级摘要)

### Embedding（向量嵌入）

```
bge-small-zh-v1.5 (95MB, 512-dim)
  normalize_embeddings=True → 余弦 = 内积
  CPU 推理，~1000 chunks/s
```

### 向量检索（Milvus Lite）

```
Collection "chunks"
  Schema: chunk_id(VARCHAR PK) + bvid + text + vector(FLOAT_VECTOR 512) + heading
          + chunk_type + start_time + end_time + keywords + published_date
  Index: HNSW on vector, metric=COSINE
  检索: .search(query_vector, filter_expr, top_k)
```

### 混合检索

```
用户查询
  ├── HNSW 向量检索 top-20 (语义泛化)
  └── BM25 关键词检索 top-10 (术语精确匹配)
       ↓
  RRF 融合 → top-10
       ↓
  video_id 去重 (同一视频只保留最高分 chunk)
       ↓
  Parent Document 扩展 (返回完整 section 文本)
```

### 对话会话

```python
Message = {
    "role": str,       # "user" | "assistant"
    "content": str,    # 消息内容
    "timestamp": str,  # ISO 时间
}

Session = {
    "session_id": str,
    "persona": str,    # 数字人 system prompt
    "history": [Message],  # 最近 N 轮
    "created_at": str,
}
```

### 测评实体

```python
EvalCase = {
    "query": str,              # 测试问题
    "type": str,               # "factual" | "multi_hop" | "global" | "persona"
    "relevant_chunk_ids": [str],  # 理想结果 (检索测评用)
    "min_sources": int,        # 最少引用数 (生成测评用)
}

RetrievalEvalResult = {
    "recall_at_k": float,   # Recall@K
    "precision_at_k": float,
    "mrr": float,           # Mean Reciprocal Rank
    "ndcg_at_k": float,
}

GenerationEvalResult = {
    "faithfulness": float,  # 忠实度 (1-5)
    "relevance": float,     # 相关性
    "completeness": float,  # 完整性
    "citation_accuracy": float,
}

PersonaEvalResult = {
    "first_person": float,  # 第一人称一致性
    "style_match": float,   # 风格匹配度
    "boundary_compliance": float,  # 边界遵守
}
```

## 领域规则

- 一个视频有且仅有一份 SRT 字幕（1:1），但可有多份不同策略产出的 chunk 集
- 语义文本层 (`[3]`) 是可选的：跳过时直接从 `[1]` 切分到 `[4]`
- SRT 的 `segment_count` 反映 Whisper 识别粒度，不等于话题数或 chunk 数
- `quality_score` 综合评估转录置信度 + 音频清晰度，用于过滤低质量内容
- Chunk 按 `chunk_type` 分层：检索时可用 `chunk_type` 过滤，优先 section 类
- 同一个 chunk_id 的多种 chunk_type 指向同一视频位置，检索去重时以 chunk_id 为基准
- 数字人对话中，Persona 约束优先级高于检索上下文——不能因检索结果违背人设
