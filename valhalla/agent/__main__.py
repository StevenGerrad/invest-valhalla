"""Agent CLI: 数字人对话"""
import argparse
import json
import logging
import sys
import io
from pathlib import Path

from valhalla.core.logging import setup as setup_logging
from valhalla.core.llm import DeepSeekBackend
from valhalla.rag.embeddings import BGEEmbedder
from valhalla.rag.chunker import build_all_chunks
from valhalla.rag.store import VectorStore
from valhalla.rag.retriever import HybridRetriever
from valhalla.agent.conversation import ConversationAgent

OUTPUT = Path("output")


def main():
    parser = argparse.ArgumentParser(description="数字人 '史诗级韭菜' 对话")
    parser.add_argument("--mid", type=int, default=322005137)
    parser.add_argument("--session", default=None, help="会话ID (断点续聊)")
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    mid = args.mid
    db_path = OUTPUT / str(mid) / "faiss_index"
    if not db_path.exists():
        print("向量库未建。请先运行: python -m valhalla.rag build --mid 322005137")
        return

    logger.info("加载向量库: %s", db_path)
    store = VectorStore(str(db_path))
    store.load()
    embedder = BGEEmbedder()
    retriever = HybridRetriever(store, embedder)

    processed_dir = OUTPUT / str(mid) / "processed"
    dates = {}
    idx_path = OUTPUT / str(mid) / "index.json"
    if idx_path.exists():
        dates = {bvid: v.get("published_date", "")
                 for bvid, v in json.loads(idx_path.read_text(encoding="utf-8")).get("videos", {}).items()}
    all_chunks = build_all_chunks(processed_dir, dates)
    retriever.set_corpus(all_chunks)

    backend = DeepSeekBackend()
    agent = ConversationAgent(retriever, backend)

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    session_id = args.session
    print("=" * 50)
    print("  史诗级韭菜 — 数字人对话")
    print("  输入 /quit 退出, /clear 清除历史")
    print("=" * 50)

    while True:
        try:
            user_input = input("\n你: ")
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue
        if user_input.strip() == "/quit":
            break
        if user_input.strip() == "/clear":
            session_id = None
            print("[历史已清除]")
            continue

        logger.info("用户: %s", user_input[:100])
        try:
            resp = agent.chat(session_id, user_input)
        except Exception as e:
            logger.error("回答失败: %s", e)
            print(f"\n[出错了: {e}]")
            continue

        if session_id is None:
            session_id = resp.sources[0].get("bvid", "")[:8] if resp.sources else "new"

        print(f"\n韭菜: {resp.answer}")
        if resp.sources:
            print(f"\n  ── 参考来源 ──")
            for s in resp.sources[:3]:
                print(f"  · [{s['heading']}] @{s['start_time']:.0f}s")
        logger.info("回答完成, %d 个来源", len(resp.sources))


if __name__ == "__main__":
    main()
