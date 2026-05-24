"""基准测试集 + 综合测评报告"""
import json
import logging
from pathlib import Path

from valhalla.core.llm import ChatBackend
from valhalla.core.models import EvalCase, Chunk, ProcessedSection
from valhalla.rag.retriever import HybridRetriever
from valhalla.rag.generator import RAGGenerator
from valhalla.eval.retrieval import evaluate as eval_retrieval
from valhalla.eval.generation import batch_evaluate as eval_generation
from valhalla.eval.persona_eval import evaluate_persona

logger = logging.getLogger(__name__)


def build_cases(chunks: list[Chunk], n: int = 20) -> list[EvalCase]:
    """从 chunk 列表自动构建测评用例: 每个 chunk 的 heading 当作事实型查询"""
    cases = []
    seen_headings = set()
    for c in chunks:
        if c.chunk_type not in ("section", "section_fragment"):
            continue
        if c.heading in seen_headings:
            continue
        seen_headings.add(c.heading)
        cases.append(EvalCase(
            query=c.heading,
            type="factual",
            relevant_chunk_ids=[c.chunk_id],
            min_sources=1,
        ))
        if len(cases) >= n:
            break
    return cases


def run_full_eval(retriever: HybridRetriever, generator: RAGGenerator,
                  backend: ChatBackend,
                  chunks: list[Chunk], n_cases: int = 10) -> dict:
    """完整测评: 检索 + 生成 + 人设"""
    cases = build_cases(chunks, n_cases)

    # 1. 检索测评
    logger.info("检索测评: %d 条", len(cases))
    retrieval_report = eval_retrieval(retriever, cases)

    # 2. 生成测评
    logger.info("生成测评: %d 条", len(cases))
    questions = [c.query for c in cases[:5]]
    answers_sources = [generator.ask(q) for q in questions]
    answers = [a.answer for a in answers_sources]
    sources_list = [a.sources for a in answers_sources]
    gen_report = eval_generation(backend, questions, answers, sources_list)

    # 3. 人设测评
    logger.info("人设测评: %d 条", len(answers))
    persona_scores = [evaluate_persona(backend, a) for a in answers]
    persona_report = {
        k: round(sum(p[k] for p in persona_scores) / len(persona_scores), 2)
        for k in persona_scores[0] if persona_scores
    }

    return {
        "n_cases": len(cases),
        "retrieval": retrieval_report,
        "generation": gen_report,
        "persona": persona_report,
    }
