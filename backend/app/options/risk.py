"""
风险分析模块

包含：
- ScenarioAnalyzer: 情景分析（市场冲击下的估值变化）
- StressTester: 压力测试（极端场景）
- PnLAttributor: P&L 归因（分解每日估值变化）
- RiskReportGenerator: 整合风险报告
"""

import json
from dataclasses import dataclass, asdict
from datetime import date
from typing import List, Dict, Optional, TYPE_CHECKING
from pathlib import Path

import numpy as np

from app.options.config import RISK_DIR

if TYPE_CHECKING:
    from app.options.data_loader import ProductRecord, MarketDataRecord
    from app.options.dispatcher import ValuationRecord, PricingDispatcher


# ── 情景分析 ──────────────────────────────────────────

class ScenarioAnalyzer:
    """情景分析：对产品组合施加市场冲击，计算估值变化"""

    # 标准情景矩阵
    DEFAULT_SCENARIOS = {
        "spot_+5%":  {"spot_shock":  0.05, "vol_shock": 0.0, "rate_shock": 0.0},
        "spot_+10%": {"spot_shock":  0.10, "vol_shock": 0.0, "rate_shock": 0.0},
        "spot_+20%": {"spot_shock":  0.20, "vol_shock": 0.0, "rate_shock": 0.0},
        "spot_-5%":  {"spot_shock": -0.05, "vol_shock": 0.0, "rate_shock": 0.0},
        "spot_-10%": {"spot_shock": -0.10, "vol_shock": 0.0, "rate_shock": 0.0},
        "spot_-20%": {"spot_shock": -0.20, "vol_shock": 0.0, "rate_shock": 0.0},
        "vol_+10%":  {"spot_shock":  0.0,  "vol_shock": 0.10, "rate_shock": 0.0},
        "vol_+20%":  {"spot_shock":  0.0,  "vol_shock": 0.20, "rate_shock": 0.0},
        "vol_-10%":  {"spot_shock":  0.0,  "vol_shock": -0.10, "rate_shock": 0.0},
        "vol_-20%":  {"spot_shock":  0.0,  "vol_shock": -0.20, "rate_shock": 0.0},
        "spot_-10%_vol_+20%": {"spot_shock": -0.10, "vol_shock": 0.20, "rate_shock": 0.0},
    }

    def run(self, products: List['ProductRecord'],
            market_data: Dict[str, 'MarketDataRecord'],
            dispatcher: 'PricingDispatcher',
            base_records: List['ValuationRecord'],
            scenarios: Dict = None,
            vol_surfaces: Optional[Dict] = None) -> dict:
        """运行情景分析

        Args:
            products: 产品列表
            market_data: 市场数据
            dispatcher: 定价派发器
            base_records: 基准估值结果
            scenarios: 自定义情景（默认使用 DEFAULT_SCENARIOS）
            vol_surfaces: 波动率曲面字典 {underlying: VolSurface}

        Returns:
            dict: {scenario_name: {product_id: {price, change, change_pct}}}
        """
        scenarios = scenarios or self.DEFAULT_SCENARIOS
        results = {}

        # 构建基准价格字典
        base_prices = {r.product_id: r.price_total for r in base_records}

        for scenario_name, shocks in scenarios.items():
            scenario_results = {}

            # 创建 shocked market data
            shocked_market = self._apply_shocks(market_data, shocks)

            # 对每个产品重新定价
            for prod in products:
                market = shocked_market.get(prod.underlying)
                if market is None:
                    continue

                vs = (vol_surfaces or {}).get(prod.underlying)
                rec = dispatcher.price_product(prod, market, vol_surface=vs)
                base_price = base_prices.get(prod.id, 0)
                change = rec.price_total - base_price
                change_pct = (change / base_price * 100) if base_price > 0 else 0

                scenario_results[prod.id] = {
                    "price": rec.price_total,
                    "change": change,
                    "change_pct": change_pct,
                }

            # 组合汇总
            total_base = sum(base_prices.values())
            total_scenario = sum(r["price"] for r in scenario_results.values())
            scenario_results["_portfolio"] = {
                "price": total_scenario,
                "change": total_scenario - total_base,
                "change_pct": ((total_scenario - total_base) / total_base * 100) if total_base > 0 else 0,
            }

            results[scenario_name] = scenario_results

        return results

    def _apply_shocks(self, market_data: Dict[str, 'MarketDataRecord'],
                      shocks: dict) -> Dict[str, 'MarketDataRecord']:
        """对市场数据施加冲击"""
        from copy import deepcopy
        shocked = {}

        for underlying, market in market_data.items():
            new_market = deepcopy(market)

            # Spot 冲击
            spot_shock = shocks.get("spot_shock", 0)
            new_market.spot *= (1 + spot_shock)

            # Vol 冲击
            vol_shock = shocks.get("vol_shock", 0)
            for tenor in new_market.vols:
                new_market.vols[tenor] *= (1 + vol_shock)

            # Rate 冲击（同时更新利率曲线和 rate_1y）
            rate_shock = shocks.get("rate_shock", 0)
            new_market.rate_1y += rate_shock
            for tenor in new_market.rates:
                new_market.rates[tenor] += rate_shock

            shocked[underlying] = new_market

        return shocked

    def print_report(self, results: dict, base_records: List['ValuationRecord']):
        """打印情景分析报告"""
        print("\n" + "=" * 80)
        print("  情景分析报告")
        print("=" * 80)

        # 选择几个关键情景显示
        key_scenarios = ["spot_+10%", "spot_-10%", "vol_+20%", "vol_-20%", "spot_-10%_vol_+20%"]
        headers = ["产品"] + key_scenarios

        # 表头
        header_line = f"{'产品':<15}"
        for s in key_scenarios:
            header_line += f"  {s:>12}"
        print(header_line)
        print("-" * 80)

        # 产品行
        base_prices = {r.product_id: r.price_total for r in base_records}
        for r in base_records:
            line = f"{r.product_id:<15}"
            for s in key_scenarios:
                if s in results and r.product_id in results[s]:
                    change_pct = results[s][r.product_id]["change_pct"]
                    line += f"  {change_pct:>11.1f}%"
                else:
                    line += f"  {'N/A':>12}"
            print(line)

        # 组合行
        print("-" * 80)
        line = f"{'组合总计':<15}"
        for s in key_scenarios:
            if s in results and "_portfolio" in results[s]:
                change_pct = results[s]["_portfolio"]["change_pct"]
                line += f"  {change_pct:>11.1f}%"
            else:
                line += f"  {'N/A':>12}"
        print(line)


