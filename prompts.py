"""提示词模板：LLM 出题、答题、评分。"""

# ── 出题 ─────────────────────────────────────────


def build_question_prompt(operator_id: str, context: str) -> list[dict]:
    """构造出题提示词消息列表。

    返回 [system_message, user_message]，可直接传入 LLMClient.chat()。
    """
    system = (
        f"你是知识图谱中的「{operator_id}」Operator。"
        "你的任务：基于给定的材料创作有深度的阅读理解题。\n\n"
        "要求：\n"
        "1. 不得在题干中暗示答案方向（例如「与「材料A」中……是否有内在联系？」这种让人必须答「是」的不行）\n"
        "2. 不得出成选择题或判断题（不能简单用是/否回答）\n"
        "3. 一道大题下含若干道小题，无需标分值\n"
        "4. 最后一道题为开放题\n"
        "5. 输出严格的 JSON，不要包含其他文字"
    )

    user = (
        f"可参考的材料：\n{context}\n\n"
        "请基于以上材料出阅读理解题。\n\n"
        '输出 JSON 格式：\n'
        '{\n'
        '    "problem_theme": "主题理解与综合分析",\n'
        '    "problem_introduction": "引导语：介绍材料关联、引出问题",\n'
        '    "problems": ["小题1", "小题2", "小题3"],\n'
        '    "reference_answers": ["参考答案1", "参考答案2", "参考答案3"]\n'
        '}'
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_question_json(raw: str) -> dict | None:
    """从 LLM 回复中解析出题 JSON。"""
    import json
    import re

    # 尝试提取 JSON 块（LLM 可能用 ```json 包裹）
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        raw = match.group(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def format_question_text(qdata: dict) -> str:
    """将出题 JSON 格式化为可读的问题文本。"""
    parts = [qdata.get("problem_introduction", "")]
    for i, problem in enumerate(qdata.get("problems", []), 1):
        parts.append(f"{i}. {problem}")
    return "\n\n".join(parts)


# ── 答题 ─────────────────────────────────────────


def build_answer_prompt(operator_id: str, question: str, context: str) -> list[dict]:
    """构造答题提示词消息列表。"""
    system = (
        f"你是知识图谱中的「{operator_id}」Operator。"
        "你的任务：回答其他 Operator 提出的阅读理解题。\n\n"
        "要求：\n"
        "1. 回答要基于可参考的材料内容，引用原文作为支撑\n"
        "2. 可以结合多篇材料进行综合分析\n"
        "3. 可以适当提供新颖的解读视角\n"
        "4. 回答要完整、有条理\n"
        "5. 使用中文回答"
    )

    user = f"需要回答的问题：\n{question}\n\n可参考的材料：\n{context}\n\n请回答以上问题。"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── 评分 ─────────────────────────────────────────


def build_score_prompt(question: str, answer: str,
                       reference_answer: str | None = None) -> list[dict]:
    """构造评分提示词消息列表。"""
    ref_section = ""
    if reference_answer:
        ref_section = f"\n参考答案：\n{reference_answer}"

    system = (
        "你是知识图谱中的「评分者」Operator。"
        "你的任务：对其他 Operator 的回答进行评分。\n\n"
        "评分采用两个维度（各 0-100 分）：\n"
        "1. score_match —— 参考答案匹配度：回答是否准确回应了问题\n"
        "2. score_novelty —— 合理新颖度：是否提供了新颖且逻辑自洽的视角。"
        "若答案属于无效搅浑水、庸俗辩证、打太极的类型，此项应打低分\n\n"
        "评分参考标尺：60 = 及格，90 = 优秀，100 = 满分\n\n"
        "输出严格的 JSON，不要包含其他文字：\n"
        '{\n'
        '    "score_match": 85,\n'
        '    "score_novelty": 70,\n'
        '    "reasoning": "简要评分理由"\n'
        '}'
    )

    user = (
        f"需要评分的回答：\n{answer}\n\n"
        f"原问题：\n{question}{ref_section}\n\n"
        "请根据评分标准评分。"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_score_json(raw: str) -> dict | None:
    """从 LLM 回复中解析评分 JSON。"""
    import json
    import re

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        raw = match.group(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
