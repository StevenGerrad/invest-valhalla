# 知识图谱构建框架对比

> 2026-05-24 | 调研笔记

## 总览

```
框架设计的核心分歧点：

            全自动 LLM 抽取              Schema 约束 + 规则
            ──────────────              ────────────────
            KGGen / LightRAG            KAG / LlamaIndex PG
            MS GraphRAG                 AutoKG
                │                           │
                │                           │
        ┌───────┴────────┐          ┌───────┴────────┐
        │                │          │                │
    抽取后聚类+摘要   抽取后不摘要   Schema定义抽取范围  混合搜索增强LLM
    (MS GraphRAG)    (LightRAG)    (KAG/LlamaIndex)  (AutoKG)
                                        │
                                    ┌───┴───┐
                                Schema约束  规则推理
                                (KAG)     (KAG逻辑形式)
```

另一个维度：**时间感知**。只有 Graphiti 把时间作为一等公民。

---

## 一、八个框架的构建原理

### 1. MS GraphRAG

**输入**：文档 → 分块 → LLM 抽取实体/关系 → **Leiden 社区聚类** → **LLM 为每个社区生成摘要**

最重的步骤是社区摘要。假设 1000 个社区，每个社区一份摘要，这就是 1000 次 LLM 调用。

**图的用途**：间接的——图本身不被查询，而是通过图结构把文档组织成社区，社区摘要才是检索目标。

### 2. LightRAG

**输入**：文档 → 分块 → LLM 抽取实体/关系 → **双层图**（低层实体+关系，高层社区节点）→ 实体/关系分别 Embed → 向量索引

和 MS GraphRAG 的关键区别：**聚类后不生成摘要**。社区只是作为一个节点存在。检索时用双层关键词并行搜：低层搜实体（精确匹配），高层搜主题（语义扩展）。

### 3. KAG (蚂蚁 OpenSPG)

**输入**：文档 → **Schema 定义**（实体类型/关系类型/语义规则）→ LLM 在 Schema 约束下抽取 → **语义对齐**（synonym/isA/belongTo 六大关系归一化）→ 三层知识（结构化/Schema-Free/原文 Chunk）

和 LightRAG/MS GraphRAG 的本质区别：**不是"扔给 LLM 自由发挥"，而是先定义 Schema，LLM 在框架内抽取**。关系有类型标签（belongsTo/reports/outperforms），不只是描述文本。

### 4. Graphiti (Zep)

**输入**：对话/事件/文本流（称为"episodes"）→ LLM 逐 episode 抽取实体/关系 → **双时态图**（valid_time + transaction_time 双时间轴）→ 边失效而非删除（`invalid_at` 标记）→ 三种子图（Episode/Semantic Entity/Community）→ 混合检索（语义+BM25+图遍历）

**独特的双时态模型**：

```
普通 KG:    (横店影视) --[净利润]--> (增长20%)   ← 只知道"当前事实"
Graphiti:   (横店影视) --[净利润]--> (增长20%) [2024Q1~2024Q4, ingested 2024-04-15]
            (横店影视) --[净利润]--> (下降5%)  [2025Q1~now, ingested 2025-04-20]
                      ↑ 旧边 invalidated，不删除，保留审计轨迹
```

**图的用途**：作为 agent 的持久记忆。查询"横店影视去年业绩如何？"→ 走 valid_time 轴，只取有效事实；查询"横店影视的业绩历史？"→ 走全量时间轴。

### 5. LlamaIndex PropertyGraphIndex + Neo4j

**输入**：文档 → **Schema 定义**（`Literal["DRUG","DISEASE"]`）→ `SchemaLLMPathExtractor` 强制 LLM 按 Schema 抽取 → Neo4j 属性图存储 → **三种检索器组合**（LLMSynonymRetriever + VectorContextRetriever + CypherTemplateRetriever）

本质是把 KAG 的逻辑搬到了 LlamaIndex 生态里。Schema 约束 + Neo4j Cypher 查询 + LlamaIndex 框架集成。和 KAG 的区别在于它**绑定 LlamaIndex 和 Neo4j**，没法换后端。

### 6. KGGen (kg-gen)

**输入**：文档 → **两步 LLM**：先抽实体 → 再抽三元组 → S-BERT Embed + k-means 聚类合并同义实体/边 → 迭代聚类直到稳定 → 输出去重后的干净图

和所有其他框架的本质区别在于**抽取质量方法论**。它不是靠 Schema 约束（KAG）、也不是靠社区检测（MS GraphRAG）、也不是靠阈值去重（LightRAG），而是靠 **迭代聚类算法**——用 embedding + BM25 + k-means 不断合并等价节点，直到图稳定。

```
多 chunk 抽取后的原始三元组:
  ("纽约市","是美国","最大城市")
  ("NYC","位于","美国")
  ("纽约","人口","800万")

KGGen 聚类后:
  ("纽约市" <synonym> "NYC" <synonym> "纽约") ← 合并为同一节点
  ("纽约市","是美国","最大城市")
  ("纽约市","人口","800万")
  ("纽约市","位于","美国")
```