# ── 压力测试 ──────────────────────────────────────────

class StressTester:
    """压力测试：极端市场条件下的估值冲击"""

    PRESET_SCENARIOS = {
        "2008_financial_crisis": {
            "description": "2008式崩盘：标的-40%，波动率+100%",
            "spot_shock": -0.40, "vol_shock": 1.00, "rate_shock": -0.01,
        },
        "flash_crash": {
            "description": "闪崩：标的-20%，波动率+50%",
            "spot_shock": -0.20, "vol_shock": 0.50, "rate_shock": 0.0,
        },
        "rate_hike": {
            "description": "加息冲击：利率+200bp",
            "spot_shock": 0.0, "vol_shock": 0.0, "rate_shock": 0.02,
        },
        "vol_spike": {
            "description": "波动率飙升：vol+80%",
            "spot_shock": 0.0, "vol_shock": 0.80, "rate_shock": 0.0,
        },
        "market_rally": {
            "description": "市场大涨：标的+30%，波动率-20%",
            "spot_shock": 0.30, "vol_shock": -0.20, "rate_shock": 0.0,
        },
    }

    def run(self, products: List['ProductRecord'],
            market_data: Dict[str, 'MarketDataRecord'],
            dispatcher: 'PricingDispatcher',
            base_records: List['ValuationRecord'],
            scenarios: Dict = None,
            vol_surfaces: Optional[Dict] = None) -> dict:
        """运行压力测试"""
        analyzer = ScenarioAnalyzer()
        scenarios = scenarios or self.PRESET_SCENARIOS
        return analyzer.run(products, market_data, dispatcher, base_records, scenarios, vol_surfaces=vol_surfaces)

    def print_report(self, results: dict, base_records: List['ValuationRecord']):
        """打印压力测试报告"""
        print("\n" + "=" * 80)
        print("  压力测试报告")
        print("=" * 80)

        scenarios = list(self.PRESET_SCENARIOS.keys())
        descriptions = {k: v["description"] for k, v in self.PRESET_SCENARIOS.items()}

        # 表头
        header_line = f"{'产品':<15}"
        for s in scenarios:
            short_name = s.replace("_", " ")[:12]
            header_line += f"  {short_name:>12}"
        print(header_line)
        print("-" * 80)

        # 产品行
        for r in base_records:
            line = f"{r.product_id:<15}"
            for s in scenarios:
                if s in results and r.product_id in results[s]:
                    change_pct = results[s][r.product_id]["change_pct"]
                    line += f"  {change_pct:>11.1f}%"
                else:
                    line += f"  {'N/A':>12}"
            print(line)

        # 组合行
        print("-" * 80)
        line = f"{'组合总计':<15}"
        for s in scenarios:
            if s in results and "_portfolio" in results[s]:
                change = results[s]["_portfolio"]["change"]
                line += f"  {change/10000:>11.1f}万"
            else:
                line += f"  {'N/A':>12}"
        print(line)

        # 场景描述
        print("\n场景说明：")
        for s, desc in descriptions.items():
            print(f"  {s}: {desc}")


