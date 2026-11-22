# 通用能力接入开发说明

本模块提供可独立调用的外部能力。采集范围、任务调度、字幕纠错策略与资料存储由调用方负责。面向使用者的示例见 [README.md](README.md)。

## 开发约定

- 调用方使用各子包的公开入口。平台 SDK 响应、流地址和供应商请求格式在接入实现中处理。
- 集中配置在 `config.toml`，按能力分节。调用方显式传入凭据。密钥、签名地址等敏感值遵循[项目开发规范](../docs/spec/项目开发规范.md)。
- B 站读取与扫码接口为异步调用。媒体转换与文本模型当前使用同步接口。调用方负责调度、展示和重试。
- 媒体和字幕位置以媒体时间轴为准。网页文本保留 HTML 源行列位置。定位信息应随结果一起返回，方便后续引用。
- 测试布局遵循[项目代码规范](../docs/spec/项目代码规范.md)，文档字符串和测试执行方式遵循 [Python 代码规范](../docs/spec/Python代码规范.md)。

## 代码结构

```text
integration/
├── README.md                        # 公共能力、安装组合和调用示例
├── CLAUDE.md                        # 开发边界、源文件职责与测试命令
├── config.py                        # 加载配置默认值并合并指定节的本地覆盖项
├── config.toml                      # B 站、模型渠道、FFmpeg 和 Whisper 公开配置
├── fetcher/
│   └── bilibili/
│       ├── __init__.py              # 导出 B 站接入的公开函数、类型和异常
│       ├── auth.py                  # 读取旧凭据文件，创建二维码并查询登录状态
│       └── client.py                # 读取投稿、合集和视频详情，下载音频并检查完整性
├── converter/
│   ├── __init__.py                  # 导出转换函数、配置、结果类型和异常
│   ├── audio.py                     # 用 FFmpeg 提取首条音轨，输出完整的 PCM WAV
│   ├── subtitle.py                  # 校验带时间戳的字幕段，渲染为 SRT 文本
│   ├── webpage.py                   # 从 HTML 提取正文段落，保留源行列位置
│   └── whisper.py                   # 按需加载 Whisper 和 OpenCC，返回带时间戳的片段
├── llm/
│   ├── __init__.py                  # 导出 ChatBackend、错误类型和后端创建入口
│   └── client.py                    # 构建 OpenAI 兼容后端，统一回复、流式事件和错误
└── test/
    ├── fetcher/
    │   └── bilibili/
    │       ├── test_auth.py         # 模拟扫码状态、终态复用和旧凭据读取
    │       └── test_client.py       # 模拟分页、元数据归一化和音频下载失败恢复
    ├── converter/
    │   ├── test_audio.py            # 验证 FFmpeg 参数、原子替换和超时处理
    │   ├── test_subtitle.py         # 验证时间戳舍入和非法时间判断
    │   ├── test_webpage.py          # 验证正文提取、回退路径和源坐标
    │   └── test_whisper.py          # 验证模型惰性加载、片段位置和识别失败处理
    └── llm/
        └── test_client.py          # 模拟模型渠道、请求格式、流式事件和异常
```

## 运行单元测试

从项目根目录在 PowerShell 运行。单元测试使用模拟网络响应和本地临时目录。

```powershell
$testFiles = Get-ChildItem -LiteralPath integration/test -Recurse -File -Filter 'test_*.py' |
    ForEach-Object { Resolve-Path -LiteralPath $_.FullName -Relative }
uv run --locked --extra bilibili --extra agent python -m unittest @testFiles
```
