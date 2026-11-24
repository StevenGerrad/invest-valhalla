# 数据采集开发说明

本模块提供数字人登记、B 站资料采集、字幕加工、本地文件 Repository 和 CLI。使用方式见 [README.md](README.md)。PostgreSQL 备选方案、暂缓采用的原因及 DDL 草案见[采集存储设计](docs/spec/采集存储设计.md)。

## 开发约定

- `AvatarEntity` 同时表示数字人与本地作者。`source_urls` 保存可直接打开的各平台作者主页地址。
- `MaterialEntity` 是资料抽象基类，使用 `author_id` 关联数字人，用 `platform` 和 `source_key` 定位来源。`content_hash` 对应原始稿。
- `SubtitleMaterialEntity` 分别提供原始字幕与优化字幕的片段列表。存储实现负责在实体与已有的 SRT、纠错 JSON 格式之间转换，并维护创建时间与修改时间。
- `Platform` 枚举定义可采集的来源平台。存储使用成员的字符串值，读回时将其解析为枚举成员。
- 数字人 ID 和资料 ID 在 Python 中使用 `int`，由各自的存储实现自增分配。切换到 PostgreSQL 时映射为 `BIGINT`。
- 服务层依赖 Repository 接口。具体实现按存储方式放入 `storage/impl/`。本地文件实现位于 `storage/impl/local_file/`，使用私有 DO，按作者和平台定位稿件，以资料索引指向当前原稿和加工稿。索引提交前已有稿件仍可读。条件保存以 `updated_at` 检查资料是否已改变。
- 资料仓储以完整的 `MaterialEntity` 为读写单位。存储实现按实体的具体类型处理内容的落盘和还原。
- 新采集流程由 `pipeline` 编排，通过公开接口调用通用能力接入和存储。CLI 与未来管理界面的入口归 `interaction`。
- `pipeline` 按博主管理、资料采集和资料加工分组。每个服务的接口放在服务目录，DTO 放入 `dto/`，具体实现放入 `impl/`。资料采集按平台和内容类型组织实现，资料加工按内容类型组织实现。
- `AvatarService` 管理数字人与平台账号。`MaterialService` 负责资料的浏览、采集和删除。`MaterialProcessService` 使用已保存的原始内容生成加工稿，删除加工稿时保留原始资料。
- 交互层从服务取得 `AvatarInfo`、`MaterialDetail` 等输出类型。它们可以通过 `AvatarIndex` 或 `MaterialIndex` 充当后续服务调用的目标。领域实体在服务与仓储之间传递。
- CLI 从 `core` 配置日志并为每次命令分配 `run_id`。服务记录任务结果和批量汇总，文件仓储在 `DEBUG` 下记录锁等待、读取和提交，在较高级别记录冲突和 I/O 故障。日志排查方式见[公共运行基础](../core/README.md)。
- 新 CLI 使用 `data/ingestion/`。旧 CLI 管理原有生产资料，迁移时先用临时目录或副本验证兼容性。

## 代码结构

```text
ingestion/
├── README.md                        # 新旧 CLI 使用方式、实体和接口示例
├── CLAUDE.md                        # 模块边界、源文件职责与测试约定
├── docs/
│   └── spec/
│       └── 采集存储设计.md            # PostgreSQL 备选方案、暂缓采用的原因及 SQL 草案
├── entity/
│   ├── __init__.py                  # 导出领域实体、身份索引、字幕片段和平台枚举
│   ├── avatar.py                    # 定义数字人的本地 ID、名称与平台主页列表
│   ├── index.py                     # 定义数字人与资料的身份索引接口
│   ├── material.py                  # 定义资料抽象基类及其公共字段
│   ├── platform.py                  # 定义来源平台枚举及其存储标识
│   └── subtitle_material.py         # 定义字幕资料子类和带时间的字幕片段
├── interaction/
│   └── cli/
│       ├── __main__.py              # 提供模块入口
│       ├── bootstrap.py             # 装配仓储、三个服务和按需加载的能力
│       ├── command.py               # 解析参数并调度服务契约
│       └── display.py               # 格式化列表、字幕和操作结果
├── pipeline/
│   ├── __init__.py                  # 导出服务接口和公共类型
│   ├── _support.py                  # 通用仓储调用和异常转换
│   ├── avatar/
│   │   ├── avatar_service.py        # 声明数字人及平台账号管理接口
│   │   ├── dto/
│   │   │   └── avatar_service_dto.py # 定义数字人服务的参数和返回信息
│   │   └── impl/
│   │       └── avatar_service_impl.py # 实现数字人登记与平台账号维护
│   ├── constant/
│   │   └── result_status.py         # 定义采集、加工和删除共用的结果状态
│   ├── error.py                     # 定义服务操作和冲突异常
│   ├── material/
│   │   ├── _support.py              # 资料详情转换和批量删除
│   │   ├── material_service.py      # 声明浏览、采集和删除接口
│   │   ├── dto/
│   │   │   └── material_service_dto.py # 定义采集参数、结果和共用的资料详情
│   │   └── impl/
│   │       └── bilibili_subtitle/
│   │           └── bilibili_subtitle_material_service_impl.py # 编排 B 站浏览、下载和转录
│   └── material_process/
│       ├── material_process_service.py     # 声明加工和删除加工稿的接口
│       ├── dto/
│       │   └── material_process_service_dto.py # 定义加工参数和执行结果
│       └── impl/
│           └── subtitle/
│               ├── subtitle_material_process_service_impl.py # 保存、复用和清除字幕加工稿
│               └── subtitle_processor.py   # 分批调用模型并校验、合并字幕
├── storage/
│   ├── __init__.py                  # 导出两个 Repository 接口
│   ├── avatar_repository.py         # 声明数字人登记读写和删除接口
│   ├── error.py                     # 定义仓储冲突错误
│   ├── impl/
│   │   └── local_file/
│   │       ├── _files.py             # 进程间文件锁、索引读写和原子替换
│   │       ├── _subtitle_codec.py    # 在实体和 SRT、加工 JSON 之间转换
│   │       ├── avatar_repository_impl.py   # 持久化数字人登记和自增 ID
│   │       └── material_repository_impl.py # 提交资料索引和稿件文件
│   └── material_repository.py       # 声明完整资料的查询、保存和删除接口
└── test/
    ├── interaction/cli/test_bootstrap.py   # 模拟远端并验证 CLI 跨调用读写
    ├── pipeline/avatar/impl/test_avatar_service_impl.py # 验证登记与删除规则
    └── storage/impl/local_file/test_material_repository_impl.py # 验证持久化、回滚和条件写入
```

## 验证与测试

从项目根目录验证实体和接口可导入。

```powershell
uv run --locked python -c "from ingestion.entity import AvatarIndex, MaterialIndex; from ingestion.pipeline import AvatarService, MaterialService, MaterialProcessService; from ingestion.storage import AvatarRepository, MaterialRepository"
```

单元测试放在 `test/` 下，按被测模块的相对路径组织。通用约定见[项目代码规范](../docs/development/项目代码规范.md)，文档字符串和测试执行方式见 [Python 代码规范](../docs/development/Python代码规范.md)。