# ── P&L 归因 ──────────────────────────────────────────

class PnLAttributor:
    """P&L 归因：分解 T 日 vs T-1 日估值变化"""

    def attribute(self, rec_today: 'ValuationRecord',
                  rec_yesterday: 'ValuationRecord',
                  spot_today: float, spot_yesterday: float,
                  vol_today: float, vol_yesterday: float) -> dict:
        """计算 P&L 归因

        分解公式：
            Delta_PnL = delta * (S_today - S_yesterday)
            Vega_PnL  = vega  * (vol_today - vol_yesterday) * 100
            Theta_PnL = theta * 1  (一天衰减)
            Residual  = total_change - Delta_PnL - Vega_PnL - Theta_PnL

        Args:
            rec_today: T 日估值记录
            rec_yesterday: T-1 日估值记录
            spot_today: T 日标的价格
            spot_yesterday: T-1 日标的价格
            vol_today: T 日波动率
            vol_yesterday: T-1 日波动率

        Returns:
            dict: {total_change, delta_pnl, vega_pnl, theta_pnl, residual}
        """
        total_change = rec_today.price_total - rec_yesterday.price_total

        # Delta 贡献（使用 T-1 日的 delta）
        delta_pnl = rec_yesterday.delta * (spot_today - spot_yesterday)

        # Vega 贡献（使用 T-1 日的 vega，vol 以小数计）
        vega_pnl = rec_yesterday.vega * (vol_today - vol_yesterday) * 100

        # Theta 贡献（一天衰减）
        theta_pnl = rec_yesterday.theta

        # 残差（未被 Greeks 解释的部分）
        residual = total_change - delta_pnl - vega_pnl - theta_pnl

        return {
            "product_id": rec_today.product_id,
            "total_change": total_change,
            "delta_pnl": delta_pnl,
            "vega_pnl": vega_pnl,
            "theta_pnl": theta_pnl,
            "residual": residual,
            "spot_change": spot_today - spot_yesterday,
            "vol_change": vol_today - vol_yesterday,
        }

    def print_report(self, attributions: List[dict]):
        """打印 P&L 归因报告"""
        print("\n" + "=" * 80)
        print("  P&L 归因分析")
        print("=" * 80)

        # 表头
        print(f"{'产品':<12} {'总变化':>10} {'Delta':>10} {'Vega':>10} {'Theta':>10} {'残差':>10}")
        print("-" * 80)

        for attr in attributions:
            print(f"{attr['product_id']:<12} "
                  f"{attr['total_change']:>10,.0f} "
                  f"{attr['delta_pnl']:>10,.0f} "
                  f"{attr['vega_pnl']:>10,.0f} "
                  f"{attr['theta_pnl']:>10,.0f} "
                  f"{attr['residual']:>10,.0f}")


