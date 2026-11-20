"""三层组合流水线：[Selection] → Allocation → [PostProcess].

所有策略的统一编排器，实现 IStrategy 接口。
核心设计原则：
  - Allocation 必选：每次回测都必须有权重计算
  - Selection 可选：composition["selector"] 为 None 时跳过
  - Control 可选：通过 BaseStrategyModel 委托给 CONTROL_REGISTRY，无需在此处理
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.allocation.runtime_params import WEIGHT_CAPS_PARAM_NAMES, resolve_weight_caps
from app.backtesting.signal import TargetWeightSignal
from app.backtesting.strategy_api import IStrategy, _log_rebalance_weights
from app.selection import SELECTION_REGISTRY, create_selector
from app.selection.services.selection_service import SelectionService

logger = logging.getLogger(__name__)

# 选择器相关参数键（不传给 allocator）
# 这些键属于 Selection 层，通过 composition["selection_params"] 路由到 selector

# Pipeline/前端控制键：由 Pipeline 编排或前端表单消费，不属于任一层的算法参数
_PIPELINE_CONTROL_KEYS = frozenset({
    'enable_momentum_selection', 'selector_type', 'selector_code',
    'asset_selection_count', 'n_assets_for_allocation',
    'selector_parameters', 'controller_code', 'controller_parameters',
    'enable_control',
    'preserve_price_gaps',   # 缺日保真（数据源层消费，非 allocator 参数）
    'inception_weights', 'inception_weights_auto_normalize',  # 期初建仓（引擎层消费）
    'calendar_source',       # 日历口径（监控 time_norm 消费，非 allocator 参数）
})

# 选择器运行时内部键：选择器/监控运行时消费但未在 get_param_schema() 中声明
_SELECTOR_RUNTIME_KEYS = frozenset({
    'use_price_skew', 'min_history_reversal',       # momentum_reversal 内部
    'mom_windows', 'posi_windows', 'smom_windows',  # 监控运行时因子窗口
    'macd_long_window',
    'top_n', 'risk_triggered',                      # etf_rotation 内部
})

def _collect_selector_schema_keys() -> frozenset:
    """从 SELECTION_REGISTRY 各选择器的参数 Schema 派生参数键集合.

    新增选择器只要在 get_param_schema() 中声明参数，即自动纳入过滤，
    无需手工维护清单，避免遗漏导致选择器参数错传给 allocator。
    """
    keys = set()
    for cls in SELECTION_REGISTRY.values():
        for p in cls.get_param_schema().get("params", []):
            name = p.get("name")
            if name:
                keys.add(name)
    return frozenset(keys)


# 选择器 schema 派生键（自动收集）
_SELECTOR_SCHEMA_KEYS = _collect_selector_schema_keys()

# 恒不下传 allocator 的键：Pipeline/前端控制键 + 选择器运行时内部键
# （由 Pipeline、引擎、数据源层、监控运行时消费，与策略形态无关）
_SELECTION_ONLY_KEYS = _PIPELINE_CONTROL_KEYS | _SELECTOR_RUNTIME_KEYS

# 双层共用键：选择器 schema 有声明，但 allocator（vol_scaled_budget/risk_parity/
# black_litterman 等）同样消费，必须继续传给 allocator，不能过滤
_ALLOCATOR_SHARED_KEYS = frozenset({'min_history_days', 'lookback_days'})

_SELECTION_PARAM_KEYS = (
    _SELECTION_ONLY_KEYS
    | (_SELECTOR_SCHEMA_KEYS - _ALLOCATOR_SHARED_KEYS)
)

# 已在内部处理杠杆的分配模型（不应在 Pipeline 层再次缩放）
_INTERNAL_LEVERAGE_IMPLS = frozenset({
    "VolScaledBudgetStrategy",
})

# 按 allocator 类缓存的「调用时应过滤掉的策略参数键」
_FILTERED_PARAM_KEYS_CACHE: Dict[type, frozenset] = {}


def _allocator_declared_keys(allocator: Any) -> frozenset:
    """返回 allocator 在自己的 ParamSchema 中声明的参数键集合.

    读取失败时返回空集并记 warning（等价于「无自声明键」，退回原过滤行为），
    不因元信息缺失中断回测。
    """
    cls = type(allocator)
    try:
        return frozenset(p.name for p in cls.get_param_schema().params)
    except Exception as exc:  # pragma: no cover - 防御性分支
        logger.warning(
            "[Pipeline] 读取 %s 参数声明失败，按无自声明键处理: %s",
            cls.__name__, exc,
        )
        return frozenset()


def _filtered_param_keys(allocator: Any) -> frozenset:
    """该 allocator 调用时应过滤掉的策略参数键集合（按类缓存）.

    选择器键过滤规则的目的是防止选择层参数渗进**不拥有选样能力**的分配器。
    打包独立形态（``composition.selector=None``）在包内复用选择器完成选样，
    这些参数由 allocator 自己声明、自己消费，属于 allocator 自有参数，必须
    放行——否则前端配了不生效，构成隐藏参数。

    判据是「allocator 是否自己声明该键」，不按策略类名特判：三层形态下现有
    allocator 均不声明选择器键（由 ``tests/test_schema_consistency.py``
    ``test_allocator_no_selector_params`` 守卫），故本规则对存量策略惰性，
    结果与 ``_SELECTION_PARAM_KEYS`` 完全一致。

    放行仅限选择器 schema 键：``_SELECTION_ONLY_KEYS``（Pipeline/前端控制键、
    选择器运行时内部键）恒过滤，即使 allocator 展开了
    ``model_level_param_group()`` 声明了 ``calendar_source`` 等键也不下传——
    它们由 Pipeline/引擎/监控运行时消费，不属 allocator 入参。
    """
    cls = type(allocator)
    cached = _FILTERED_PARAM_KEYS_CACHE.get(cls)
    if cached is None:
        cached = _SELECTION_ONLY_KEYS | (
            (_SELECTOR_SCHEMA_KEYS - _ALLOCATOR_SHARED_KEYS)
            - _allocator_declared_keys(allocator)
        )
        _FILTERED_PARAM_KEYS_CACHE[cls] = cached
    return cached


class CompositionPipeline(IStrategy):
    """三层组合流水线.

    将选择/分配/后处理三个阶段解耦为独立步骤，实现 IStrategy 接口。

    composition 配置格式:
    {
        "selector": "momentum_reversal",   # 选择器类型，None 表示跳过选择
        "allocator": "vol_scaled_budget",  # 分配器类型（必填）
        "controller": "rolling_vol",   # 控制器类型，None 表示不使用
        "schedule": {                      # 执行调度
            "rebalance_freq": "month_end",
            "execution_delay": 2
        }
    }
    """

    def __init__(
        self,
        allocator: Any,
        thscodes: List[str],
        composition: Optional[Dict[str, Any]] = None,
        strategy_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化组合流水线.

        Args:
            allocator: BaseStrategyModel 实例（必选），负责权重计算
            thscodes: 候选资产池代码列表
            composition: 三层组合配置，包含 selector/allocator/controller/schedule
            strategy_params: 策略参数字典（传给 allocator.allocate）
        """
        self._allocator = allocator
        self._thscodes = list(thscodes)
        self._composition = composition or {}
        self._strategy_params = strategy_params or {}
        self._selection_service = SelectionService()
        # 引擎注入的完整行情日历（ISO 字符串元组，进程内复用同一对象），
        # 透传给需要精确时序判定的选择器（见 _run_multi_signal）
        self._price_calendar_iso: Optional[tuple] = None
        # 引擎注入的非价格截面面板（面板名 → {期日 → 截面 DataFrame(index=code)}），
        # 供 allocate 按期取数；仅声明 get_extra_panels 的策略会被注入
        self._panels: Dict[str, Dict[pd.Timestamp, pd.DataFrame]] = {}
        self._panel_dates: Dict[str, List[pd.Timestamp]] = {}
        # allocator 是否声明包内自带日度风控（惰性求值后缓存）
        self._native_vol_control: Optional[bool] = None

    def set_price_calendar(self, trade_dates) -> None:
        """引擎在回测启动前注入完整行情日历（价格矩阵索引）."""
        self._price_calendar_iso = tuple(
            pd.Timestamp(d).strftime("%Y-%m-%d") for d in trade_dates
        )

    def set_panels(self, panels, panel_dates=None) -> None:
        """引擎在回测启动前注入非价格截面面板（与 set_price_calendar 同位置）.

        必须在 resolve_execution_schedule 之前调用：面板期日要作为 event_dates
        驱动调仓（见 get_execution_schedule）。

        Args:
            panels: {面板名: {期日 Timestamp: 截面 DataFrame(index=code)}}
            panel_dates: {面板名: [期日 Timestamp]}；缺省从 panels 推导
        """
        self._panels = dict(panels or {})
        if panel_dates is None:
            panel_dates = {
                name: sorted(periods.keys())
                for name, periods in self._panels.items()
            }
        self._panel_dates = dict(panel_dates or {})

    # ------------------------------------------------------------------
    # IStrategy 接口实现
    # ------------------------------------------------------------------

    def generate_target_weights(
        self,
        history_prices: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        """生成目标权重：Selection → Allocation → PostProcess."""

        # 检查是否为 multi_signal 模式（多信号复合）
        multi_signal = self._composition.get("multi_signal")

        if multi_signal:
            # multi_signal 模式：跑多个 selector 并混合信号
            signal_weights, active_assets = self._run_multi_signal(
                history_prices, as_of
            )
            asset_tags = {}
            use_full_matrix = False
        else:
            # 标准模式：单 selector
            # Step 1: Selection（可选）
            active_assets, asset_tags, use_full_matrix = self._run_selection(
                history_prices, as_of
            )
            signal_weights = None

        # Step 2: 构建 allocation 参数（注入标签、选择行等）
        alloc_params = self._build_allocation_params(
            active_assets, asset_tags, use_full_matrix, as_of
        )

        # multi_signal 模式：注入复合信号权重
        if signal_weights is not None:
            alloc_params["_signal_weights"] = signal_weights

        # Step 3: Allocation（必选）
        # momentum_reversal (7+1) 需要完整价格矩阵（含未选中资产），其他选择器仅传入选中资产
        if use_full_matrix:
            allocate_prices = history_prices
        else:
            # 选中资产可能来自面板/自定义候选池，未必在当前回测窗口内有行情。
            # 直接按 active_assets 取列会抛 KeyError，这里先与窗口价格矩阵取交集：
            # 无行情的标的无法分配，只能剔除；全部剔除则说明窗口与候选池不匹配，需显式报错。
            no_price = [c for c in active_assets if c not in history_prices.columns]
            if no_price:
                logger.warning(
                    "[Pipeline] 选中资产中 %d 只在当前回测窗口内无行情，已从分配矩阵剔除：%s",
                    len(no_price), no_price[:20],
                )
                active_assets = [c for c in active_assets if c in history_prices.columns]
                if not active_assets:
                    raise ValueError(
                        f"选中资产在当前回测窗口内均无行情数据（共 {len(no_price)} 只），无法分配。"
                        "请检查回测区间、行情入库情况或候选池配置"
                    )
            allocate_prices = history_prices[active_assets]

        weights_series = self._allocator.allocate(allocate_prices, **alloc_params)

        # 转为 dict，补全缺失资产为 0
        if isinstance(weights_series, pd.Series):
            weights_dict = weights_series.to_dict()
        elif isinstance(weights_series, dict):
            weights_dict = weights_series
        else:
            weights_dict = {}

        # 补全：分配模型可能未返回所有资产（数据不足、波动率为0等原因）
        for code in active_assets:
            if code not in weights_dict:
                weights_dict[code] = 0.0

        # Step 4: Post-process（杠杆缩放 + 权重 cap）
        weights_dict = self._run_post_process(weights_dict)

        # Step 5: 补全候选池中所有资产（未选中的为 0）
        final_weights = {code: weights_dict.get(code, 0.0) for code in self._thscodes}

        _log_rebalance_weights(as_of, final_weights, self._thscodes)

        return TargetWeightSignal(time=as_of, target_weights=final_weights)

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        history_prices: pd.DataFrame,
    ) -> Dict[str, Any]:
        """代理调用 allocator 的监控指标计算（含 control monitor 委托）.

        监控指标仅用于观测展示，波动率重置是否触发由
        check_volatility_trigger 单独把关（未配置 controller 时直接不触发），
        因此此处不再按 controller 门控，避免引擎回退到自己的波动率公式。
        """
        if hasattr(self._allocator, "compute_monitoring_metrics"):
            return self._allocator.compute_monitoring_metrics(
                current_weights=current_weights,
                prices=history_prices,
                **self._strategy_params
            )
        return {}

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> Tuple[bool, Optional[float]]:
        """代理调用 allocator 的波动率触发检查（含 control monitor 委托）.

        当 composition 未配置 controller 且 allocator 未声明包内自带风控时，
        直接返回未触发，避免 allocator 内置兜底逻辑被误触发。
        打包形态的独立策略 controller 为 None、风控写在策略包内，
        由 has_native_vol_control() 声明放行。
        """
        if not self._composition.get("controller") and not self._allocator_has_native_vol_control():
            return False, None
        if hasattr(self._allocator, "check_volatility_trigger"):
            merged = self._merge_params_with_controller(params)
            return self._allocator.check_volatility_trigger(
                current_weights=current_weights,
                prices=prices,
                **merged
            )
        return False, None

    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> Optional[pd.Series]:
        """代理调用 allocator 的波动率重置权重计算（含 control monitor 委托）.

        当 composition 未配置 controller 且 allocator 未声明包内自带风控时，
        直接返回 None，避免 allocator 内置兜底逻辑被误触发。
        """
        if not self._composition.get("controller") and not self._allocator_has_native_vol_control():
            return None
        if hasattr(self._allocator, "compute_volatility_reset_weights"):
            merged = self._merge_params_with_controller(params)
            return self._allocator.compute_volatility_reset_weights(
                current_weights=current_weights,
                prices=prices,
                **merged
            )
        return None

    def _allocator_has_native_vol_control(self) -> bool:
        """allocator 是否声明包内自带日度波动率风控（结果缓存）.

        打包形态的独立策略 composition.controller 为 None，但风控写在策略包内
        （重写 check_volatility_trigger / compute_volatility_reset_weights），
        需放行代理；三层组合形态的策略未声明此方法或返回 False，
        短路行为与历史完全一致。声明读取异常时按无自带风控处理，
        不静默放大风控范围。
        """
        if self._native_vol_control is None:
            fn = getattr(self._allocator, "has_native_vol_control", None)
            if callable(fn):
                try:
                    self._native_vol_control = bool(fn())
                except Exception as exc:
                    logger.warning(
                        "[Pipeline] has_native_vol_control 声明读取失败，"
                        "按无自带风控处理: %s", exc
                    )
                    self._native_vol_control = False
            else:
                self._native_vol_control = False
        return self._native_vol_control

    def _merge_params_with_controller(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """合并策略参数与 controller_parameters 子字典（扁平化）.

        控制器的 vc_short/vol_method 等参数由前端分区存储在
        controller_parameters 里，委托给 monitor 前必须展开，
        否则 monitor 读不到这些参数。
        """
        merged = {**self._strategy_params, **params}
        ctrl_params = merged.get("controller_parameters")
        if isinstance(ctrl_params, dict) and ctrl_params:
            merged.update(ctrl_params)
        return merged

    def get_execution_schedule(self) -> Optional[dict]:
        """代理调用 allocator 的执行调度声明，并支持模型级参数覆盖.

        BacktestEngine 通过此方法获取策略的调仓频率和执行延迟。
        模型参数 execution_delay 可覆盖 allocator/schema 的默认声明（如
        GMSI 2.0 GMAP 原型月末信号 T+2 执行，需在同模板不同模型间
        配置不同延迟），使同一 allocator 模板可复用于不同执行口径。
        """
        sched = None
        if hasattr(self._allocator, "get_execution_schedule"):
            sched = self._allocator.get_execution_schedule()
        user_delay = self._strategy_params.get("execution_delay")
        if user_delay is not None:
            try:
                delay = int(user_delay)
            except (TypeError, ValueError):
                logger.warning("[Pipeline] execution_delay 参数非法，忽略：%r", user_delay)
            else:
                base = dict(sched or {})
                # 模型显式声明执行延迟 = 该模型对执行口径有独立要求（如同模板
                # 服务不同原型口径），allocator 自带的 skip_dates/
                # selection_start_date 是为其他模型定制的配置，不得泄露给当前
                # 模型，重建干净 schedule 只保留调仓频率
                clean = {"rebalance_freq": base.get("rebalance_freq", "monthly")}
                # natural_frequency 是频率语义而非模型专属配置：它表示
                # daily/weekly 就是自然频率（监控侧据此走逐日/逐周映射，
                # 而不是按月末推演），必须与 rebalance_freq 一起保留，
                # 否则模型一填 execution_delay 就丢失该声明，回测与监控频率
                # 不同源。
                if base.get("natural_frequency"):
                    clean["natural_frequency"] = base["natural_frequency"]
                if base.get("skip_dates") or base.get("selection_start_date"):
                    logger.info(
                        "[Pipeline] 模型声明 execution_delay=%s，重置 allocator 专属调度配置"
                        "（skip_dates/selection_start_date）",
                        delay,
                    )
                clean["execution_delay"] = delay
                sched = clean
        # 面板驱动调仓：把注入的面板期日作为 event_dates（信号日=执行日=生效日）
        return self._inject_panel_event_dates(sched)

    def _inject_panel_event_dates(self, sched: Optional[dict]) -> Optional[dict]:
        """allocator 声明 panel_event_dates 且已注入面板期日时，把期日集合作为
        event_dates 注入调度声明。

        期日来自数据加载层注入的面板（set_panels），策略类内不出现具体日期常量；
        未注入面板或未声明 panel_event_dates 时原样返回，存量策略零影响。
        """
        if not self._panel_dates:
            return sched
        opts: Dict[str, Any] = {}
        fn = getattr(self._allocator, "get_data_feed_options", None)
        if callable(fn):
            try:
                opts = dict(fn() or {})
            except Exception as exc:
                logger.warning("[Pipeline] 读取 allocator 数据源选项失败：%s", exc)
        if not opts.get("panel_event_dates"):
            return sched
        event_dates = sorted({d for dates in self._panel_dates.values() for d in dates})
        if not event_dates:
            return sched
        merged = dict(sched or {})
        merged["event_dates"] = event_dates
        return merged

    def get_data_feed_options(self) -> Dict[str, Any]:
        """数据源选项声明（BacktestEngine 通过此方法选择信号计算价格源）.

        模型参数 preserve_price_gaps=True 时，信号计算使用保留品种缺日 NaN
        的价格矩阵，对齐原型"品种缺日→收益率/动量窗口 NaN 传播、缺窗口
        品种退出候选"口径（如 GMSI 2.0 数据源存在品种零星缺日）。
        """
        alloc_opts: Dict[str, Any] = {}
        fn = getattr(self._allocator, "get_data_feed_options", None)
        if callable(fn):
            try:
                alloc_opts = dict(fn() or {})
            except Exception as exc:
                logger.warning("[Pipeline] 读取 allocator 数据源选项失败：%s", exc)
        opts = dict(alloc_opts)
        # preserve_price_gaps：模型参数优先（用户可配），缺省取 allocator 静态声明
        preserve = self._strategy_params.get("preserve_price_gaps")
        if preserve is None:
            preserve = alloc_opts.get("preserve_price_gaps", False)
        opts["preserve_price_gaps"] = bool(preserve)
        return opts

    def on_daily_settle(self, time, position, total_value, bar_extra=None):
        """每日结算钩子，委托到 allocator.

        策略模型可重写此方法实现闲置资金利息、GC001 回购利息等每日调整逻辑。
        """
        if hasattr(self._allocator, "on_daily_settle"):
            return self._allocator.on_daily_settle(
                time, position, total_value, bar_extra=bar_extra
            )
        return None

    def get_capabilities(self) -> Dict[str, Any]:
        """汇聚 allocator 的能力声明（供引擎调整执行/展示行为）.

        能力写在 allocator 的 StrategyParamSchema 上，与参数声明同位置维护。
        无法读取 schema 时返回空字典，由引擎取默认值。
        """
        try:
            schema = type(self._allocator).get_param_schema()
        except Exception as exc:
            logger.debug("[Pipeline] 读取 %s 能力声明失败：%s", type(self._allocator).__name__, exc)
            return {}
        caps = {
            "snapshot_weight_source": getattr(schema, "snapshot_weight_source", "actual"),
            "signal_timing": getattr(schema, "signal_timing", "prev_close"),
        }
        # 模型级覆盖：同一 allocator 模板服务不同原型口径时（如 GMSI 2.0
        # GCMI 需要 execution_bar），由模型参数声明而非改模板默认值
        user_timing = self._strategy_params.get("signal_timing")
        if isinstance(user_timing, str) and user_timing in ("prev_close", "execution_bar"):
            caps["signal_timing"] = user_timing
        return caps

    # ------------------------------------------------------------------
    # 向后兼容：引擎通过 _base_strategy / _impl 访问策略参数
    # ------------------------------------------------------------------

    @property
    def _base_strategy(self):
        """向后兼容：BacktestEngine 通过此属性访问策略内部参数."""
        return self

    @property
    def _impl(self):
        """向后兼容：引擎通过 _base_strategy._impl 获取策略实现类."""
        return self._allocator

    @property
    def _params(self):
        """向后兼容：引擎通过 _base_strategy._params 获取策略参数."""
        return self._strategy_params

    # ------------------------------------------------------------------
    # Step 1: Selection（可选）
    # ------------------------------------------------------------------

    def _run_selection(
        self,
        history_prices: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> Tuple[List[str], Dict[str, str], bool]:
        """执行选择阶段.

        从 composition["selector"] 读取选择器类型：
        - None → 跳过选择，使用全部候选池
        - "momentum_reversal" / ... → 从 SELECTION_REGISTRY 获取并执行

        Returns:
            (active_assets, asset_tags, use_full_matrix)
        """
        selector_type_raw = self._composition.get("selector")

        # selector 为 None：跳过选择
        if not selector_type_raw:
            # 候选池是策略配置的静态代码列表，未必都在当前回测窗口内有行情；
            # 未过滤会让 allocate_prices 取列时抛 KeyError，故按窗口价格矩阵求交集。
            available = [c for c in self._thscodes if c in history_prices.columns]
            dropped = [c for c in self._thscodes if c not in history_prices.columns]
            if dropped:
                logger.warning(
                    "[Pipeline] 候选池中 %d 只资产在当前回测窗口内无行情，已剔除：%s",
                    len(dropped), dropped[:20],
                )
            if not available:
                raise ValueError(
                    f"候选池 {len(self._thscodes)} 只资产在当前回测窗口内均无行情数据，无法分配。"
                    "请检查回测区间与行情入库情况"
                )
            return available, {}, False

        # 处理 selector_type 别名兼容
        selector_type = self._normalize_selector_type(selector_type_raw)

        # 检查注册表
        if selector_type not in SELECTION_REGISTRY:
            # 不静默退化为全池：未注册通常是 selector_type 配置错误（如前端传错别名），
            # 退化为全池会把配置错误伪装成一次正常的全池回测。
            raise ValueError(
                f"选择器 {selector_type!r} 未在 SELECTION_REGISTRY 中注册。"
                f"请检查 composition.selector 配置；已注册选择器：{sorted(SELECTION_REGISTRY)}"
            )

        # 构建选择参数
        selection_params = dict(
            self._composition.get("selection_params", {})
            or self._strategy_params.get("_selection_params", {})
        )
        # 合并前端通过 selector_parameters 子字典传入的选择器参数
        selector_params_dict = self._strategy_params.get("selector_parameters")
        if isinstance(selector_params_dict, dict) and selector_params_dict:
            selection_params.update(selector_params_dict)
        # 从策略参数继承通用选择参数
        selection_params.setdefault(
            "min_history_days",
            self._strategy_params.get("min_history_days", 260)
        )
        # 自定义信号日历与行情日历透传（与 multi_signal 模式一致）：
        # 日历感知选择器需在信号日历上识别月末信号、在行情日历上判定生效日就绪
        calendar = self._strategy_params.get("signal_calendar_dates")
        if isinstance(calendar, (list, tuple)) and calendar:
            selection_params["signal_calendar_dates"] = calendar
        if self._price_calendar_iso:
            selection_params["price_calendar_dates"] = self._price_calendar_iso

        # 池内再选数量（仅对非 momentum_reversal 生效）
        n_assets = int(
            self._composition.get("n_assets", len(self._thscodes))
        )

        try:
            selector = create_selector(selector_type)
            selection_params["_rebalance_date"] = as_of

            result = selector.select(history_prices, n_assets, **selection_params)

            if not result.selected_assets:
                # 不静默退化为全池：空选择表示「无合格资产/数据不足」，
                # 退化为全池会反转选择意图（如 ETF 折价选择器在无 ETF 时选中全部非 ETF），
                # 把一次失败伪装成看似正常的全池回测。
                raise ValueError(
                    f"选择器 {selector_type!r} 在 {as_of} 未选出任何资产"
                    "（无合格资产或历史数据不足）。请检查候选池、选择参数或回测起始日"
                )
            selected_assets = list(result.selected_assets)
            asset_tags = getattr(result, "tags", None) or {}

            logger.info(
                "[Pipeline-选择] 选择器=%s | 选中=%d | tags=%s",
                selector_type, len(selected_assets), asset_tags,
            )

            # 池内再选：在已选池上再跑一次选择，决定哪些参与分配
            active_assets = self._run_within_pool_selection(
                selector, history_prices, selected_assets, selection_params, as_of
            )

            # momentum_reversal (7+1) 或 vol_scaled_budget 需要完整价格矩阵传递给 allocator
            use_full_matrix = (
                selector_type == "momentum_reversal"
                or type(self._allocator).__name__ == "VolScaledBudgetStrategy"
            )

            return active_assets, asset_tags, use_full_matrix

        except Exception as e:
            # 不静默退化为全池：选择阶段异常（参数解析错误、选择器内部错误、
            # 上面主动抛出的空选择/未注册等）都应直达调用方，由 router 转 HTTP 400，
            # 而不是把失败伪装成一次全池回测。
            logger.error(f"[Pipeline] 选择阶段失败: {e}")
            raise

    def _normalize_selector_type(self, raw: str) -> str:
        """规范化选择器类型名（兼容旧别名）."""
        if raw.startswith("sel_"):
            raw = raw[4:]
        if raw in ("reversal", "hybrid"):
            return "momentum_reversal"
        return raw

    def _run_within_pool_selection(
        self,
        selector,
        history_prices: pd.DataFrame,
        selected_assets: List[str],
        selection_params: Dict[str, Any],
        as_of: pd.Timestamp,
    ) -> List[str]:
        """在已选池中再选择，决定本次调仓哪些参与分配（可选）.

        momentum_reversal 已按 7+1 产出选中资产，不再做池内再选。
        其他选择器可通过 n_assets_for_allocation 配置池内再选数量。
        """
        selector_type = self._normalize_selector_type(
            self._composition.get("selector", "")
        )
        if selector_type == "momentum_reversal":
            return selected_assets

        n_for_alloc = self._composition.get("n_assets_for_allocation")
        if n_for_alloc is None:
            return selected_assets

        n_active = int(n_for_alloc)
        if n_active < 1 or n_active >= len(selected_assets) or len(selected_assets) <= 1:
            return selected_assets

        # 池内再选属于选择阶段的一部分，异常不静默降级，交由外层 _run_selection 抛出
        within_result = selector.select(
            history_prices[selected_assets], n_active, **selection_params
        )
        return list(within_result.selected_assets)

    # ------------------------------------------------------------------
    # multi_signal 模式：多信号复合（Selection 层职责）
    # ------------------------------------------------------------------

    def _run_multi_signal(
        self,
        history_prices: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> Tuple[Dict[str, float], List[str]]:
        """多信号复合：跑多个 selector 并按权重混合信号。

        从 composition["multi_signal"] 读取信号通道配置：
        [
            {"selector": "trend_following", "weight": 0.5},
            {"selector": "cross_sectional_long_short", "weight_param": "combo_weight_cs"},
        ]

        权重来源：
        - weight: 静态数值
        - weight_param: 从 strategy_params 动态读取（支持前端滑块控制）

        Returns:
            (signal_weights, active_assets)
            signal_weights: {asset_code: composite_signal_value}
            active_assets: 参与分配的资产列表（multi_signal 模式下为全部候选池）
        """
        multi_signal_configs = self._composition.get("multi_signal", [])
        if not multi_signal_configs:
            return {}, list(self._thscodes)

        # 获取 selector 参数（从 selector_parameters 子字典）
        selector_params_dict = self._strategy_params.get("selector_parameters", {})
        if not isinstance(selector_params_dict, dict):
            selector_params_dict = {}

        composite_weights: Dict[str, float] = {}

        for config in multi_signal_configs:
            sel_type = config.get("selector")
            if not sel_type:
                continue

            # 解析权重：weight_param（动态）优先，否则用 weight（静态）
            weight_param = config.get("weight_param")
            if weight_param and weight_param in self._strategy_params:
                weight = float(self._strategy_params[weight_param])
            else:
                weight = float(config.get("weight", 0.5))

            # 零权重通道跳过执行：不贡献信号，避免无效计算
            # （如 GCMI 场景 combo_weight_tf=0 时只跑 CS 通道）
            if weight == 0:
                continue

            if sel_type not in SELECTION_REGISTRY:
                # 不静默跳过：多信号复合缺一路信号会让合成权重悄悄失真
                raise ValueError(
                    f"[Pipeline-multi_signal] 选择器 {sel_type!r} 未在 SELECTION_REGISTRY 中注册。"
                    f"请检查 composition.multi_signal 配置；已注册选择器：{sorted(SELECTION_REGISTRY)}"
                )

            try:
                selector = create_selector(sel_type)
                # 每个 selector 只接收它自己的参数（由 selector_params_dict 提供）
                sel_params = dict(selector_params_dict)
                sel_params["_rebalance_date"] = as_of
                # 自定义信号日历透传：日频调仓不走调度层日历，
                # 月频锁定类选择器（如 cross_sectional_long_short）需在日历上识别月末信号
                calendar = self._strategy_params.get("signal_calendar_dates")
                if isinstance(calendar, (list, tuple)) and calendar:
                    sel_params["signal_calendar_dates"] = calendar
                # 完整行情日历透传：月频锁定类选择器需在价格日历上精确判定
                # 信号日历计数的生效日是否为窗口末行的下一交易日
                if self._price_calendar_iso:
                    sel_params["price_calendar_dates"] = self._price_calendar_iso

                result = selector.select(
                    history_prices, len(self._thscodes), **sel_params
                )

                if result.scores:
                    for code, score in result.scores.items():
                        composite_weights[code] = (
                            composite_weights.get(code, 0.0) + weight * float(score)
                        )

                logger.info(
                    "[Pipeline-multi_signal] selector=%s weight=%.3f scores=%d",
                    sel_type, weight, len(result.scores or {}),
                )
            except Exception as e:
                # 不静默吞掉：单路信号失败会让合成信号缺腿，结果失真却看似正常
                logger.error(
                    f"[Pipeline-multi_signal] selector={sel_type!r} 失败: {e}"
                )
                raise

        if not composite_weights:
            # 不静默退化为全池空信号：所有信号通道都没产出，属复合失败
            raise ValueError(
                f"multi_signal 复合在 {as_of} 未产出任何信号权重"
                "（所有信号通道得分为空）。请检查各选择器参数与候选池数据"
            )

        # 合并所有资产的权重（包括未产生信号的资产，补 0）
        all_codes = set(composite_weights.keys()) | set(self._thscodes)
        signal_weights = {
            code: composite_weights.get(code, 0.0) for code in all_codes
        }
        active_assets = list(self._thscodes)

        logger.info(
            "[Pipeline-multi_signal] 复合完成: %d 个信号通道, %d 个资产",
            len(multi_signal_configs), len(signal_weights),
        )

        return signal_weights, active_assets

    # ------------------------------------------------------------------
    # Step 2: 构建 Allocation 参数
    # ------------------------------------------------------------------

    def _build_allocation_params(
        self,
        active_assets: List[str],
        asset_tags: Dict[str, str],
        use_full_matrix: bool,
        as_of: Optional[pd.Timestamp] = None,
    ) -> Dict[str, Any]:
        """从选择结果和策略参数构建 allocator 的调用参数.

        职责：
        1. 构建 _selection_row（0/1/2 标记）供分配模型使用
        2. 注入 _asset_tags（动量/反转标签）
        3. 过滤掉选择器专属参数，仅传分配相关参数
        """
        params = {}

        # 构建 _selection_row：标记每个候选资产的选中状态
        if use_full_matrix and asset_tags:
            # momentum_reversal (7+1) 路径：根据标签编码（both=2, momentum/reversal=1, 其他=0）
            selection_row = {}
            for code in self._thscodes:
                tag = asset_tags.get(code, "")
                if tag == "both":
                    selection_row[code] = 2
                elif tag in ("momentum", "reversal"):
                    selection_row[code] = 1
                else:
                    selection_row[code] = 0
        else:
            # 普通路径：选中标记为 1，未选中标记为 0
            active_set = set(active_assets)
            selection_row = {code: (1 if code in active_set else 0) for code in self._thscodes}

        # 合并策略参数（过滤选择层专属键；allocator 自己声明的键放行）
        filtered_keys = _filtered_param_keys(self._allocator)
        for k, v in self._strategy_params.items():
            if k in filtered_keys:
                continue
            params[k] = v

        # 展开 controller_parameters 子字典（前端分区存储的控制器参数）
        ctrl_params = self._strategy_params.get("controller_parameters")
        if isinstance(ctrl_params, dict) and ctrl_params:
            params.update(ctrl_params)

        # multi_signal 模式下，selector 参数已在 _run_multi_signal() 中处理
        # 标准模式下，selector 参数已在 _run_selection() 中处理
        # allocator 只接收属于它自己的参数，无需特殊提取 selector 参数

        # 注入选择结果
        params["_selection_row"] = selection_row
        if asset_tags:
            params["_asset_tags"] = asset_tags

        # 注入选择器配置的选择数量（供 tag_based 动态等分预算使用）
        n_momentum = self._strategy_params.get("n_momentum")
        n_reversal = self._strategy_params.get("n_reversal")
        if n_momentum is not None:
            params["_n_momentum"] = int(n_momentum)
        if n_reversal is not None:
            params["_n_reversal"] = int(n_reversal)

        # 确保 base.py 能解析到 composition 声明的控制器
        controller = self._composition.get("controller")
        if controller:
            params.setdefault("vol_control_type", controller)

        # 注入执行日 as_of：面板类策略据此定位当期截面（与 _selection_row 同为
        # Pipeline 注入的运行时键，非用户配置，不进 _PIPELINE_CONTROL_KEYS 过滤）
        if as_of is not None:
            params["_as_of"] = as_of

        # 注入非价格截面面板：整份按期字典，期匹配与滞后校验在策略包内完成
        # （策略包用 prices.index 数滞后交易日，Pipeline 不感知 panel_max_lag_days）
        for panel_name, periods in self._panels.items():
            params[f"_panel_{panel_name}"] = periods

        return params

    # ------------------------------------------------------------------
    # Step 4: Post-process（杠杆缩放 + 权重 cap）
    # ------------------------------------------------------------------

    def _run_post_process(
        self,
        weights_dict: Dict[str, float],
    ) -> Dict[str, float]:
        """后处理阶段：杠杆缩放 + 单资产权重上限.

        从 strategy_params 读取 max_leverage/max_total_leverage 与资产权重约束
        （取值口径见 :func:`app.allocation.runtime_params.resolve_weight_caps`）。
        已在内部处理杠杆的分配模型（schema.internal_leverage=True）跳过杠杆缩放。

        波动率定标不属于后处理：声明 vol_targeting_enabled 的策略由回测引擎
        在收益层逐日缩放（raw_ret × leverage.shift(1) 口径），权重层不介入。
        """
        # 优先通过 schema 声明判断，兜底用类名向后兼容
        has_internal_leverage = False
        try:
            schema = type(self._allocator).get_param_schema()
            has_internal_leverage = getattr(schema, 'internal_leverage', False)
        except Exception:
            has_internal_leverage = type(self._allocator).__name__ in _INTERNAL_LEVERAGE_IMPLS

        # 1. 杠杆缩放（跳过已在内部处理杠杆的策略）
        if not has_internal_leverage:
            max_lev = (
                self._strategy_params.get("max_leverage")
                or self._strategy_params.get("max_total_leverage")
            )
            if max_lev is not None:
                try:
                    max_lev_f = float(max_lev)
                    if max_lev_f > 1:
                        weights_dict = {k: v * max_lev_f for k, v in weights_dict.items()}
                except (TypeError, ValueError):
                    pass

        # 2. 资产权重约束（仅当 allocator schema 中声明了 weight_caps / max_weight_dict 时才生效，
        #    避免编制规则权重上限误伤 risk_parity 等不需要单资产约束的策略）
        allocator_schema_names = set()
        try:
            schema = type(self._allocator).get_param_schema()
            allocator_schema_names = {p.name for p in (schema.params or [])}
        except Exception:
            pass

        if allocator_schema_names.intersection(WEIGHT_CAPS_PARAM_NAMES):
            # 现名 weight_caps 为空时回退历史名 max_weight_dict，与策略内实现、
            # 回测门禁同一口径（各写一份会让空字典静默吃掉约束）
            weight_caps = resolve_weight_caps(self._strategy_params)
            for code, cap in weight_caps.items():
                if code not in weights_dict:
                    continue
                if cap <= 0:
                    if weights_dict[code] > 0:
                        logger.warning(
                            "[Pipeline] 资产 %s 的权重上限为 %s，将权重置为0。",
                            code, cap
                        )
                        weights_dict[code] = 0.0
                elif weights_dict[code] > cap:
                    weights_dict[code] = cap

        return weights_dict
