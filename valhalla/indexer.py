"""字幕索引管理：按 UP 主分类，JSON 索引"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

INDEX_FILENAME = "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ts_to_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class IndexManager:
    """管理单个 UP 主的字幕索引"""

    def __init__(self, base_dir: Path, mid: int):
        self.mid = mid
        self.dir = base_dir / str(mid)
        self.srt_dir = self.dir / "srt"
        self.index_path = self.dir / INDEX_FILENAME

    def load(self) -> dict:
        """加载索引，不存在则返回空结构"""
        if self.index_path.exists():
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"mid": self.mid, "videos": {}}

    def save(self, data: dict):
        """保存索引"""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        data["updated"] = _now_iso()
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def has(self, bvid: str) -> bool:
        """检查某视频是否已有字幕"""
        data = self.load()
        return bvid in data.get("videos", {})

    def add(self, bvid: str, meta: dict, segment_count: int = 0):
        """记录一个视频的字幕"""
        data = self.load()
        srt_rel = f"srt/{bvid}.srt"
        data["videos"][bvid] = {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "length": meta.get("length", ""),
            "published_ts": meta.get("created", 0),
            "published_date": _ts_to_date(meta.get("created", 0)),
            "play": meta.get("play", 0),
            "srt_file": srt_rel,
            "segment_count": segment_count,
            "downloaded_at": _now_iso(),
        }
        self.save(data)

    def list_videos(self, sort_by: str = "published_ts",
                    reverse: bool = False, search: Optional[str] = None) -> list[dict]:
        """列出所有已有字幕的视频"""
        data = self.load()
        videos = list(data.get("videos", {}).values())

        if search:
            q = search.lower()
            videos = [v for v in videos
                      if q in v.get("title", "").lower()
                      or q in v.get("author", "").lower()]

        key = sort_by if sort_by in ("published_ts", "downloaded_at", "play",
                                      "length", "segment_count") else "published_ts"
        videos.sort(key=lambda v: v.get(key, ""), reverse=reverse)
        return videos

    def stats(self) -> dict:
        """返回统计信息"""
        data = self.load()
        videos = data.get("videos", {})
        total = len(videos)
        if not total:
            return {"mid": self.mid, "total": 0}

        total_segments = sum(v.get("segment_count", 0) for v in videos.values())
        total_plays = sum(v.get("play", 0) for v in videos.values())
        dates = [v.get("published_date", "") for v in videos.values() if v.get("published_date")]
        return {
            "mid": self.mid,
            "total": total,
            "total_segments": total_segments,
            "total_plays": total_plays,
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None,
        }