# ── 风险报告生成器 ──────────────────────────────────

class RiskReportGenerator:
    """风险报告生成器：整合情景+压力+P&L"""

    def __init__(self):
        self.scenario_analyzer = ScenarioAnalyzer()
        self.stress_tester = StressTester()
        self.pnl_attributor = PnLAttributor()

    def generate(self, val_date: date,
                 products: List['ProductRecord'],
                 market_data: Dict[str, 'MarketDataRecord'],
                 dispatcher: 'PricingDispatcher',
                 base_records: List['ValuationRecord'],
                 prev_records: Optional[List['ValuationRecord']] = None,
                 prev_market_data: Optional[Dict[str, 'MarketDataRecord']] = None,
                 run_scenario: bool = True,
                 run_stress: bool = True,
                 run_pnl: bool = True,
                 vol_surfaces: Optional[Dict] = None) -> dict:
        """生成完整风险报告

        Args:
            val_date: 估值日期
            products: 产品列表
            market_data: 当日市场数据
            dispatcher: 定价派发器
            base_records: 基准估值结果
            prev_records: 前一日估值记录（P&L 归因用）
            prev_market_data: 前一日市场数据（P&L 归因用）
            run_scenario: 是否运行情景分析
            run_stress: 是否运行压力测试
            run_pnl: 是否运行 P&L 归因

        Returns:
            dict: 完整风险报告
        """
        report = {
            "date": val_date.isoformat(),
            "generated_at": date.today().isoformat(),
            "scenario": None,
            "stress": None,
            "pnl": None,
        }

        # 情景分析
        if run_scenario:
            scenario_results = self.scenario_analyzer.run(
                products, market_data, dispatcher, base_records,
                vol_surfaces=vol_surfaces
            )
            report["scenario"] = scenario_results
            self.scenario_analyzer.print_report(scenario_results, base_records)

        # 压力测试
        if run_stress:
            stress_results = self.stress_tester.run(
                products, market_data, dispatcher, base_records,
                vol_surfaces=vol_surfaces
            )
            report["stress"] = stress_results
            self.stress_tester.print_report(stress_results, base_records)

        # P&L 归因
        if run_pnl and prev_records and prev_market_data:
            attributions = []
            prev_dict = {r.product_id: r for r in prev_records}

            for rec_today in base_records:
                rec_yesterday = prev_dict.get(rec_today.product_id)
                if not rec_yesterday:
                    continue

                # 获取市场数据
                market_today = market_data.get(rec_today.underlying)
                market_yesterday = prev_market_data.get(rec_today.underlying)
                if not market_today or not market_yesterday:
                    continue

                attr = self.pnl_attributor.attribute(
                    rec_today, rec_yesterday,
                    market_today.spot, market_yesterday.spot,
                    rec_today.vol, rec_yesterday.vol,
                )
                attributions.append(attr)

            report["pnl"] = attributions
            if attributions:
                self.pnl_attributor.print_report(attributions)

        # 保存 JSON 报告
        self._save_report(val_date, report)

        return report

    def _save_report(self, val_date: date, report: dict):
        """保存风险报告到 JSON"""
        path = RISK_DIR / f"{val_date.isoformat()}.json"
        # 转换 numpy 类型为 Python 原生类型
        def convert(obj):
            if isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=convert)
        print(f"\n💾 风险报告已保存: {path}")
