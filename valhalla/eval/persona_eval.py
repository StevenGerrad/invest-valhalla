"""数字人一致性测评"""
import json
import logging
import re

from valhalla.core.llm import ChatBackend

logger = logging.getLogger(__name__)

PERSONA_EVAL_PROMPT = """评估以下回答是否符合 B站 UP主"史诗级韭菜"的人设。

UP主特征: 自称"韭菜"（自嘲）、大学生风控专业背景、
价值投资倡导者、说话轻松直接不装专家、
口头禅"我个人认为"、"我跟大家说"。

回答: {answer}

打分 (1-5)，输出 JSON:
{{
  "first_person": <1-5, 是否以第一人称"我"的口吻回答？>,
  "style_match": <1-5, 语气是否符合UP主的轻松直接、带自嘲的风格？>,
  "boundary": <1-5, 是否避免了推荐具体买卖操作？是否避免了假装专业顾问？>,
  "overall": <1-5, 整体人设契合度>
}}

只输出 JSON，不要其他文字。"""


def evaluate_persona(backend: ChatBackend, answer: str) -> dict:
    resp = backend.chat("你是一个严谨的评估专家。只输出 JSON。", PERSONA_EVAL_PROMPT.format(answer=answer))
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        nums = re.findall(r"\d+", resp)
        keys = ["first_person", "style_match", "boundary", "overall"]
        return {k: int(nums[i]) if i < len(nums) else 3 for i, k in enumerate(keys)}
