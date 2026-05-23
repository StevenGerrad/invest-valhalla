"""Layer 3: LLM 字幕后处理 — 分批 + 缓存 + 合并"""
import hashlib
import json
import logging
from pathlib import Path

from bilibili_subtitle.llm import ChatBackend
from bilibili_subtitle.prompts import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # 每批最多 20 个 segment
OVERLAP = 3      # 相邻批次重叠段数


class SubtitleProcessor:
    """LLM 字幕后处理器：纠错 + 去口语化 + 话题分段"""

    def __init__(self, backend: ChatBackend,
                 cache_dir: Path | None = None):
        self._backend = backend
        self._cache_dir = cache_dir

    def process(self, bvid: str, title: str,
                segments: list[dict]) -> dict:
        """处理一个视频的全部 segments，返回 Layer 3 结构化数据"""
        batches = self._make_batches(segments)
        all_sections: list[dict] = []
        all_keywords: list[str] = []

        for i, batch in enumerate(batches):
            cache_key = self._cache_key(bvid, batch)
            result = self._load_cache(cache_key)
            if result is None:
                logger.info("处理批次 %d/%d (%d 段)",
                            i + 1, len(batches), len(batch))
                result = self._process_batch(title, batch)
                self._save_cache(cache_key, result)
            else:
                logger.info("缓存命中 批次 %d/%d", i + 1, len(batches))
            all_sections.extend(result.get("sections", []))
            all_keywords.extend(result.get("global_keywords", []))

        merged = self._merge_sections(all_sections)
        return {
            "bvid": bvid,
            "title": title,
            "sections": merged,
            "global_keywords": sorted(set(all_keywords)),
        }

    # ── 内部 ──────────────────────────────────────────

    def _process_batch(self, title: str,
                       batch: list[dict]) -> dict:
        """调 LLM 处理单批，含重试和降级"""
        user = build_user_message(title, batch)
        for attempt in range(3):
            try:
                raw = self._backend.chat(SYSTEM_PROMPT, user)
                result = json.loads(raw)
                self._validate(result)
                return result
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("第 %d 次解析失败: %s", attempt + 1, e)
                if attempt == 2:
                    return self._fallback_sections(batch)
        # unreachable
        return self._fallback_sections(batch)

    def _validate(self, result: dict):
        if "sections" not in result:
            raise ValueError("缺少 sections 字段")
        for s in result["sections"]:
            missing = [k for k in ("heading", "start_time", "end_time", "text")
                       if k not in s]
            if missing:
                raise ValueError(f"section 缺少字段 {missing}: {s}")

    def _fallback_sections(self, segments: list[dict]) -> dict:
        text = "".join(seg["text"] for seg in segments)
        return {
            "sections": [{
                "heading": "",
                "start_time": segments[0]["start"],
                "end_time": segments[-1]["end"],
                "text": text,
                "keywords": [],
            }],
            "global_keywords": [],
        }

    def _make_batches(self,
                      segments: list[dict]) -> list[list[dict]]:
        step = max(BATCH_SIZE - OVERLAP, 1)
        batches = []
        i = 0
        while i < len(segments):
            batches.append(segments[i:i + BATCH_SIZE])
            if i + BATCH_SIZE >= len(segments):
                break
            i += step
        return batches

    def _merge_sections(self, sections: list[dict]) -> list[dict]:
        if len(sections) <= 1:
            return sections
        merged = [sections[0]]
        for sec in sections[1:]:
            last = merged[-1]
            # 时间重叠超过 2 秒 → 同一段 → 跳过
            if sec["start_time"] <= last["end_time"] - 2.0:
                continue
            merged.append(sec)
        return merged

    # ── 缓存 ──────────────────────────────────────────

    def _cache_key(self, bvid: str, batch: list[dict]) -> str:
        texts = "".join(s["text"] for s in batch)
        h = hashlib.sha256(texts.encode()).hexdigest()[:16]
        return f"{bvid}_{h}"

    def _load_cache(self, key: str) -> dict | None:
        if not self._cache_dir:
            return None
        f = self._cache_dir / f"{key}.json"
        if f.exists():
            with open(f, encoding="utf-8") as fp:
                return json.load(fp)
        return None

    def _save_cache(self, key: str, result: dict):
        if not self._cache_dir:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self._cache_dir / f"{key}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
