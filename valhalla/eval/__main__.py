"""Eval CLI: 批量测评"""
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
from valhalla.eval.benchmark import run_full_eval

OUTPUT = Path("output")


def main():
    parser = argparse.ArgumentParser(description="RAG 质量测评")
    parser.add_argument("--mid", type=int, default=322005137)
    parser.add_argument("--n", type=int, default=10, help="测评用例数")
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)
    mid = args.mid
    db_path = OUTPUT / str(mid) / "faiss_index"
    if not db_path.exists():
        print("向量库未建。请先运行: python -m valhalla.rag build --mid 322005137")
        return

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

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    logger.info("开始测评 (n=%d)...", args.n)
    report = run_full_eval(retriever, generator, backend, all_chunks, n_cases=args.n)

    print("\n" + "=" * 50)
    print("  📊 RAG 质量测评报告")
    print("=" * 50)
    print(f"\n测评用例数: {report['n_cases']}")
    print(f"\n## 检索质量")
    for k, v in report["retrieval"].items():
        if k != "n":
            print(f"  {k}: {v:.3f}")
    print(f"\n## 生成质量 (LLM-as-Judge, 1-5)")
    for k, v in report["generation"].items():
        print(f"  {k}: {v:.2f}")
    print(f"\n## 数字人一致性 (1-5)")
    for k, v in report["persona"].items():
        print(f"  {k}: {v:.2f}")


if __name__ == "__main__":
    main()
