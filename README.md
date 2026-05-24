# B站 UP 主视频字幕生成器

爬取 B 站 UP 主视频，下载音频，使用本地 AI 模型自动生成 SRT 字幕。

## 快速开始

```bash
# 1. 安装环境
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt    # 国内: set HF_ENDPOINT=https://hf-mirror.com

# 2. 登录 B 站 (仅一次)
python -m valhalla.cli --login

# 3. 生成字幕
python -m valhalla.cli --mid <UP主ID> --pages 5
```

## 使用方式

```bash
# 处理 UP 主最新 60 个视频
python -m valhalla.cli --mid 322005137 --pages 2

# 处理指定系列/合集 (URL 中 lists/ 后的数字)
python -m valhalla.cli --mid 322005137 --series 5488551

# 增量模式 (跳过已有字幕)
python -m valhalla.cli --mid 322005137 --pages 3 --skip-existing

# 查看已有字幕
python -m valhalla.cli --mid 322005137 --list
python -m valhalla.cli --mid 322005137 --stats
python -m valhalla.cli --mid 322005137 --search 投资

# 完整参数
python -m valhalla.cli \
    --mid 322005137 \
    --pages 5 \
    --limit 10 \
    --model medium \
    --skip-existing \
    --keep-audio
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mid` | UP 主用户 ID (必填) | - |
| `--series` | 系列/合集 ID | - |
| `--pages` | 爬取页数 (每页 30 个) | 1 |
| `--limit` | 最多处理视频数 (0=全部) | 0 |
| `--model` | Whisper 模型 (tiny/base/small/medium/large) | small |
| `--output-dir` | 输出根目录 | output |
| `--skip-existing` | 跳过已有字幕 | false |
| `--keep-audio` | 保留下载的音频 | false |
| `--dry-run` | 仅列出视频不处理 | false |
| `--login` | 二维码登录 | - |

## 输出结构

```
output/{mid}/
├── index.json        # 元数据索引 (可查询、搜索)
└── srt/              # SRT 字幕文件
    └── {bvid}.srt
```

## 依赖

- Python 3.12+
- FFmpeg (winget: `winget install Gyan.FFmpeg`)
- 详见 [requirements.txt](requirements.txt)
