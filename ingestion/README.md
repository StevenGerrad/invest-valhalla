# 数据采集

采集模块提供数字人登记、B 站投稿与合集浏览、字幕采集和 Agent 加工。CLI 使用本地文件仓储。

## 使用采集命令

从项目根目录运行。浏览远端需要 `bilibili`，采集字幕还需要 `transcription` 和 FFmpeg，加工字幕需要 `llm` 和对应模型的 API Key。

```powershell
uv sync --locked --extra bilibili --extra transcription --extra llm
uv run --locked --extra bilibili --extra transcription --extra llm python -m ingestion.interaction.cli --help
```

初次登记博主可以通过服务接口完成，例如在项目根目录运行以下 Python 代码。

```python
import asyncio
from pathlib import Path

from ingestion.entity import Platform
from ingestion.service import AvatarPlatformParam, CreateAvatarParam
from ingestion.service.avatar.impl.avatar_service_impl import AvatarServiceImpl
from ingestion.storage.impl.local_file.avatar_repository_impl import AvatarRepositoryImpl
from ingestion.storage.impl.local_file.material_repository_impl import MaterialRepositoryImpl

data = Path("data/ingestion")
service = AvatarServiceImpl(AvatarRepositoryImpl(data), MaterialRepositoryImpl(data))
account = AvatarPlatformParam(Platform.BILIBILI, "https://space.bilibili.com/322005137")
avatar = asyncio.run(service.create_avatar(CreateAvatarParam("示例作者", [account])))
print(avatar.id)
```

按上一步返回的本地博主 ID 浏览。采集后使用命令输出的本地资料 ID 查看或加工。

```powershell
python -m ingestion.interaction.cli avatar list
python -m ingestion.interaction.cli material list-remote --avatar-id 1 --platform bilibili --page 1
python -m ingestion.interaction.cli material collect --avatar-id 1 --platform bilibili --source-key BV1xx411c7mD
python -m ingestion.interaction.cli material list-local --avatar-id 1
python -m ingestion.interaction.cli material show --material-id 1
python -m ingestion.interaction.cli material process --material-id 1
```

也可以用一条命令采集并加工一份资料。默认使用 DeepSeek Flash，可通过 `--provider` 和 `--model` 指定模型。

```powershell
python -m ingestion.interaction.cli material collect-and-process --avatar-id 1 --platform bilibili --source-key BV1xx411c7mD --provider deepseek --model deepseek-flash
```

上述命令使用已安装依赖的项目 Python 环境。B 站合集可传 `--collection-key 123` 或 `--collection-key series:123`。需要登录时，通过扫码获得会话并保存到根目录的 `.sessions/bilibili.json`。加工默认使用 `DEEPSEEK_API_KEY`。可通过环境变量或 `.env` 中的 `VALHALLA_LLM_PROVIDER=tokenhub` 切到 TokenHub，并提供 `TOKENHUB_API_KEY`。 [会话文件格式](../integration/README.md#b-站内容拉取)

仓储将作者登记和资料索引写入 `data/ingestion/`，原始 SRT 和加工 JSON 分别保存在作者及平台对应的 `srt/`、`processed/` 目录。

`material show` 读取已保存的原稿和加工稿，在加工稿末尾显示全文关键词。`material process` 将整份原稿提交给所选模型。新加工段保存起止时间和正文，全文关键词保存在 `global_keywords`。

CLI 的日志写入 `logs/ingestion/`。用日志行中的 `run_id` 串联同一次采集、加工或查询。 [日志排查说明](../core/README.md)

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
        SubtitleSegment(start_seconds=0, end_seconds=2, text="第一段。")
    ],
)
```

一个数字人对应一个本地作者。数字人的 `source_urls` 保存各平台的作者主页地址。

`MaterialEntity` 是资料抽象基类，保存各类资料共有的字段。`SubtitleMaterialEntity` 的 `raw_segments` 和 `optimized_segments` 分别保存原始稿与 Agent 优化稿。两个列表使用同一种字幕片段结构，起止时间均为相对源媒体起点的秒数。尚未优化时，`optimized_segments` 为空列表。

`metadata` 保存来源扩展信息，`content_hash` 对应原始稿。

`platform` 接收 `Platform` 枚举成员。用 `Platform(value)` 解析配置或存储中的字符串，无效的平台值会抛出 `ValueError`。

数字人和资料各自拥有自增 ID。Python 使用 `int`，可以完整表示 PostgreSQL `BIGINT` 的取值范围。资料的 `created_at` 和 `updated_at` 分别记录首次保存和最近修改时间。

### 仓储接口

- 数字人登记用 `AvatarRepository.create()` 分配本地 ID，用 `update()` 更新现有登记，用 `get()` 或 `list_all()` 读取登记，用 `delete()` 删除无资料的作者。
- 资料用 `MaterialRepository.get()` 按来源读取，用 `get_by_id()` 按本地 ID 读取，用 `list_by_author()` 读取指定作者的全部资料。统一使用 `save()` 保存完整实体。

### 服务接口

- `AvatarService` 查询、登记和更新数字人及其平台账号。通过 `list_avatars()` 取得全部 `AvatarInfo`，可直接用查询结果指定后续操作的目标。
- `MaterialService` 的 `list_remote_materials()` 按数字人和平台列出远端资料，`collect_material()` 与 `batch_collect_material()` 根据选定的 `source_key` 采集原始内容。查询本地资料时返回 `MaterialDetail`，删除资料时移除原始稿与加工稿。
- `MaterialProcessService` 的 `process_material()` 与 `batch_process_material()` 加工已保存的原始资料。`delete_processed_material()` 与 `batch_delete_processed_material()` 仅移除加工稿。
- `MaterialCollectAndProcessService` 提供 `collect_and_process_material()` 和 `batch_collect_and_process_material()`。B 站实现先保存原稿，再调用现有字幕加工服务。调用方可通过 `model_selection` 指定模型目录中的组合，省略时使用 DeepSeek Flash。已有原稿时可复用，已有加工稿时可跳过。加工失败后，已保存的原稿可用于重试。 [模型选择说明](../integration/README.md#文本模型)

服务方法是异步契约。单条删除成功时返回 `None`，失败时抛出异常。批量操作按输入顺序逐项返回结果。

`CollectionResult`、`ProcessingResult` 和 `DeletionResult` 共用 `ResultStatus`。成功使用 `SUCCESS`，跳过使用 `SKIPPED`，无需加工使用 `NOT_REQUIRED`，批量项失败使用 `FAILED`。

单条和批量的采集、加工参数均使用 `skip_existing`。默认 `True`，采集时跳过已有原稿的资料，加工时跳过已有加工稿的资料。传入 `False` 可重新执行相应操作。

开发边界和逐文件说明见 [CLAUDE.md](CLAUDE.md)。PostgreSQL 备选方案及暂缓采用的原因见[采集存储设计](docs/spec/采集存储设计.md)。
