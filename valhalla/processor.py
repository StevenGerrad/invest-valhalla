"""Layer 3: LLM 字幕后处理 — 分批 + 缓存 + 合并 + 并行"""
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from valhalla.core.llm import ChatBackend
from valhalla.prompts import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # 每批最多 20 个 segment
OVERLAP = 3      # 相邻批次重叠段数
MAX_WORKERS = 4  # DeepSeek API 并发数


class SubtitleProcessor:
    """LLM 字幕后处理器：纠错 + 去口语化 + 话题分段"""

    def __init__(self, backend: ChatBackend,
                 cache_dir: Path | None = None,
                 max_workers: int = MAX_WORKERS):
        self._backend = backend
        self._cache_dir = cache_dir
        self._max_workers = max_workers

    def process(self, bvid: str, title: str,
                segments: list[dict]) -> dict:
        """处理一个视频的全部 segments，batch 内 LLM 调用并行"""
        batches = self._make_batches(segments)
        total = len(batches)

        # 分离：缓存命中 vs 需要调 API
        results: list[dict | None] = [None] * total
        pending: list[tuple[int, list[dict], str]] = []

        for i, batch in enumerate(batches):
            key = self._cache_key(bvid, batch)
            cached = self._load_cache(key)
            if cached is not None:
                results[i] = cached
                logger.info("缓存命中 %d/%d", i + 1, total)
            else:
                pending.append((i, batch, key))

        # 并行调 API
        if pending:
            logger.info("并行处理 %d/%d 批次 (max_workers=%d)...",
                        len(pending), total, self._max_workers)
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                futures = {
                    pool.submit(self._process_batch, title, batch): (idx, key)
                    for idx, batch, key in pending
                }
                for future in as_completed(futures):
                    idx, key = futures[future]
                    try:
                        results[idx] = future.result()
                        self._save_cache(key, results[idx])
                    except Exception as e:
                        logger.error("批次 %d 失败: %s", idx + 1, e)
                        # 找到对应 batch 做降级
                        results[idx] = self._fallback_sections(batches[idx])

        # 按原始顺序合并
        all_sections: list[dict] = []
        all_keywords: list[str] = []
        for r in results:
            if r is None:
                continue
            all_sections.extend(r.get("sections", []))
            all_keywords.extend(r.get("global_keywords", []))

        merged = self._merge_sections(all_sections)
        return {
            "bvid": bvid,
            "title": title,
            "sections": merged,
            "global_keywords": sorted(set(all_keywords)),
        }

    def _process_batch(self, title: str,
                       batch: list[dict]) -> dict:
        """调 LLM 处理单批，含重试和降级（线程安全）"""
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
