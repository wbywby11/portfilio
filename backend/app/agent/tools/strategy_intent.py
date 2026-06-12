"""策略意图分类器

根据用户自然语言消息，识别其投资策略意图，并返回候选策略类型。
分类来源包含两层：
1. 通用意图模式（硬编码关键词）：与具体策略无关的投资风格匹配
2. 策略专属关键词（来自知识库 YAML intent_keywords）：通过 StrategyKnowledgeBase 动态读取
"""

from loguru import logger

# ---------- 通用意图模式 ----------
GENERIC_INTENT_PATTERNS: dict[str, list[str]] = {
    "risk_averse":        ["稳健", "保守", "低风险", "不要亏", "安全", "少亏", "防守"],
    "return_seeking":     ["高收益", "最大化收益", "赚钱", "超额收益", "最大收益", "进取", "激进", "增强"],
    "tactical_rotation":  ["轮动", "动量", "定期调仓", "切换", "择时", "动态"],
    "view_blending":      ["观点", "主观判断", "我认为", "看好", "看空", "预期"],
    "risk_balanced":      ["平衡风险", "等风险", "分散", "均衡", "风险均衡"],
    "volatility_control": ["控制波动", "目标波动率", "风险限额", "波动率控制"],
    "passive_hold":       ["长期持有", "固定权重", "等权", "买入持有", "不动"],
    "data_inquiry":       ["查看", "查询", "了解", "数据", "表现", "收益率", "波动率", "走势", "行情"],
    "quick_comparison":   ["对比", "比较", "哪个好", "对比一下", "pk", "对比表现"],
}

# ---------- 通用意图 -> 策略类型映射（兜底） ----------
INTENT_STRATEGY_MAP: dict[str, list[str]] = {
    "risk_averse":        ["risk_parity", "risk_budget_target_vol", "risk_budget"],
    "return_seeking":     ["mean_variance", "factor_rp", "cso"],
    "tactical_rotation":  ["etf_cycle_rotation"],
    "view_blending":      ["black_litterman"],
    "risk_balanced":      ["risk_parity", "risk_budget"],
    "volatility_control": ["risk_budget_target_vol"],
    "passive_hold":       ["manual_allocation", "risk_parity"],
    "data_inquiry":       [],  # 数据查询不直接推荐策略
    "quick_comparison":   [],  # 对比意图不直接推荐策略
}


def classify_intent(user_message: str, knowledge_base=None) -> list[dict]:
    """分类用户策略意图，合并通用模式和知识库 intent_keywords 结果。

    Args:
        user_message: 用户原始消息文本
        knowledge_base: StrategyKnowledgeBase 实例（可选）

    Returns:
        list[dict]，每个 dict 包含：
        - intent: str  意图类型
        - score: float 匹配分数 0-1
        - candidates: list[str]  候选策略类型列表
    """
    from app.agent.skills.synonyms import expand_synonyms

    # 1. 扩展同义词
    expanded: set[str] = expand_synonyms(user_message)
    search_text = user_message.lower()
    logger.debug(f"意图分类 | 原始消息: {user_message[:80]} | 扩展词数: {len(expanded)}")

    results: list[dict] = []

    # 2. 通用意图模式匹配
    for intent, keywords in GENERIC_INTENT_PATTERNS.items():
        hit_count = sum(
            1 for kw in keywords
            if kw in search_text or kw in expanded
        )
        if hit_count > 0:
            score = round(hit_count / len(keywords), 3)
            candidates = INTENT_STRATEGY_MAP.get(intent, [])
            results.append({
                "intent": intent,
                "score": score,
                "candidates": list(candidates),
            })
            logger.debug(f"通用意图命中 | {intent} score={score} candidates={candidates}")

    # 3. 知识库维度匹配
    if knowledge_base is not None:
        expanded_list = list(expanded | {search_text})
        try:
            kb_scores: dict[str, float] = knowledge_base.get_intent_candidates(expanded_list)
            for strategy_type, score in kb_scores.items():
                results.append({
                    "intent": f"kb_{strategy_type}",
                    "score": score,
                    "candidates": [strategy_type],
                })
                logger.debug(f"知识库意图命中 | {strategy_type} score={score}")
        except Exception as e:
            logger.warning(f"知识库意图匹配异常: {e}")

    # 4. 去重（同一 intent 保留最高分）并按 score 降序排列
    merged: dict[str, dict] = {}
    for item in results:
        key = item["intent"]
        if key not in merged or item["score"] > merged[key]["score"]:
            merged[key] = item

    sorted_results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    logger.info(f"意图分类完成 | 共 {len(sorted_results)} 个意图命中")
    return sorted_results


def get_top_candidates(user_message: str, knowledge_base=None, top_n: int = 5) -> list[str]:
    """快捷方法：返回按综合分数排序的 top_n 策略类型列表。

    合并通用意图和知识库两个维度的候选策略，按出现频次和分数加权排序。

    Args:
        user_message: 用户原始消息文本
        knowledge_base: StrategyKnowledgeBase 实例（可选）
        top_n: 返回前 N 个策略类型，默认 5

    Returns:
        策略类型字符串列表，按加权分数降序
    """
    intents = classify_intent(user_message, knowledge_base=knowledge_base)

    # 对每个候选策略进行加权计分：score * 出现次数
    candidate_scores: dict[str, float] = {}
    for item in intents:
        score = item["score"]
        for c in item["candidates"]:
            candidate_scores[c] = candidate_scores.get(c, 0.0) + score

    # 按加权分降序排列
    ranked = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
    top = [name for name, _ in ranked[:top_n]]
    logger.debug(f"Top candidates | {top}")
    return top
