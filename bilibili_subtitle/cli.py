"""CLI 入口：B 站 UP 主视频字幕生成"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

from bilibili_subtitle.bilibili import BiliClient, load_credential_from_file, login_with_qrcode
from bilibili_subtitle.downloader import download_audio, convert_to_wav
from bilibili_subtitle.transcriber import Transcriber, srt_time
from bilibili_subtitle.indexer import IndexManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _print_list(mid: int, output_dir: Path, sort_by: str, reverse: bool,
                search: str | None, show_stats: bool):
    """列出已有字幕"""
    index = IndexManager(output_dir, mid)
    data = index.load()
    videos = data.get("videos", {})

    if not videos:
        print(f"UP主 {mid} 暂无本地字幕")
        return

    if show_stats:
        s = index.stats()
        print(f"UP主 {mid}")
        print(f"  本地字幕: {s['total']} 个")
        print(f"  总片段数: {s['total_segments']}")
        print(f"  总播放量: {s['total_plays']:,}")
        print(f"  日期范围: {s['earliest']} ~ {s['latest']}")
        return

    listed = index.list_videos(sort_by=sort_by, reverse=reverse, search=search)
    print(f"UP主 {mid} — {len(listed)} 个字幕")
    print(f"{'日期':<12} {'时长':>6} {'播放':>8} {'标题'}")
    print("-" * 70)
    for v in listed:
        length = v.get("length", "?")
        play = f"{v.get('play', 0):,}"
        date = v.get("published_date", "?")
        title = v.get("title", "?")[:45]
        segments = v.get("segment_count", 0)
        print(f"{date:<12} {length:>6} {play:>8} [{segments}段] {title}")


def main():
    parser = argparse.ArgumentParser(
        description="B站 UP 主视频字幕生成器 — 爬取视频列表，下载音频，生成 SRT 字幕"
    )
    parser.add_argument("--mid", type=int, required=True, help="UP 主用户 ID")
    parser.add_argument("--series", type=int, default=0, help="系列/合集 ID (URL 中 lists/ 后面的数字)")
    parser.add_argument("--pages", type=int, default=1, help="最大爬取页数，--series 模式下忽略")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个视频 (0=全部)")
    parser.add_argument("--model", default="small", help="Whisper 模型大小 (tiny/base/small/medium/large)")
    parser.add_argument("--device", default="cpu", help="推理设备 (cpu/cuda)")
    parser.add_argument("--output-dir", default="output", help="输出根目录")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已有字幕的视频")
    parser.add_argument("--keep-audio", action="store_true", help="保留下载的原始音频文件")
    parser.add_argument("--dry-run", action="store_true", help="只获取视频列表，不下载和转录")
    parser.add_argument("--login", action="store_true", help="使用二维码登录")
    parser.add_argument("--credential-file", default="bilibili_credential.env",
                        help="凭据文件路径")

    # 列表/查询
    parser.add_argument("--list", action="store_true", help="列出已有字幕")
    parser.add_argument("--stats", action="store_true", help="显示统计信息")
    parser.add_argument("--search", default=None, help="搜索关键词")
    parser.add_argument("--sort", default="published_ts", help="排序字段")
    parser.add_argument("--reverse", action="store_true", help="倒序排列")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    index = IndexManager(output_dir, args.mid)
    srt_dir = index.srt_dir
    audio_dir = index.dir / "audio"

    # 只列/查模式
    if args.list or args.stats or args.search:
        _print_list(args.mid, output_dir, args.sort, args.reverse,
                    args.search, args.stats)
        return

    logger.info("=" * 50)
    logger.info("B站 UP 主字幕生成器")
    logger.info("  UP 主 mid: %d", args.mid)
    logger.info("  模型: %s, 设备: %s", args.model, args.device)
    logger.info("  输出: %s", index.dir.resolve())
    logger.info("=" * 50)

    # 凭据
    if args.login:
        logger.info("启动二维码登录...")
        credential = login_with_qrcode()
        cred_file = Path(args.credential_file)
        with open(cred_file, "w", encoding="utf-8") as f:
            f.write(f"SESSDATA={credential.sessdata}\n")
            f.write(f"BILI_JCT={credential.bili_jct}\n")
            f.write(f"BUVID3={credential.buvid3}\n")
            f.write(f"BUVID4={credential.buvid4}\n")
            f.write(f"DEDEUSERID={credential.dedeuserid}\n")
            if credential.ac_time_value:
                f.write(f"AC_TIME_VALUE={credential.ac_time_value}\n")
        logger.info("凭据已保存: %s", cred_file)
    elif os.path.exists(args.credential_file):
        logger.info("加载凭据: %s", args.credential_file)
        credential = load_credential_from_file(args.credential_file)
    else:
        credential = None

    client = BiliClient(credential=credential)
    transcriber = Transcriber(model_size=args.model, device=args.device)

    if args.series:
        logger.info("获取系列视频 (series_id=%d)...", args.series)
        video_iter = client.iter_series_videos(args.mid, args.series)
    else:
        logger.info("获取视频列表...")
        video_iter = client.iter_all_videos(args.mid, max_pages=args.pages)

    processed = 0
    skipped = 0

    for item in video_iter:
        if args.limit and processed >= args.limit:
            break

        bvid = item["bvid"]
        title = item["title"]
        srt_path = srt_dir / f"{bvid}.srt"

        # 跳过已有字幕
        if args.skip_existing and index.has(bvid):
            logger.info("跳过 (已有字幕): [%s] %s", bvid, title[:40])
            skipped += 1
            continue

        logger.info("--- [%s] %s", bvid, title[:50])

        if args.dry_run:
            logger.info("  [DRY RUN] %s | %s | 播放:%s",
                        item.get("created", ""), item.get("length", ""), item.get("play", 0))
            processed += 1
            continue

        try:
            # 下载 + 转录
            audio_url, _ = client.get_best_audio_url(bvid)
            m4s_path = audio_dir / f"{bvid}.m4s"
            download_audio(audio_url, m4s_path)
            wav_path = convert_to_wav(m4s_path)

            # 转录并获取段数
            segments = transcriber.transcribe(wav_path)
            srt_path.parent.mkdir(parents=True, exist_ok=True)
            with open(srt_path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(segments, start=1):
                    f.write(f"{i}\n")
                    f.write(f"{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n")
                    f.write(seg["text"] + "\n\n")

            # 写入索引
            index.add(bvid, item, segment_count=len(segments))

            # 清理
            if not args.keep_audio:
                m4s_path.unlink(missing_ok=True)
                wav_path.unlink(missing_ok=True)

            processed += 1
            logger.info("完成: %s (%d 段)", srt_path, len(segments))

        except Exception as e:
            logger.error("处理失败 [%s]: %s", bvid, e)
            continue

        time.sleep(3)

    logger.info("=" * 50)
    logger.info("处理完成: %d 个, 跳过: %d 个", processed, skipped)
    logger.info("字幕目录: %s", srt_dir.resolve())
    logger.info("索引文件: %s", index.index_path.resolve())
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
