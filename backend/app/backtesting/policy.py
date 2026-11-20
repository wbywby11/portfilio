# -*- coding: utf-8 -*-
"""执行口径的唯一可哈希描述（ExecutionPolicy）。

回测与监控是两次独立运行，各自的成本参数来自不同的组装路径：

- 回测：``BacktestConfig.commission_rate`` / ``slippage``，外加策略自述的
  ``get_trading_costs(params)`` 回填到 ``commission_by_code``
  （见 ``runner._apply_trading_costs``）
- 监控：``PortfolioTracker.trading_cost`` 经 ``resolve_cost_of`` 变成
  ``cost_of`` 回调；而 ``configure()`` 把它固定置空，即通用监控是 gross 口径

两条路径对同一份策略参数可以产出不同的有效费率，NAV 于是逐日分叉，而分叉
原因藏在配置里、不出现在任何数值断言中。本模块把参与成交计算的参数收进一个
可哈希对象，使「这次运行到底按什么口径成交」变成一个能落库、能比对、能打印
的事实。

关于是否强制一致：**不强制**。``dividend_garp.get_trading_costs`` 的文档已经
写明「系统通用监控固定 gross 口径，不在本策略中改写」——gross 监控是有意设计
（实盘费率体系未建立前先不计费），拒绝启动只会让人绕过校验。因此本模块的用途
是让差异显式可归因：:meth:`ExecutionPolicy.diff` 输出人话级字段差异，
:meth:`ExecutionPolicy.is_cost_equivalent` 给出「逐资产有效费率是否相等」这一
真正决定 NAV 是否分叉的判据，供 parity 报告在首行就指出根因。
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: 成交口径：net = 计入交易成本，gross = 不计成本
COST_BASIS_NET = "net"
COST_BASIS_GROSS = "gross"

#: FillModel 标识（与 app.backtesting.fills 的两个实现对应）
FILL_CLOSE = "close"          # 回测：增量成交，成本从 cash 扣
FILL_REBALANCE = "rebalance"  # 监控：扣费后按目标权重重建，成本从 nav 扣

#: 哨兵资产名：代表「任何未被显式声明费率的资产」。
#: ``commission_rate`` / ``slippage`` 是扁平费率，对全部资产生效；若只比对
#: 两侧显式声明过的代码，则「一侧按统一费率计费、另一侧不计费」这一最常见
#: 的口径差异会因为并集为空而判成等价。比对时始终把本哨兵计入资产全集，
#: ``effective_cost_of`` 对它返回的就是各自的默认费率。
UNDECLARED_ASSET = "<undeclared>"


def _freeze_rate_map(rates: Optional[Dict[str, float]]) -> Tuple[Tuple[str, float], ...]:
    """费率表 → 排序元组，使 hash 与字典插入顺序无关。"""
    if not rates:
        return ()
    return tuple(
        (str(code), float(rate))
        for code, rate in sorted((str(k), float(v)) for k, v in rates.items())
    )


@dataclass(frozen=True)
class ExecutionPolicy:
    """一次运行实际生效的执行口径。

    字段全部可 JSON 序列化，可直接落库；``frozen=True`` 使实例可哈希、
    不可就地篡改（口径在运行中途被改是最难查的一类分叉）。
    """

    fill_model: str = FILL_CLOSE
    commission_rate: float = 0.0
    slippage: float = 0.0
    #: 回测侧分资产费率（策略 get_trading_costs 声明）
    commission_by_code: Tuple[Tuple[str, float], ...] = ()
    #: 监控侧分资产费率（PortfolioTracker.trading_cost）
    cost_by_asset: Tuple[Tuple[str, float], ...] = ()
    rebalance_freq: str = ""
    execution_delay: Optional[int] = None
    target_vol: Optional[float] = None
    cost_basis: str = COST_BASIS_GROSS
    #: 口径来源说明（如 "backtest_config" / "monitor_tracker"），仅用于报告
    source: str = ""

    # ------------------------------------------------------------------
    # 有效费率
    # ------------------------------------------------------------------

    def effective_cost_of(self, asset: str) -> float:
        """该资产实际生效的总费率。

        公式与成交代码逐行对齐：``CloseFill`` 与 ``ExecutionEngine`` 都按
        ``commission_by_code.get(code, commission_rate) + slippage`` 计费；
        ``RebalanceFill`` 走 ``resolve_cost_of(cost_by_asset)``，即
        ``cost_by_asset.get(code, 0.0)``。
        """
        code = str(asset)
        if self.fill_model == FILL_REBALANCE:
            return dict(self.cost_by_asset).get(code, 0.0)
        by_code = dict(self.commission_by_code)
        return by_code.get(code, self.commission_rate) + self.slippage

    def costed_assets(self) -> List[str]:
        """有效费率非零的资产（含默认费率覆盖的情形），按代码排序。"""
        by_code = dict(self.commission_by_code) or dict(self.cost_by_asset)
        candidates = set(by_code.keys())
        # 默认费率非零时对所有资产生效，但资产全集不在本对象职责内，
        # 此处只报告显式声明过的代码
        return sorted(a for a in candidates if self.effective_cost_of(a) > 0)

    # ------------------------------------------------------------------
    # 序列化与指纹
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """转为可落库字典（费率表还原为 dict，便于人读与前端展示）。"""
        return {
            "fill_model": self.fill_model,
            "commission_rate": self.commission_rate,
            "slippage": self.slippage,
            "commission_by_code": dict(self.commission_by_code),
            "cost_by_asset": dict(self.cost_by_asset),
            "rebalance_freq": self.rebalance_freq,
            "execution_delay": self.execution_delay,
            "target_vol": self.target_vol,
            "cost_basis": self.cost_basis,
            "source": self.source,
            "policy_hash": self.policy_hash(),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionPolicy":
        """从落库字典还原；``data`` 为空时返回全零 gross 口径。"""
        if not data:
            return cls()
        return cls(
            fill_model=str(data.get("fill_model") or FILL_CLOSE),
            commission_rate=float(data.get("commission_rate") or 0.0),
            slippage=float(data.get("slippage") or 0.0),
            commission_by_code=_freeze_rate_map(data.get("commission_by_code")),
            cost_by_asset=_freeze_rate_map(data.get("cost_by_asset")),
            rebalance_freq=str(data.get("rebalance_freq") or ""),
            execution_delay=(
                int(data["execution_delay"])
                if data.get("execution_delay") is not None else None
            ),
            target_vol=(
                float(data["target_vol"])
                if data.get("target_vol") is not None else None
            ),
            cost_basis=str(data.get("cost_basis") or COST_BASIS_GROSS),
            source=str(data.get("source") or ""),
        )

    def policy_hash(self) -> str:
        """口径指纹（sha256 前 16 位）。

        ``source`` 不参与哈希：它只说明口径从哪条路径组装而来，同一口径可以
        由回测或监控两条路径得到，指纹相同才说明二者真的等价。
        """
        payload = {
            "fill_model": self.fill_model,
            "commission_rate": self.commission_rate,
            "slippage": self.slippage,
            "commission_by_code": list(self.commission_by_code),
            "cost_by_asset": list(self.cost_by_asset),
            "rebalance_freq": self.rebalance_freq,
            "execution_delay": self.execution_delay,
            "target_vol": self.target_vol,
            "cost_basis": self.cost_basis,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    # 比对
    # ------------------------------------------------------------------

    def is_cost_equivalent(self, other: "ExecutionPolicy", assets: Optional[Any] = None) -> bool:
        """逐资产有效费率是否相等——真正决定 NAV 是否分叉的判据。

        ``fill_model`` 不同不影响本判据：回测增量成交与监控扣费后重建是两种
        经济语义（见 fills.py 的两个实现），它们的差异由 parity 报告单独归因，
        不属于「成本口径不一致」。

        Args:
            assets: 需要比对的资产全集；为 None 时取两侧显式声明过的代码并集，
                并始终补入 :data:`UNDECLARED_ASSET` 以覆盖扁平费率。
        """
        if assets is None:
            assets = set(dict(self.commission_by_code)) | set(dict(self.cost_by_asset))
            assets |= set(dict(other.commission_by_code)) | set(dict(other.cost_by_asset))
            assets.add(UNDECLARED_ASSET)
        for asset in assets:
            if abs(self.effective_cost_of(asset) - other.effective_cost_of(asset)) > 1e-12:
                return False
        return True

    def diff(self, other: "ExecutionPolicy") -> List[str]:
        """字段级差异（人话），用于 parity 报告首行归因。空列表表示完全一致。"""
        out: List[str] = []
        if not self.is_cost_equivalent(other):
            if self.cost_basis != other.cost_basis:
                out.append(
                    "成交口径不同：{}={}，{}={}（gross 不计交易成本，net 计费，"
                    "两侧净值必然逐日分叉）".format(
                        self.source or "A", self.cost_basis,
                        other.source or "B", other.cost_basis,
                    )
                )
            sample = sorted(
                set(dict(self.commission_by_code)) | set(dict(self.cost_by_asset))
                | set(dict(other.commission_by_code)) | set(dict(other.cost_by_asset))
                | {UNDECLARED_ASSET}
            )[:5]
            for asset in sample:
                a, b = self.effective_cost_of(asset), other.effective_cost_of(asset)
                if abs(a - b) > 1e-12:
                    label = (
                        "（未单独声明费率的资产）"
                        if asset == UNDECLARED_ASSET else asset
                    )
                    out.append(
                        "资产 {} 有效费率：{}={} vs {}={}".format(
                            label, self.source or "A", a, other.source or "B", b
                        )
                    )
        for name in ("rebalance_freq", "execution_delay", "target_vol"):
            va, vb = getattr(self, name), getattr(other, name)
            # 空值代表「该路径不持有这项信息」（监控的调仓调度由 detector 决定，
            # 不在 PortfolioTracker 上），未知不等于不一致；若也报差异，每次比对
            # 都会多出固定噪声，反而淹没真正导致分叉的成本口径。
            if va == vb:
                continue
            if va in ("", None) or vb in ("", None):
                continue
            out.append(
                "{}：{}={} vs {}={}".format(name, self.source or "A", va,
                                            other.source or "B", vb)
            )
        return out


# =============================================================================
# 工厂：从两条组装路径各取一次口径
# =============================================================================

def from_backtest_config(config: Any, fill_model: str = FILL_CLOSE) -> ExecutionPolicy:
    """从 ``BacktestConfig`` 取回测侧口径。

    ``commission_by_code`` 由 ``runner._apply_trading_costs`` 在引擎构建前回填，
    因此本函数必须在 ``run_unified`` 内、回填之后调用才拿得到策略自述费率。
    """
    by_code = _freeze_rate_map(getattr(config, "commission_by_code", None))
    rate = float(getattr(config, "commission_rate", 0.0) or 0.0)
    slip = float(getattr(config, "slippage", 0.0) or 0.0)
    basis = COST_BASIS_NET if (rate > 0 or slip > 0 or by_code) else COST_BASIS_GROSS
    return ExecutionPolicy(
        fill_model=fill_model,
        commission_rate=rate,
        slippage=slip,
        commission_by_code=by_code,
        rebalance_freq=str(getattr(config, "rebalance_freq", "") or ""),
        execution_delay=getattr(config, "execution_delay", None),
        target_vol=getattr(config, "target_vol", None),
        cost_basis=basis,
        source="backtest_config",
    )


def from_monitor_tracker(tracker: Any, fill_model: str = FILL_REBALANCE) -> ExecutionPolicy:
    """从 ``PortfolioTracker`` 取监控侧口径。

    ``configure()`` 把 ``trading_cost`` 固定置空（通用监控 gross 口径），因此
    这里得到的 ``cost_basis`` 通常是 gross；研究员策略自带费率、不经过
    ``PortfolioTracker``，不适用本函数。

    调仓调度类字段（``rebalance_freq`` / ``execution_delay``）故意不填：它们
    由 ``signal_detector`` 与运行时配置决定，tracker 不持有；留空即表示未知，
    :meth:`ExecutionPolicy.diff` 不会把未知当成不一致。
    """
    cost_by_asset = _freeze_rate_map(getattr(tracker, "trading_cost", None))
    return ExecutionPolicy(
        fill_model=fill_model,
        cost_by_asset=cost_by_asset,
        cost_basis=COST_BASIS_NET if cost_by_asset else COST_BASIS_GROSS,
        source="monitor_tracker",
    )
