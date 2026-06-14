"""RAG CLI: 建索引 / 搜索 / 问答"""
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
from valhalla.rag.generator import RAGGenerator

OUTPUT = Path("output")


def cmd_build(args):
    """构建/重建向量索引"""
    setup_logging()
    logger = logging.getLogger(__name__)
    mid = args.mid
    processed_dir = OUTPUT / str(mid) / "processed"
    if not processed_dir.exists():
        logger.error("processed/ 目录不存在: %s", processed_dir)
        return

    # 加载 dated
    idx_path = OUTPUT / str(mid) / "index.json"
    dates = {}
    if idx_path.exists():
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        dates = {bvid: v.get("published_date", "")
                 for bvid, v in idx.get("videos", {}).items()}

    chunks = build_all_chunks(processed_dir, dates)
    logger.info("生成 %d 个 chunks", len(chunks))

    embedder = BGEEmbedder()
    logger.info("向量化...")
    texts = [c.text for c in chunks]
    vectors = embedder.encode(texts)
    for c, v in zip(chunks, vectors):
        c.vector = v.tolist()

    index_dir = OUTPUT / str(mid) / "faiss_index"
    index_dir.mkdir(parents=True, exist_ok=True)
    store = VectorStore(str(index_dir))
    store.rebuild(chunks)
    logger.info("完成: %d 条向量已入库 → %s", store.count(), index_dir)


def cmd_search(args):
    """纯检索测试"""
    setup_logging()
    logger = logging.getLogger(__name__)
    mid = args.mid
    db_path = OUTPUT / str(mid) / "faiss_index"
    if not db_path.exists():
        logger.error("vectordb 不存在，请先 run build")
        return

    store = VectorStore(str(db_path))
    store.load()
    embedder = BGEEmbedder()
    retriever = HybridRetriever(store, embedder)

    # 需要加载 BM25 语料
    processed_dir = OUTPUT / str(mid) / "processed"
    dates = {}
    idx_path = OUTPUT / str(mid) / "index.json"
    if idx_path.exists():
        dates = {bvid: v.get("published_date", "")
                 for bvid, v in json.loads(idx_path.read_text(encoding="utf-8")).get("videos", {}).items()}
    from valhalla.rag.chunker import build_all_chunks
    all_chunks = build_all_chunks(processed_dir, dates)
    retriever.set_corpus(all_chunks)

    for query in args.query:
        print(f"\n🔍 {query}")
        hits = retriever.search(query, top_k=5)
        for i, h in enumerate(hits, 1):
            print(f"  {i}. [{h.heading}] (score={h.score:.3f}) @{h.start_time:.0f}s")
            print(f"     {h.text[:80]}...")


def cmd_ask(args):
    """RAG 问答"""
    setup_logging()
    logger = logging.getLogger(__name__)
    mid = args.mid
    db_path = OUTPUT / str(mid) / "faiss_index"
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
    generator = RAGGenerator(retriever, backend)

    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    question = " ".join(args.ask)
    print(f"\n🔍 问题: {question}\n")
    resp = generator.ask(question)
    print(resp.answer)
    print(f"\n--- 来源 ---")
    for s in resp.sources:
        print(f"  [{s['heading']}] @{s['start_time']:.0f}s (score={s['score']})")


def main():
    parser = argparse.ArgumentParser(description="RAG 检索增强生成")
    sub = parser.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build", help="构建/重建向量索引")
    p_build.add_argument("--mid", type=int, required=True)

    p_search = sub.add_parser("search", help="纯检索测试")
    p_search.add_argument("--mid", type=int, required=True)
    p_search.add_argument("query", nargs="*")

    p_ask = sub.add_parser("ask", help="RAG 问答")
    p_ask.add_argument("--mid", type=int, required=True)
    p_ask.add_argument("ask", nargs="+")

    args = parser.parse_args()
    if args.cmd == "build":
        cmd_build(args)
    elif args.cmd == "search":
        cmd_search(args)
    elif args.cmd == "ask":
        cmd_ask(args)


if __name__ == "__main__":
    main()