**效果**：MINE 基准上 66.07%，MS GraphRAG 只有 47.80%，OpenIE 只有 29.84%。

### 7. AutoKG

**输入**：文档 → 自动提取关键术语 → 构建图结构 → **混合搜索**（向量相似度 + 图关联关键词）

最轻量的方案。不是做知识图谱构建，而是**用图结构增强 LLM 的搜索和 RAG**。Jupyter Notebook 交互式使用，适合实验和原型。

### 8. Fast-GraphRAG

**输入**：和 MS GraphRAG 类似，但用 **PageRank** 替代 Leiden 做图探索，支持增量更新。

定位在 MS GraphRAG 和 LightRAG 之间：比 MS 轻，比 LightRAG 重。

---

## 二、差异根源：对"知识"的定义不同

| 框架 | "知识"是什么 | 检索单元 |
|------|-------------|---------|
| **MS GraphRAG** | 社区摘要文本 | 社区摘要 |
| **LightRAG** | 实体 + 关系向量 | 实体/关系 embedding + 图邻居 |
| **KAG** | Schema 约束的实体+类型化关系 | 图遍历路径 + 原文 Chunk |
| **Graphiti** | 带时间轴的实体+关系+社区 | 当前有效事实（或全量历史） |
| **LlamaIndex PG** | Schema 约束的属性图 | 三种检索器组合结果 |
| **KGGen** | 去重聚合后的三元组 | 干净的三元组图 |
| **AutoKG** | 关键词 + 图结构 | 向量 + 图联合搜索 |
| **Fast-GraphRAG** | PageRank 排序后的实体+社区 | 图遍历路径 |

---

## 三、效果差异

### 抽取质量（MINE 基准）

| 方法 | MINE Score | 特点 |
|------|:--:|------|
| **KGGen** | **66.07%** | 迭代聚类去重，图最干净 |
| MS GraphRAG | 47.80% | 不做去重，噪音多 |
| OpenIE | 29.84% | 传统方法 |

### GraphRAG-Bench（FalkorDB 基准，2,010 个问题）

| 系统 | 事实检索 | 复杂推理 | 上下文摘要 | 综合得分 |
|------|:--:|:--:|:--:|:--:|
| **FalkorDB GraphRAG-SDK** | 65.22 | 58.63 | 69.54 | **63.73** |
| MS GraphRAG (local) | 49.29 | 50.93 | 64.40 | 50.93 |
| LightRAG | 58.62 | 49.07 | 48.85 | 45.09 |

### LongMemEval（agent 长期记忆基准）

| | Baseline | +Graphiti | 延迟改善 |
|------|:--:|:--:|:--:|
| GPT-4o-mini | 55.4% | **63.8%** | 31.3s → **3.2s** |
| GPT-4o | 60.2% | **71.2%** | 28.9s → **2.58s** |

---

## 四、选择矩阵：按项目阶段

| 你的阶段 | 需求 | 推荐 | 原因 |
|------|------|------|------|
| **现在 (v0.3-v0.4)** | 第一版 RAG 跑通 | 纯向量（你已规划） | 0 额外成本，先验证问答质量 |
| **引入 KG (v0.5)** | 跨视频多跳问答 + 增量追加 | **LightRAG** | 追加不需重建、低查询成本、中文友好 |
| **需要时间维度** | "仓位策略这些年怎么变的？" | **Graphiti**（备选追加） | 唯一支持时间轴 |
| **多 UP 主 + 专业术语标准化** | 跨 UP 主查询、术语消歧 | **KAG** 或 **KGGen** | Schema 约束 + 迭代去重 |
| **已在用 LlamaIndex** | 不想换生态 | **LlamaIndex PropertyGraphIndex** | 原生集成 |
| **极致抽取质量** | 关系必须准确、不能有噪音 | **KGGen** | MINE 66%，最高 |

### 最低摩擦路径

```
Phase 1: 纯向量 RAG (你当前)
Phase 2: 纯向量 + Parent Document Retriever + Rerank (下个迭代)
Phase 3: + LightRAG (增量追加, 零重建)
Phase 4: 如需时间轴 → + Graphiti
        如需术语标准化 → + KAG
```

---

## 五、一句话总结每个框架

| 框架 | 一句话 |
|------|------|
| **MS GraphRAG** | 最贵的方案，最强的全局聚合，数据静止不动时最合适 |
| **LightRAG** | 最适合增量追加的轻量方案，成本低 99.98% |
| **KAG** | Schema 约束下最可靠，蚂蚁在金融场景验证过 |
| **Graphiti** | 唯一支持"知识随时间变化"的框架，agent 记忆的正确答案 |
| **LlamaIndex PG** | 如果你选了 LlamaIndex 生态，这就是无缝的选择 |
| **KGGen** | 抽取质量最高的纯研究框架，图最干净 |
| **AutoKG** | 最轻量的实验方案，Jupyter 友好 |
| **Fast-GraphRAG** | PageRank 替代 Leiden，更快更可视化 |
