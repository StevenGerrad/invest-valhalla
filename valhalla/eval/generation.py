"""生成测评: LLM-as-Judge 评估回答质量"""
import json
import logging
import re

from valhalla.core.llm import ChatBackend
from valhalla.core.models import ChunkWithScore

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """你是一个 RAG 回答质量评估专家。评估以下回答。

参考上下文:
{context}

用户问题: {question}
系统回答: {answer}

请从以下维度打分，输出 JSON (每个维度 1-5 分):
{{
  "faithfulness": <1-5, 回答是否严格基于参考上下文？有没有编造？>,
  "relevance": <1-5, 回答是否直接回应了用户问题？>,
  "completeness": <1-5, 回答是否覆盖了上下文中的关键信息？>,
  "citation": <1-5, 引用格式和来源是否准确？>
}}

只输出 JSON，不要其他文字。"""


def evaluate_answer(backend: ChatBackend, question: str, answer: str,
                    sources: list[dict]) -> dict:
    """LLM-as-Judge 评估单条回答"""
    context = "\n\n".join(
        f"[{i+1}] {s.get('heading', '')}: {s.get('text', '')[:200]}"
        for i, s in enumerate(sources[:5])
    )
    prompt = JUDGE_PROMPT.format(question=question, answer=answer, context=context)
    resp = backend.chat("你是一个严谨的评估专家。只输出 JSON。", prompt)
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        nums = re.findall(r"\d+", resp)
        keys = ["faithfulness", "relevance", "completeness", "citation"]
        return {k: int(nums[i]) if i < len(nums) else 3 for i, k in enumerate(keys)}


def batch_evaluate(backend: ChatBackend,
                   questions: list[str],
                   answers: list[str],
                   sources_list: list[list[dict]]) -> dict:
    """批量评估"""
    scores = {"faithfulness": [], "relevance": [], "completeness": [], "citation": []}
    for q, a, s in zip(questions, answers, sources_list):
        r = evaluate_answer(backend, q, a, s)
        for k in scores:
            scores[k].append(r.get(k, 3))
    return {k: round(sum(v) / len(v), 2) if v else 0 for k, v in scores.items()}
