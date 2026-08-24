"""截面多空资产选择器.

从 trend_cross_sectional.py._cross_sectional() 提取的截面多空选择逻辑：
- 计算多窗口累计动量
- 做多排名前 50%，做空排名后 50%
- 多空内部各自波动率倒数加权，归一化到 +-0.5
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult


@lru_cache(maxsize=4)
def _parse_signal_calendar(dates: tuple) -> pd.DatetimeIndex:
    """解析自定义信号日历（ISO 字符串元组），进程级缓存避免逐日重复解析."""
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna()
    return idx.sort_values().unique()


class CrossSectionalLongShortSelector(BaseAssetSelector):
    """截面多空选择器：动量排序 -> 做多前50% + 做空后50%.

    核心特点：
    - 截面动量排序，做多前 50%，做空后 50%
    - 多空内部各自波动率倒数加权
    - 归一化到 +-0.5
    月末信号锁定（GMSI 2.0 原型口径）：信号取最近一个已生效月末交易日
      的动量排名与 inv_vol，月内多次调用信号不变，避免每日重算导致的
      高频换手（inv_vol 用信号日当日值，防泄露）。
    - 自定义信号日历（signal_calendar_dates）：月末在自带交易日表上识别
      （对齐原型 _build_rebalance_schedule 口径）；生效日在信号日历上计数
      （原型 T+delay+1），引擎注入完整行情日历（price_calendar_dates）时
      精确判定生效日就绪（生效日须为价格交易日，否则回退上月，对齐原型
      跳月语义）；信号日不在价格索引时同样回退上月。
    
    参数:
        cs_lookback_months: 截面动量窗口（月，默认 8）
        signal_calendar_dates: 自定义信号日历（ISO 字符串列表，可选）
        price_calendar_dates: 完整行情日历（ISO 字符串元组，引擎注入，可选）
    """

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "cross_sectional_long_short",
            "display_name": "截面多空",
            "description": "基于截面动量排序的多空选择器，做多前50%做空后50%",
            "params": [
                {
                    "name": "cs_lookback_months",
                    "label": "截面动量窗口(月)",
                    "type": "number",
                    "default": 8,
                    "min_value": 1,
                    "max_value": 24,
                    "step": 1,
                    "description": "截面动量排序窗口（月，GMSI 2.0 对齐口径默认 8）",
                },
                {
                    "name": "cs_execution_delay",
                    "label": "截面信号执行延迟(交易日)",
                    "type": "number",
                    "default": 2,
                    "min_value": 0,
                    "max_value": 5,
                    "step": 1,
                    "description": "信号日后在信号日历上计数的延迟交易日数，"
                                   "信号日 T+delay+1 生效；配置信号日历时生效日须为"
                                   "价格交易日，否则回退上月（GMSI 2.0 对齐口径配 1，"
                                   "即月末信号 T+2 生效）",
                },
            ],
        }

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params,
    ) -> SelectionResult:
        """执行截面多空选择.

        Args:
            prices: 候选资产价格矩阵
            n_assets: 不使用（自动按 50/50 分割）
            **params:
                - cs_lookback_months: 动量窗口月数（默认 8）

        Returns:
            SelectionResult: 选择结果（tags 为 long/short）
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        cs_lookback_months = int(params.get("cs_lookback_months", 8))
        lookback_days = cs_lookback_months * 21
        returns = prices.pct_change(fill_method=None)

        # 过去 N 月累计收益（向量化：Π(1+r)-1 ≡ expm1(Σln(1+r))）
        momentum = np.expm1(
            np.log1p(returns).rolling(lookback_days, min_periods=lookback_days).sum()
        )

        # 波动率倒数
        vol = returns.rolling(20, min_periods=10).std()
        inv_vol = 1.0 / vol.replace(0, np.nan).replace(np.inf, np.nan).fillna(1.0)

        # 信号行定位（月末信号锁定）：
        # 默认口径：月末交易日 = 下一行属于下一个月的行；最后一行无法确认
        # 是否月末，不参与。信号需满足“至少已过 cs_execution_delay 个交易日”
        # （原型月末信号 T+2 生效），保证月内任意调用日取到的都是同一个
        # 已生效的月末信号。
        # 日历口径：提供 signal_calendar_dates 时，月末在自定义日历上识别；
        # 原型信号日在自带交易日表上数 T+(delay+1) 为生效日 E（须在价格日历内，
        # 否则跳月），引擎在 E 前一个交易日收盘成交、新权重自 E 承接收益，
        # 故当前窗口到达 E-1（或已含 E）即可用。
        idx = prices.index
        n_rows = len(idx)
        cs_exec_delay = int(params.get("cs_execution_delay", 2))
        signal_pos = None

        calendar_raw = params.get("signal_calendar_dates")
        if isinstance(calendar_raw, (list, tuple)) and calendar_raw and n_rows >= 2:
            calendar = _parse_signal_calendar(tuple(calendar_raw))
            # 月末 = 自定义日历按年月分组取每月最后一天
            ym_cal = calendar.to_period("M")
            month_ends = pd.DatetimeIndex(
                pd.Series(calendar, index=calendar).groupby(ym_cal).last().values
            )
            pos_map = {ts: i for i, ts in enumerate(idx)}
            cal_pos = {ts: i for i, ts in enumerate(calendar)}
            # 完整行情日历（引擎注入）：生效日在信号日历上计数（原型
            # td_sorted[pos+delay+1] 口径），生效日须为真实价格交易日
            # （否则原型跳月），就绪日 = 生效日前一个价格交易日
            price_cal_raw = params.get("price_calendar_dates")
            price_cal = (
                _parse_signal_calendar(tuple(price_cal_raw))
                if isinstance(price_cal_raw, (list, tuple)) and price_cal_raw
                else None
            )
            # 自最近月末倒序找第一个已生效信号；信号日不在价格索引、
            # 或生效日不在价格日历（原型跳月语义）则回退上月
            for sig_ts in month_ends[::-1]:
                sp = cal_pos.get(sig_ts)
                if sp is None or sig_ts not in pos_map:
                    continue
                if sp + cs_exec_delay + 1 >= len(calendar):
                    continue
                exec_ts = calendar[sp + cs_exec_delay + 1]
                if price_cal is not None:
                    # 精确口径：生效日非价格交易日→原型跳月，回退上月；
                    # 就绪日 = 生效日前一个价格交易日，窗口末行到达就绪日
                    # 即可用（引擎在就绪日收盘成交、新权重自生效日承接收益）
                    pp = price_cal.searchsorted(exec_ts)
                    if pp >= len(price_cal) or price_cal[pp] != exec_ts:
                        continue
                    if pp == 0:
                        continue
                    if idx[-1] >= price_cal[pp - 1]:
                        signal_pos = pos_map[sig_ts]
                        break
                    continue
                ep = pos_map.get(exec_ts)
                if ep is None:
                    # 无行情日历时的近似口径：窗口末行到达信号日历上
                    # E 前一交易日（含）即可用；价格日历可能含信号日历之外
                    # 的真实交易日（原型交易日表不完备），故用 >= 而非 ==
                    if sp + cs_exec_delay >= 1 and idx[-1] >= calendar[sp + cs_exec_delay]:
                        signal_pos = pos_map[sig_ts]
                        break
                    continue
                if ep <= n_rows - 1:
                    # E 已在窗口内：ready = E 前一交易日（窗口必然含该行）
                    signal_pos = pos_map[sig_ts]
                    break

        if signal_pos is None:
            months = idx.to_period("M")
            if n_rows >= 2:
                me_mask = np.zeros(n_rows, dtype=bool)
                me_mask[:-1] = months[:-1].values != months[1:].values
                latest_eligible = n_rows - 1 - cs_exec_delay
                candidates = np.where(me_mask)[0]
                candidates = candidates[candidates <= latest_eligible]
                signal_pos = int(candidates[-1]) if len(candidates) > 0 else n_rows - 1
            else:
                signal_pos = n_rows - 1

        # 使用信号行的动量分数（信号日 inv_vol 同步取用，避免信息泄露）
        latest_momentum = momentum.iloc[signal_pos]
        valid_momentum = latest_momentum.dropna()

        if len(valid_momentum) < 2:
            # 数据不足，返回空
            return SelectionResult(
                selected_assets=[],
                scores={},
                ranking=pd.DataFrame(),
                timestamp=pd.Timestamp.now().isoformat(),
                selector_type="cross_sectional_long_short",
                params=params,
                tags={},
            )

        # 排序：做多前 50%，做空后 50%
        sorted_assets = valid_momentum.sort_values(ascending=False)
        n_total = len(sorted_assets)
        n_long = max(1, int(n_total * 0.5))
        n_short = max(1, int(n_total * 0.5))
        long_assets = sorted_assets.index[:n_long].tolist()
        short_assets = sorted_assets.index[-n_short:].tolist()

        # 波动率倒数加权归一化到 +-0.5（信号日口径）
        latest_inv_vol = inv_vol.iloc[signal_pos]
        weights = pd.Series(0.0, index=prices.columns)

        # 多头权重
        if long_assets:
            w_long = latest_inv_vol.reindex(long_assets).fillna(0)
            w_long_sum = w_long.sum()
            if w_long_sum > 0:
                for a in long_assets:
                    weights[a] = w_long.get(a, 0) / w_long_sum * 0.5
            else:
                for a in long_assets:
                    weights[a] = 0.5 / len(long_assets)

        # 空头权重
        if short_assets:
            w_short = latest_inv_vol.reindex(short_assets).fillna(0)
            w_short_sum = w_short.sum()
            if w_short_sum > 0:
                for a in short_assets:
                    weights[a] = -w_short.get(a, 0) / w_short_sum * 0.5
            else:
                for a in short_assets:
                    weights[a] = -0.5 / len(short_assets)

        # 构造结果
        selected = long_assets + short_assets
        scores = weights.to_dict()
        tags = {}
        for a in prices.columns:
            if a in long_assets:
                tags[a] = "long"
            elif a in short_assets:
                tags[a] = "short"
            else:
                tags[a] = "neutral"

        ranking = pd.DataFrame({
            "Asset": sorted_assets.index,
            "MomentumScore": sorted_assets.values,
            "Direction": ["long" if a in long_assets else "short" for a in sorted_assets.index],
        }).set_index("Asset")

        return SelectionResult(
            selected_assets=selected,
            scores=scores,
            ranking=ranking,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="cross_sectional_long_short",
            params=params,
            tags=tags,
        )
