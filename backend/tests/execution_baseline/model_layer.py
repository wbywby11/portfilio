# -*- coding: utf-8 -*-
"""生产模型层：真实 ``strategy_models`` 文档跑固定窗口，冻结输出并做 ``rel ≤ 1e-9`` 比对.

选型依据（``commit message`` 里同样记录）
----------------------------------------
从 ``strategy_models`` 中 ``status=已发布`` 或 ``live_publish_enabled=True`` 的
18 个模型里选 4 个，覆盖执行层的四条互不重叠的路径：

+--------------------------------+------------------+----------------------------------+
| model_id                       | 覆盖点           | 为什么是它                       |
+================================+==================+==================================+
| 6a7194f3df5c07bf2cd2dd05       | 单策略           | ``allocation`` 模型 + 选择器      |
| 多资产策略                     |                  | （momentum_reversal），走          |
|                                |                  | CompositionPipeline 三层编排      |
+--------------------------------+------------------+----------------------------------+
| 6ae80410e6d7a479f90bbb5b       | 带               | ``standalone_strategies``          |
| 红利 GARP 增强                 | commission_by_   | ``get_trading_costs`` 返回分资产   |
|                                | code             | 费率 → ``execution.py`` 净额配平   |
+--------------------------------+------------------+----------------------------------+
| 6ad9820464d47ae3b5003103       | standalone       | 独立打包策略，单类内完成选样/赋权  |
| NOUS验收_库内15资产            |                  | ＋月末调仓，无分资产费率           |
+--------------------------------+------------------+----------------------------------+
| 6a719daf2351b925eb1adacc       | 组合             | ``is_portfolio=True`` + 四象限     |
| 四象限组合                     |                  | 权重模型，走 ``composite_runner``  |
|                                |                  | 两段引擎（子策略 + 母层）          |
+--------------------------------+------------------+----------------------------------+

为什么组合层不用 ``run_portfolio_backtest_api``：该端点会写 ``backtest_records``
（破坏性副作用）。``app.monitor.portfolio_backtest_monitor.run_portfolio_monitor_pipeline``
使用**完全相同**的构建块但不落库，是同一语义的只读入口。

容差
----
``rel ≤ 1e-9`` + 绝对兜底 ``abs ≤ 1e-12``（零值附近 ``rel`` 无意义）。
超出容差即打印差异字段路径与两侧值，由主执行者归因（预期变化 / 逻辑错误）。
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

GOLDEN_DIR = HERE / "model_golden"

#: 固定回测窗口：不能取 ``datetime.now()``（那样每天重跑都换基线）。
START_DATE = "20220104"
END_DATE = "20251231"
INITIAL_CASH = 10_000_000.0
INITIAL_NAV = 1000.0
RISK_FREE_RATE = 0.02

RTOL = 1e-9
ATOL = 1e-12


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    label: str
    kind: str  # "single" | "portfolio"
    why: str
    #: 该模型的回测窗口（YYYYMMDD）。组合层窗口单独收窄：四象限组合含雪球
    #: 日频对冲与产品层叠加，4 年窗跑一次约 7.5 分钟——组合层若因此被排除在
    #: 每步门禁之外，等于没有守。1 年窗（12 次月度调仓）足以让任何记账漂移
    #: 显形，是覆盖率与可执行性的折中；单策略层保持 4 年窗。
    start_date: str = START_DATE
    end_date: str = END_DATE


MODELS: Tuple[ModelSpec, ...] = (
    ModelSpec(
        "6a7194f3df5c07bf2cd2dd05", "allocation_multi_asset", "single",
        "单策略：allocation 模型 + momentum_reversal 选择器，覆盖 CompositionPipeline 三层编排",
    ),
    ModelSpec(
        "6ae80410e6d7a479f90bbb5b", "standalone_dividend_garp", "single",
        "分资产费率：standalone get_trading_costs → commission_by_code 净额配平分支",
    ),
    ModelSpec(
        "6ad9820464d47ae3b5003103", "standalone_nous_low_vol", "single",
        "standalone 单策略：独立打包策略、月末调仓、无分资产费率",
    ),
    ModelSpec(
        "6a719daf2351b925eb1adacc", "portfolio_quadrant", "portfolio",
        "组合：is_portfolio + 四象限权重模型，覆盖 composite_runner 两段引擎",
        start_date="20250102", end_date="20251231",
    ),
)


# ======================================================================
#  运行
# ======================================================================

async def _run_single_pair(spec: ModelSpec) -> Dict[str, Any]:
    """单策略/standalone 模型：走 ``run_unified``（生产回测同一入口）."""
    from bson import ObjectId

    from app.allocation.services.registry import create_strategy_service_from_database
    from app.backtesting.composition_builder import build_strategy_composition
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed, resolve_lookback_days
    from app.backtesting.runner import RunSpec, run_unified
    from app.services.backtest_execution import _build_risk_config
    from app.services.market_service import MarketService
    from app.services.strategy_model_service import StrategyModelService, build_backtest_params

    service = StrategyModelService()
    model = await service.get_model(spec.model_id)
    if model is None:
        raise RuntimeError(f"生产模型不存在: {spec.model_id}")
    raw = await service.collection.find_one({"_id": ObjectId(spec.model_id)})
    strategy_params = build_backtest_params(model, model_data=raw)

    config = BacktestConfig(
        name=f"baseline_{spec.label}",
        thscodes=list(model.asset_codes),
        start_date=spec.start_date,
        end_date=spec.end_date,
        rebalance_freq=model.rebalance_frequency,
        initial_cash=INITIAL_CASH,
    )
    comp = build_strategy_composition(spec.model_id and model.template_code,
                                      list(model.asset_codes), strategy_params)
    if comp.force_month_end:
        config.rebalance_freq = "month_end"

    market_service = MarketService()
    feed = await DataFeed.from_market_service(
        market_service, config,
        lookback_days=resolve_lookback_days(
            strategy_params, 500, strategy_type=model.template_code
        ),
        strategy_type=model.template_code,
    )
    if feed.prices.empty:
        raise RuntimeError(f"模型 {spec.label} 在窗口 {spec.start_date}-{spec.end_date} 无行情")

    registry = await create_strategy_service_from_database(market_service=market_service)
    strategy_cls = registry.get_strategy_class(model.template_code)

    result = run_unified(RunSpec(
        config=config,
        data_feed=feed,
        allocator=strategy_cls(),
        thscodes=list(model.asset_codes),
        composition=comp.composition,
        strategy_params=strategy_params,
        risk_config=_build_risk_config(strategy_params),
    ))
    out = normalize_backtest_result(result)
    out["meta"] = {
        "model_id": spec.model_id,
        "label": spec.label,
        "kind": spec.kind,
        "template_code": model.template_code,
        "why": spec.why,
        "window": [spec.start_date, spec.end_date],
        "rebalance_freq": config.rebalance_freq,
        "n_assets": len(model.asset_codes),
        "commission_by_code": bool(config.commission_by_code),
        "commission_rate": float(config.commission_rate),
        "slippage": float(config.slippage),
    }
    return out


async def _run_portfolio_pair(spec: ModelSpec) -> Dict[str, Any]:
    """组合模型：走 ``run_portfolio_monitor_pipeline``（只读，不写 backtest_records）."""
    from app.monitor.portfolio_backtest_monitor import run_portfolio_monitor_pipeline

    pipe = await run_portfolio_monitor_pipeline(
        portfolio_model_id=spec.model_id,
        start_date=spec.start_date,
        end_date=spec.end_date,
        initial_nav=INITIAL_NAV,
        rebalance_freq="monthly",
        commission_rate=0.0,
        slippage=0.0,
    )
    nav = pipe["portfolio_nav"]
    perf = pipe.get("performance")
    return {
        "n_snapshots": int(len(nav)),
        "nav": [[d.strftime("%Y-%m-%d"), _f(v)] for d, v in nav.items()],
        "rebalance_dates": [str(d)[:10] for d in (pipe.get("rebalance_dates") or [])],
        "n_rebalance_dates": len(pipe.get("rebalance_dates") or []),
        "final_weights": _sorted_floats(
            (pipe.get("equity_curve") or [{}])[-1].get("weights") or {}
        ),
        "sub_keys": sorted(
            str(k) for k in (pipe.get("sub_snapshots_by_key") or {}).keys()
        ),
        "metrics": _metrics_of_perf(perf),
        "meta": {
            "model_id": spec.model_id,
            "label": spec.label,
            "kind": spec.kind,
            "template_code": "portfolio_composite",
            "why": spec.why,
            "window": [spec.start_date, spec.end_date],
            "rebalance_freq": "monthly",
            "n_assets": len((pipe.get("equity_curve") or [{}])[-1].get("weights") or {}),
            "commission_by_code": False,
            "commission_rate": 0.0,
            "slippage": 0.0,
        },
    }


# ======================================================================
#  归一化
# ======================================================================

def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _sorted_floats(d: Optional[Dict[str, Any]]) -> Dict[str, float]:
    items = (d or {}).items()
    return {
        str(k): _f(v)
        for k, v in sorted(items, key=lambda kv: str(kv[0]))
        if abs(_f(v)) > 0.0
    }


def _digest(obj: Any) -> str:
    text = __import__("json").dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_backtest_result(result: Any) -> Dict[str, Any]:
    """``BacktestResult`` → 冻结结构.

    规模取舍：369 资产的逐笔成交全量冻结会撑到几十 MB，因此成交明细只冻结
    SHA256 摘要 + 聚合量；净值序列与期末权重逐点冻结（对记账漂移最敏感）。
    """
    from app.backtesting.analytics import PerformanceAnalyzer

    snaps = list(result.snapshots)
    trades = list(result.trades)
    nav = [[s.time.strftime("%Y-%m-%d"), _f(s.total_value)] for s in snaps]
    final = _sorted_floats(snaps[-1].weights) if snaps else {}
    trade_rows = [
        [t.time.strftime("%Y-%m-%d"), str(t.thscode), str(t.side), _f(t.quantity),
         _f(t.price), _f(t.commission), _f(t.slippage_cost), _f(t.pnl)]
        for t in trades
    ]
    perf = PerformanceAnalyzer(risk_free_rate=RISK_FREE_RATE).from_results(snaps, trades)
    return {
        "n_snapshots": len(snaps),
        "n_trades": len(trades),
        "nav": nav,
        # 期末权重取绝对值最大的 40 项（含负现金腿以外的主仓），其余入摘要
        "final_weights": dict(
            sorted(final.items(), key=lambda kv: -abs(kv[1]))[:40]
            if len(final) > 40 else final.items()
        ),
        "final_weights_sha": _digest(final),
        "trades_sha": _digest(trade_rows),
        "trades_agg": {
            "quantity_sum": _f(sum(_f(t.quantity) for t in trades)),
            "commission_sum": _f(sum(_f(t.commission) for t in trades)),
            "slippage_sum": _f(sum(_f(t.slippage_cost) for t in trades)),
            "pnl_sum": _f(sum(_f(t.pnl) for t in trades)),
            "buy_count": int(sum(1 for t in trades if str(t.side) == "buy")),
            "sell_count": int(sum(1 for t in trades if str(t.side) == "sell")),
        },
        "metrics": _metrics_of_perf(perf),
    }


def _metrics_of_perf(perf: Any) -> Dict[str, float]:
    if perf is None:
        return {}
    return {
        "annual_return": _f(getattr(perf, "annual_return", 0.0)),
        "annual_vol": _f(getattr(perf, "annual_volatility", 0.0)),
        "sharpe": _f(getattr(perf, "sharpe_ratio", 0.0)),
        "max_drawdown": _f(getattr(perf, "max_drawdown", 0.0)),
        "calmar": _f(getattr(perf, "calmar_ratio", 0.0)),
        "total_return": _f(getattr(perf, "total_return", 0.0)),
        "turnover": _f(getattr(perf, "turnover", 0.0)),
        "total_commission": _f(getattr(perf, "total_commission", 0.0)),
        "total_slippage": _f(getattr(perf, "total_slippage", 0.0)),
    }


# ======================================================================
#  数据指纹
# ======================================================================

async def data_fingerprint_for(spec: ModelSpec) -> Dict[str, Any]:
    """模型级数据版本：行情覆盖区间 + 行数 + 价格矩阵 SHA256.

    只看 ``asset_prices`` 里本模型资产的日频 close —— 数据换版是模型层
    唯一合理的「非代码漂移」来源，必须可查而不是靠对比结果猜。
    """
    from app.config.collections import COL_ASSET_PRICES
    from app.config.database import Database

    from bson import ObjectId

    from app.services.strategy_model_service import StrategyModelService

    service = StrategyModelService()
    model = await service.get_model(spec.model_id)
    codes = sorted(set(model.asset_codes or [])) if model else []
    db = Database.get_database()
    # ``asset_prices`` 的资产键是 ``asset_code``（唯一索引 uniq_asset_date），
    # 不是行情宽表惯用的 ``thscode``；写错字段会静默得到 n_rows=0 的假指纹。
    # ``date`` 存 ``YYYY-MM-DD`` 字符串而基线窗口写 ``YYYYMMDD``，字符串比较会
    # 把整段排除，这里同样显式转换。
    lo = f"{spec.start_date[:4]}-{spec.start_date[4:6]}-{spec.start_date[6:8]}"
    hi = f"{spec.end_date[:4]}-{spec.end_date[4:6]}-{spec.end_date[6:8]}"
    cursor = db[COL_ASSET_PRICES].find(
        {"asset_code": {"$in": codes}, "date": {"$gte": lo, "$lte": hi}},
        {"_id": 0, "asset_code": 1, "date": 1, "close": 1},
    ).sort([("asset_code", 1), ("date", 1)])
    rows = await cursor.to_list(length=None)
    payload = [[r.get("asset_code"), str(r.get("date")), float(r.get("close") or 0.0)]
               for r in rows]
    dates = sorted({r[1] for r in payload})
    return {
        "n_assets": len(codes),
        "n_rows": len(payload),
        "first_date": dates[0] if dates else "",
        "last_date": dates[-1] if dates else "",
        "close_sha256": _digest(payload),
    }


# ======================================================================
#  构建 / 比对
# ======================================================================

def golden_path(spec: ModelSpec) -> Path:
    return GOLDEN_DIR / f"{spec.label}.json"


async def build_one(spec: ModelSpec) -> Dict[str, Any]:
    if spec.kind == "portfolio":
        out = await _run_portfolio_pair(spec)
    else:
        out = await _run_single_pair(spec)
    out["data"] = await data_fingerprint_for(spec)
    return out


def build(labels: Optional[List[str]] = None) -> Dict[str, Any]:
    specs = [m for m in MODELS if labels is None or m.label in labels]

    async def _all() -> Dict[str, Any]:
        from app.config.database import Database

        Database.connect()
        try:
            return {m.label: await build_one(m) for m in specs}
        finally:
            Database.close()

    return asyncio.run(_all())


def write_golden(label: str, payload: Dict[str, Any]) -> str:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    text = __import__("json").dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
    path = GOLDEN_DIR / f"{label}.json"
    path.write_text(text, encoding="utf-8")
    return _digest(payload)


def load_golden(label: str) -> Optional[Dict[str, Any]]:
    path = GOLDEN_DIR / f"{label}.json"
    if not path.exists():
        return None
    return __import__("json").loads(path.read_text(encoding="utf-8"))


def _walk_numeric(golden: Any, actual: Any, path: str, out: List[Dict[str, Any]]) -> None:
    """收集 (path, golden, actual, rel, abs) 差异（只关心数值叶子与结构差异）."""
    if isinstance(golden, dict):
        if not isinstance(actual, dict):
            out.append({"path": path, "golden": "<dict>", "actual": str(type(actual)), "rel": None})
            return
        gk, ak = set(golden), set(actual)
        for k in sorted(gk - ak):
            out.append({"path": f"{path}.{k}", "golden": "<present>", "actual": "<MISSING>", "rel": None})
        for k in sorted(ak - gk):
            out.append({"path": f"{path}.{k}", "golden": "<MISSING>", "actual": str(actual[k])[:60], "rel": None})
        for k in sorted(gk & ak):
            _walk_numeric(golden[k], actual[k], f"{path}.{k}", out)
        return
    if isinstance(golden, list):
        if not isinstance(actual, list):
            out.append({"path": path, "golden": "<list>", "actual": str(type(actual)), "rel": None})
            return
        if len(golden) != len(actual):
            out.append({"path": f"{path}.<len>", "golden": len(golden), "actual": len(actual), "rel": None})
        for i, (g, a) in enumerate(zip(golden, actual)):
            _walk_numeric(g, a, f"{path}[{i}]", out)
        return
    if isinstance(golden, bool) or isinstance(actual, bool):
        if golden is not actual:
            out.append({"path": path, "golden": golden, "actual": actual, "rel": None})
        return
    if isinstance(golden, (int, float)) and isinstance(actual, (int, float)):
        g, a = float(golden), float(actual)
        d = abs(a - g)
        scale = max(abs(g), abs(a))
        rel = (d / scale) if scale > 0 else 0.0
        if d <= ATOL or rel <= RTOL:
            return
        out.append({"path": path, "golden": g, "actual": a, "rel": rel, "abs": d})
        return
    if golden != actual:
        out.append({"path": path, "golden": str(golden)[:60], "actual": str(actual)[:60], "rel": None})


def compare_one(golden: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    diffs: List[Dict[str, Any]] = []
    _walk_numeric(golden, actual, "$", diffs)
    numeric = [d["rel"] for d in diffs if d.get("rel") is not None]
    return {
        "ok": not diffs,
        "n_diffs": len(diffs),
        "max_rel": max(numeric) if numeric else 0.0,
        "diffs": diffs,
    }


def check(labels: Optional[List[str]] = None) -> Dict[str, Any]:
    """跑模型并逐字段比对；返回 {ok, per_model: {label: {...}}}."""
    freshest = build(labels)
    per: Dict[str, Any] = {}
    ok = True
    for label, actual in freshest.items():
        golden = load_golden(label)
        if golden is None:
            per[label] = {"ok": False, "error": f"缺少 golden: {golden_path_by_label(label)}"}
            ok = False
            continue
        res = compare_one(golden, actual)
        g_data = golden.get("data") or {}
        a_data = actual.get("data") or {}
        res["data_changed"] = bool(g_data) and g_data.get("close_sha256") != a_data.get("close_sha256")
        res["data_window"] = [a_data.get("first_date", ""), a_data.get("last_date", "")]
        per[label] = res
        ok = ok and res["ok"]
    return {"ok": ok, "per_model": per}


def golden_path_by_label(label: str) -> Path:
    return GOLDEN_DIR / f"{label}.json"
