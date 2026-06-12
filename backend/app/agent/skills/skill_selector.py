"""基于用户意图匹配相关 Skills 的选择器

支持多级匹配策略:
1. trigger_keywords 精确匹配 (+1.0)
2. 同义词扩展匹配 (+0.8)
3. 模糊子串匹配 (+0.3)
4. tags 精确匹配 (+0.5)
5. tags 同义词匹配 (+0.3)
"""

import logging
from app.agent.skills.skill_loader import Skill, SkillLoader
from app.agent.skills.synonyms import expand_synonyms

logger = logging.getLogger(__name__)


class SkillSelector:
    """基于用户意图匹配相关 Skills

    使用多级匹配策略（精确 + 同义词 + 模糊），根据用户消息
    与 Skill 的 trigger_keywords 和 tags 进行评分排序。
    """

    def __init__(self, skill_loader: SkillLoader):
        self._loader = skill_loader

    def match(self, user_message: str, max_results: int = 2) -> list[Skill]:
        """匹配用户消息最相关的 Skills"""
        if not user_message or not user_message.strip():
            return []

        msg_lower = user_message.lower()
        # 预计算消息的同义词集合（避免每个 Skill 重复计算）
        msg_synonyms = expand_synonyms(msg_lower)
        scored: list[tuple[float, Skill]] = []

        for skill in self._loader.skills.values():
            try:
                score = self._calculate_score(msg_lower, msg_synonyms, skill)
                if score > 0:
                    scored.append((score, skill))
            except Exception as exc:
                logger.warning("计算 Skill [%s] 匹配分数失败: %s", skill.name, exc)

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [skill for _, skill in scored[:max_results]]

        if results:
            logger.debug(
                "匹配到 %d 个 Skills (分数: %s): %s",
                len(results),
                [(round(s, 2), sk.name) for s, sk in scored[:max_results]],
                [s.name for s in results],
            )
            for skill in results:
                logger.info("Matched skill: %s (version: %s)", skill.name, skill.version)

        return results

    @staticmethod
    def _calculate_score(msg_lower: str, msg_synonyms: set[str], skill: Skill) -> float:
        """计算单个 Skill 的匹配分数（多级匹配策略）"""
        # --- exclude_keywords 排除检查 ---
        for ek in skill.exclude_keywords:
            ek_lower = ek.lower()
            # 直接匹配
            if ek_lower in msg_lower:
                return 0
            # 同义词扩展匹配
            ek_synonyms = expand_synonyms(ek_lower)
            for exp in ek_synonyms:
                if exp in msg_lower:
                    return 0

        score = 0.0
        matched_keywords: set[str] = set()  # 防止同一关键词重复计分

        # --- trigger_keywords 匹配 ---
        for kw in skill.trigger_keywords:
            kw_lower = kw.lower()

            # 1. 精确匹配 → +1.0
            if kw_lower in msg_lower:
                score += 1.0
                matched_keywords.add(kw_lower)
                continue  # 精确命中后不再对同一关键词做同义词/模糊匹配

            # 2. 同义词扩展匹配 → +0.8（精确未命中时尝试）
            kw_synonyms = expand_synonyms(kw_lower)
            if kw_synonyms and msg_synonyms & kw_synonyms:
                score += 0.8
                matched_keywords.add(kw_lower)
                continue

            # 3. 模糊子串匹配 → +0.3（同义词也未命中时尝试）
            if SkillSelector._fuzzy_match(kw_lower, msg_lower):
                score += 0.3
                matched_keywords.add(kw_lower)

        # --- tags 匹配 ---
        for tag in skill.tags:
            tag_lower = tag.lower()
            if tag_lower in matched_keywords:
                continue  # 已作为 keyword 计分，跳过

            # 4. tags 精确匹配 → +0.5
            if tag_lower in msg_lower:
                score += 0.5
                continue

            # 5. tags 同义词匹配 → +0.3
            tag_synonyms = expand_synonyms(tag_lower)
            if tag_synonyms and msg_synonyms & tag_synonyms:
                score += 0.3

        return score

    @staticmethod
    def _fuzzy_match(keyword: str, text: str, threshold: float = 0.6) -> bool:
        """基于字符重叠率的模糊匹配（零外部依赖）

        计算 keyword 中的字符在 text 中出现的比例。
        适用于处理部分匹配场景（如"配"匹配"配置方案"）。

        Args:
            keyword: 关键词
            text: 待匹配文本
            threshold: 匹配阈值（0-1），默认 0.6

        Returns:
            是否达到模糊匹配阈值
        """
        if len(keyword) <= 1:
            return False  # 单字符不做模糊匹配，避免误匹配

        # 计算 keyword 字符在 text 中的覆盖率
        matched_chars = sum(1 for ch in keyword if ch in text)
        overlap = matched_chars / len(keyword)
        return overlap >= threshold
