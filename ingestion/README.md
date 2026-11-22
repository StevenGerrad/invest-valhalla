# 数据采集

采集模块为后续采集流程提供数字人登记、资料实体与存储接口。当前可以构造领域对象，供新服务层和存储实现接入。实际拉取仍使用项目已有的 `valhalla.cli`。

## 使用实体和接口

```python
from datetime import datetime, timezone

from ingestion.entity import AvatarEntity, Platform, SubtitleMaterialEntity, SubtitleSegment
from ingestion.storage import AvatarRepository, MaterialRepository

avatar = AvatarEntity(
    id=1,
    name="示例数字人",
    source_urls=["https://platform-a.example/creator", "https://platform-b.example/creator"],
)
created_at = datetime.now(timezone.utc)
material = SubtitleMaterialEntity(
    id=1,
    created_at=created_at,
    updated_at=created_at,
    author_id=avatar.id,
    platform=Platform.BILIBILI,
    source_key="BV1xx411c7mD",
    source_url="https://www.bilibili.com/video/BV1xx411c7mD/",
    raw_segments=[SubtitleSegment(start_seconds=0, end_seconds=2, text="第一段转录。")],
    optimized_segments=[
        SubtitleSegment(start_seconds=0, end_seconds=2, text="第一段。", heading="开场")
    ],
)
```

一个数字人对应一个本地作者。数字人的 `source_urls` 保存各平台的作者主页地址。

`MaterialEntity` 是资料抽象基类，保存各类资料共有的字段。`SubtitleMaterialEntity` 的 `raw_segments` 和 `optimized_segments` 分别保存原始稿与 Agent 优化稿。两个列表使用同一种字幕片段结构，起止时间均为相对源媒体起点的秒数。尚未优化时，`optimized_segments` 为空列表。

`metadata` 保存来源扩展信息，`content_hash` 对应原始稿。

`platform` 接收 `Platform` 枚举成员。用 `Platform(value)` 解析配置或存储中的字符串，无效的平台值会抛出 `ValueError`。

数字人和资料各自拥有自增 ID。Python 使用 `int`，可以完整表示 PostgreSQL `BIGINT` 的取值范围。资料的 `created_at` 和 `updated_at` 分别记录首次保存和最近修改时间。

### 仓储接口

- 数字人登记用 `AvatarRepository.create()` 分配本地 ID，用 `update()` 更新现有登记，用 `get()` 或 `list_all()` 读取登记。
- 资料用 `MaterialRepository.get()` 读取单份完整实体，用 `list_by_author()` 读取指定作者的全部资料实体，用 `save()` 统一保存 `MaterialEntity`。

以上为存储接口契约。

## 继续使用现有采集命令

```powershell
uv run --locked --extra bilibili --extra transcription python -m valhalla.cli --mid 322005137 --pages 1 --skip-existing
```

现有命令默认将原始字幕写到 `data/{mid}/srt/`，启用 `--llm-process` 后将纠错结果写到 `data/{mid}/processed/`。启用纠错时同时安装 `agent` 依赖组合，并按[项目 README](../README.md)配置模型凭据。

开发边界和逐文件说明见 [CLAUDE.md](CLAUDE.md)。PostgreSQL 备选方案及暂缓采用的原因见[采集存储设计](docs/spec/采集存储设计.md)。
