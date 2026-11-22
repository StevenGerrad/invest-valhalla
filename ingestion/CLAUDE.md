# 数据采集开发说明

当前实现定义数字人登记和采集资料实体，以及对应的 Repository 契约。使用方式见 [README.md](README.md)。PostgreSQL 备选方案、暂缓采用的原因及 DDL 草案见[采集存储设计](docs/spec/采集存储设计.md)。

## 开发约定

- `AvatarEntity` 同时表示数字人与本地作者。`source_urls` 保存可直接打开的各平台作者主页地址。
- `MaterialEntity` 是资料抽象基类，使用 `author_id` 关联数字人，用 `platform` 和 `source_key` 定位来源。`content_hash` 对应原始稿。
- `SubtitleMaterialEntity` 分别提供原始字幕与优化字幕的片段列表。存储实现负责在实体与已有的 SRT、纠错 JSON 格式之间转换，并维护创建时间与修改时间。
- `Platform` 枚举定义可采集的来源平台。存储使用成员的字符串值，读回时将其解析为枚举成员。
- 数字人 ID 和资料 ID 在 Python 中使用 `int`，由各自的存储实现自增分配。切换到 PostgreSQL 时映射为 `BIGINT`。
- 服务层依赖 Repository 接口。后续 `RepositoryImpl` 负责领域实体与私有 DO 的转换，按作者和内容 ID 分别保存 `srt/` 和 `processed/` 文件。
- 资料仓储以完整的 `MaterialEntity` 为读写单位。存储实现按实体的具体类型处理内容的落盘和还原。
- 新采集流程由 `pipeline` 编排，通过公开接口调用通用能力接入和存储。CLI 与未来管理界面的入口归 `interaction`。
- 当前生产数据由旧 CLI 管理。新增文件存储实现时，先用临时目录或副本验证兼容性。

## 代码结构

```text
ingestion/
├── README.md                        # 实体与接口用法，以及当前可用的旧采集命令
├── CLAUDE.md                        # 模块边界、源文件职责与测试约定
├── docs/
│   └── spec/
│       └── 采集存储设计.md            # PostgreSQL 备选方案、暂缓采用的原因及 SQL 草案
├── entity/
│   ├── __init__.py                  # 导出领域实体、字幕片段和平台枚举
│   ├── avatar.py                    # 定义数字人的本地 ID、名称与平台主页列表
│   ├── material.py                  # 定义资料抽象基类及其公共字段
│   ├── platform.py                  # 定义来源平台枚举及其存储标识
│   └── subtitle_material.py         # 定义字幕资料子类和带时间的字幕片段
└── storage/
    ├── __init__.py                  # 导出两个 Repository 接口
    ├── avatar_repository.py         # 声明数字人登记的创建、更新和查询接口
    └── material_repository.py       # 声明完整资料实体的查询与保存接口
```

## 验证与测试

从项目根目录验证实体和接口可导入。

```powershell
uv run --locked python -c "from ingestion.entity import AvatarEntity, MaterialEntity, SubtitleMaterialEntity, SubtitleSegment; from ingestion.storage import AvatarRepository, MaterialRepository"
```

后续单元测试放在 `test/` 下，按被测模块的相对路径组织，例如 `storage/avatar_repository.py` 对应 `test/storage/test_avatar_repository.py`。通用约定见[项目代码规范](../docs/spec/项目代码规范.md)，文档字符串和测试执行方式见 [Python 代码规范](../docs/spec/Python代码规范.md)。
