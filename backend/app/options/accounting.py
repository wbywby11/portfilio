# -*- coding: utf-8 -*-
"""
会计分录生成引擎

根据估值结果自动生成会计分录，支持：
- 日终盯市（公允价值变动）
- 敲出结算
- 到期结算
- 票息收入

科目映射可由运营通过 API 调整。
"""

from datetime import datetime
from typing import List, Dict, Optional, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from app.options.dispatcher import ValuationRecord

# ── 默认科目映射 ──────────────────────────────────────

DEFAULT_ACCOUNT_MAP = {
    "fair_value_asset": "交易性金融资产-成本",
    "accumulated_fair_value": "交易性金融资产-公允价值变动",
    "fair_value_pnl": "公允价值变动损益",
    "coupon_income": "投资收益-利息收入",
    "settlement": "银行存款",
    "receivable_coupon": "应收利息",
}


class AccountingGenerator:
    """根据估值结果自动生成会计分录"""

    def __init__(self, account_map: Optional[Dict[str, str]] = None):
        self.account_map = account_map or DEFAULT_ACCOUNT_MAP

    def _acct(self, key: str) -> str:
        """获取科目名称"""
        return self.account_map.get(key, key)

    # ══════════════════════════════════════════════════
    #  日终盯市分录
    # ══════════════════════════════════════════════════

    def generate_daily_mark(
        self,
        date_str: str,
        valuations: List['ValuationRecord'],
        prev_valuations: Optional[Dict[str, 'ValuationRecord']] = None,
        valuation_version: int = 0,
    ) -> List[dict]:
        """日终盯市分录: 公允价值变动

        对每个产品，比较今日估值与昨日估值（或本金），生成分录：
        - 估值上升: 借 交易性金融资产-公允价值变动，贷 公允价值变动损益
        - 估值下降: 借 公允价值变动损益，贷 交易性金融资产-公允价值变动
        """
        entries = []
        prev_valuations = prev_valuations or {}

        for val in valuations:
            if val.error:
                continue

            prev = prev_valuations.get(val.product_id)
            prev_price = prev.price_total if prev else val.principal
            change = round(val.price_total - prev_price, 2)

            if abs(change) < 0.01:
                continue

            if change > 0:
                # 估值上升：资产增加，损益增加
                entries.append({
                    "date": date_str,
                    "product_id": val.product_id,
                    "valuation_version": valuation_version,
                    "entry_type": "daily_mark",
                    "debit_account": self._acct("accumulated_fair_value"),
                    "credit_account": self._acct("fair_value_pnl"),
                    "amount": abs(change),
                    "description": f"{val.name} 日终盯市 估值变动 +{change:,.2f}",
                    "created_at": datetime.now(),
                })
            else:
                # 估值下降：损益减少，资产减少
                entries.append({
                    "date": date_str,
                    "product_id": val.product_id,
                    "valuation_version": valuation_version,
                    "entry_type": "daily_mark",
                    "debit_account": self._acct("fair_value_pnl"),
                    "credit_account": self._acct("accumulated_fair_value"),
                    "amount": abs(change),
                    "description": f"{val.name} 日终盯市 估值变动 {change:,.2f}",
                    "created_at": datetime.now(),
                })

        logger.info(f"[会计引擎] 日终盯市: date={date_str}, 生成分录 {len(entries)} 条")
        return entries

    # ══════════════════════════════════════════════════
    #  敲出结算分录
    # ══════════════════════════════════════════════════

    def generate_knock_out_settlement(
        self,
        date_str: str,
        product_id: str,
        product_name: str,
        settlement_amount: float,
        carrying_value: float,
        valuation_version: int = 0,
    ) -> List[dict]:
        """敲出结算分录

        敲出时产品提前终止：
        1. 结转交易性金融资产账面价值
        2. 收到结算款
        3. 差额计入投资收益
        """
        entries = []
        settlement_amount = round(settlement_amount, 2)
        carrying_value = round(carrying_value, 2)
        gain_loss = round(settlement_amount - carrying_value, 2)

        # 收到结算款
        entries.append({
            "date": date_str,
            "product_id": product_id,
            "valuation_version": valuation_version,
            "entry_type": "knock_out_settlement",
            "debit_account": self._acct("settlement"),
            "credit_account": self._acct("fair_value_asset"),
            "amount": settlement_amount,
            "description": f"{product_name} 敲出结算 收到 {settlement_amount:,.2f}",
            "created_at": datetime.now(),
        })

        # 结转公允价值变动累计额
        if abs(carrying_value - settlement_amount) > 0.01:
            entries.append({
                "date": date_str,
                "product_id": product_id,
                "valuation_version": valuation_version,
                "entry_type": "knock_out_settlement",
                "debit_account": self._acct("accumulated_fair_value") if gain_loss >= 0 else self._acct("fair_value_pnl"),
                "credit_account": self._acct("fair_value_pnl") if gain_loss >= 0 else self._acct("accumulated_fair_value"),
                "amount": abs(gain_loss),
                "description": f"{product_name} 敲出结算 结转损益 {gain_loss:+,.2f}",
                "created_at": datetime.now(),
            })

        logger.info(f"[会计引擎] 敲出结算: {product_id}, 结算={settlement_amount:,.2f}, 损益={gain_loss:+,.2f}")
        return entries

    # ══════════════════════════════════════════════════
    #  到期结算分录
    # ══════════════════════════════════════════════════

    def generate_maturity_settlement(
        self,
        date_str: str,
        product_id: str,
        product_name: str,
        settlement_amount: float,
        carrying_value: float,
        valuation_version: int = 0,
    ) -> List[dict]:
        """到期结算分录（与敲出结算逻辑相同）"""
        entries = []
        settlement_amount = round(settlement_amount, 2)
        carrying_value = round(carrying_value, 2)
        gain_loss = round(settlement_amount - carrying_value, 2)

        entries.append({
            "date": date_str,
            "product_id": product_id,
            "valuation_version": valuation_version,
            "entry_type": "maturity_settlement",
            "debit_account": self._acct("settlement"),
            "credit_account": self._acct("fair_value_asset"),
            "amount": settlement_amount,
            "description": f"{product_name} 到期结算 收到 {settlement_amount:,.2f}",
            "created_at": datetime.now(),
        })

        if abs(gain_loss) > 0.01:
            entries.append({
                "date": date_str,
                "product_id": product_id,
                "valuation_version": valuation_version,
                "entry_type": "maturity_settlement",
                "debit_account": self._acct("accumulated_fair_value") if gain_loss >= 0 else self._acct("fair_value_pnl"),
                "credit_account": self._acct("fair_value_pnl") if gain_loss >= 0 else self._acct("accumulated_fair_value"),
                "amount": abs(gain_loss),
                "description": f"{product_name} 到期结算 结转损益 {gain_loss:+,.2f}",
                "created_at": datetime.now(),
            })

        logger.info(f"[会计引擎] 到期结算: {product_id}, 结算={settlement_amount:,.2f}, 损益={gain_loss:+,.2f}")
        return entries

    # ══════════════════════════════════════════════════
    #  汇总统计
    # ══════════════════════════════════════════════════

    @staticmethod
    def summarize_by_account(entries: List[dict]) -> List[dict]:
        """按科目汇总分录"""
        summary: Dict[str, Dict[str, float]] = {}
        for e in entries:
            debit = e["debit_account"]
            credit = e["credit_account"]
            amount = e["amount"]

            if debit not in summary:
                summary[debit] = {"debit": 0.0, "credit": 0.0, "count": 0}
            summary[debit]["debit"] += amount
            summary[debit]["count"] += 1

            if credit not in summary:
                summary[credit] = {"debit": 0.0, "credit": 0.0, "count": 0}
            summary[credit]["credit"] += amount
            summary[credit]["count"] += 1

        results = []
        for account, totals in sorted(summary.items()):
            results.append({
                "account": account,
                "total_debit": round(totals["debit"], 2),
                "total_credit": round(totals["credit"], 2),
                "net": round(totals["debit"] - totals["credit"], 2),
                "count": totals["count"],
            })
        return results
