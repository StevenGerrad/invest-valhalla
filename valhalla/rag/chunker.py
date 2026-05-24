"""processed JSON → 多层 chunks"""
import json
import logging
from pathlib import Path

from valhalla.core.models import Chunk, ProcessedSection

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 500
OVERLAP_CHARS = 50


def build_chunks(processed_path: Path) -> list[Chunk]:
    """从一个 processed JSON 构建三层 chunks"""
    data = json.loads(processed_path.read_text(encoding="utf-8"))
    bvid = data["bvid"]
    title = data.get("title", "")

    sections = [ProcessedSection(**s) for s in data.get("sections", [])]
    chunks: list[Chunk] = []

    for si, sec in enumerate(sections):
        sid = f"{bvid}_{si}"

        # 1. Section / SectionFragment
        text = sec.text
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(Chunk(
                chunk_id=sid,
                chunk_type="section",
                bvid=bvid, heading=sec.heading,
                text=text,
                start_time=sec.start_time, end_time=sec.end_time,
                keywords=sec.keywords,
            ))
        else:
            # 按 MAX_CHUNK_CHARS 切，重叠 OVERLAP_CHARS
            sub_idx = 0
            pos = 0
            while pos < len(text):
                sub = text[pos:pos + MAX_CHUNK_CHARS]
                chunks.append(Chunk(
                    chunk_id=f"{sid}_{sub_idx}",
                    chunk_type="section_fragment",
                    bvid=bvid, heading=sec.heading,
                    text=sub,
                    start_time=sec.start_time, end_time=sec.end_time,
                    keywords=sec.keywords,
                ))
                pos += MAX_CHUNK_CHARS - OVERLAP_CHARS
                sub_idx += 1

        # 2. Keywords chunk (轻量，匹配短查询)
        if sec.keywords:
            kw_text = f"{sec.heading}: {', '.join(sec.keywords[:8])}"
            chunks.append(Chunk(
                chunk_id=f"{sid}_kw",
                chunk_type="keywords",
                bvid=bvid, heading=sec.heading,
                text=kw_text,
                start_time=sec.start_time, end_time=sec.end_time,
                keywords=sec.keywords,
            ))

    # 3. Video summary chunk
    if sections:
        summary_text = f"《{title}》章节: " + " → ".join(s.heading for s in sections)
        chunks.append(Chunk(
            chunk_id=f"{bvid}_summary",
            chunk_type="video_summary",
            bvid=bvid, heading="视频摘要",
            text=summary_text,
            start_time=0.0, end_time=(sections[-1].end_time if sections else 0.0),
            keywords=list(data.get("global_keywords", [])[:10]),
        ))

    return chunks


def build_all_chunks(processed_dir: Path, published_dates: dict[str, str] | None = None) -> list[Chunk]:
    """从 processed/ 目录批量构建所有视频的 chunks"""
    all_chunks: list[Chunk] = []
    for f in sorted(processed_dir.glob("*.json")):
        try:
            chunks = build_chunks(f)
            if published_dates and chunks:
                date = published_dates.get(chunks[0].bvid, "")
                for c in chunks:
                    c.published_date = date
            all_chunks.extend(chunks)
        except Exception as e:
            logger.warning("跳过 %s: %s", f.name, e)
    logger.info("生成 %d 个 chunks (来自 %d 个视频)",
                len(all_chunks),
                len(set(c.bvid for c in all_chunks)))
    return all_chunks
