from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

import pandas as pd

from app.backtesting.signal import TargetWeightSignal

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.strategies.services import StrategyService


def _log_rebalance_weights(
    as_of: pd.Timestamp,
    final_weights: Dict[str, float],
    thscodes: list,
) -> None:
    """每次调仓时打印计算出的权重（资产代码、权重、权重和）。"""
    date_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)
    total = sum(final_weights.get(c, 0.0) for c in thscodes)
    print("\n" + "=" * 80)
    print(f"【调仓日权重】 日期: {date_str}  权重和: {total:.6f}")
    print("=" * 80)
    for code in thscodes:
        w = final_weights.get(code, 0.0)
        pct = w * 100
        mark = "  " if w == 0 else " *"
        print(f"  {mark} {code:20s}  {w:.6f}  ({pct:6.2f}%)")
    print("=" * 80 + "\n")


class IStrategy(ABC):
    """回测框架内部使用的策略接口.

    负责基于历史价格数据生成目标权重信号。
    """

    @abstractmethod
    def generate_target_weights(
            self,
            history_prices: pd.DataFrame,
            as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        """基于历史价格生成 as_of 时点的目标权重信号."""
        raise NotImplementedError

    def compute_monitoring_metrics(
            self,
            current_weights: pd.Series,
            history_prices: pd.DataFrame,
    ) -> Dict[str, Any]:
        """计算监控指标（如组合波动率等）。"""
        return {}


class StrategiesWrapper(IStrategy):
    """将 `strategies` 模块中的模型包装为回测可用的策略对象.

    要求被包装的策略实现 allocate(prices: DataFrame, **params) -> Series.
    """

    def __init__(self, strategy_impl: Any, params: Dict[str, Any]) -> None:
        self._impl = strategy_impl
        self._params = params

    def generate_target_weights(
            self,
            history_prices: pd.DataFrame,
            as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        try:
            # 验证历史数据不为空
            if history_prices.empty:
                raise ValueError(f"历史价格数据为空，无法生成目标权重（日期: {as_of}）")

            # 验证 history_prices 是 DataFrame
            if not isinstance(history_prices, pd.DataFrame):
                raise TypeError(
                    f"history_prices 必须是 pandas DataFrame，实际类型为 {type(history_prices)}。"
                    f"日期: {as_of}"
                )

            # 验证策略参数类型
            if not isinstance(self._params, dict):
                raise TypeError(
                    f"策略参数必须是字典类型，实际类型为 {type(self._params)}。"
                    f"参数值: {self._params}"
                )

            # 调用策略的 allocate 方法
            # 注意：prices 是 DataFrame，不是字典，访问列应该使用 prices[asset] 而不是 prices.get(asset)
            weights = self._impl.allocate(history_prices, **self._params)

            # 验证返回结果
            if weights is None:
                raise ValueError("策略 allocate 方法返回 None，无法生成目标权重")

            # 确保返回的是 Series
            if not isinstance(weights, pd.Series):
                raise TypeError(
                    f"策略 allocate 方法返回类型错误: 期望 pd.Series，实际为 {type(weights)}"
                )

            # 验证权重值
            if weights.empty:
                raise ValueError("策略返回的权重序列为空")

            # 转换为字典
            weights_dict = weights.to_dict()

            return TargetWeightSignal(time=as_of, target_weights=weights_dict)

        except AttributeError as e:
            error_msg = str(e)
            if "allocate" in error_msg:
                raise AttributeError(
                    f"策略类 {type(self._impl).__name__} 没有实现 allocate 方法。"
                    f"请确保策略类实现了 allocate(prices: DataFrame, **params) -> Series 接口。"
                ) from e
            # 特殊处理 'float' object has no attribute 'get' 错误
            if "'float' object has no attribute 'get'" in error_msg or "has no attribute 'get'" in error_msg:
                raise AttributeError(
                    f"策略代码错误: {error_msg}\n\n"
                    f"可能原因：\n"
                    f"1. 策略代码中使用了 prices.get(asset)，但 DataFrame 没有 .get() 方法\n"
                    f"   应该使用 prices[asset] 或 prices.loc[:, asset] 来访问列\n"
                    f"2. 策略代码中某个地方期望字典但得到了浮点数\n"
                    f"   请检查策略代码中所有使用 .get() 的地方，确保对象是字典类型\n"
                    f"3. 策略参数中某个值应该是字典但实际是浮点数\n\n"
                    f"调试信息：\n"
                    f"- 策略类型: {type(self._impl).__name__}\n"
                    f"- 执行日期: {as_of}\n"
                    f"- 历史数据形状: {history_prices.shape}\n"
                    f"- 历史数据列: {list(history_prices.columns)}\n"
                    f"- 策略参数: {self._params}\n\n"
                    f"请检查策略模板代码，特别是第270行附近的代码。"
                ) from e
            raise

        except TypeError as e:
            if "allocate()" in str(e) or "unexpected keyword" in str(e).lower():
                raise TypeError(
                    f"策略参数错误: {str(e)}\n"
                    f"策略参数: {self._params}\n"
                    f"请检查策略模型的参数配置是否正确。"
                ) from e
            raise

        except ValueError as e:
            # ValueError 通常是参数验证错误，保留原始错误信息（可能包含详细的诊断信息）
            error_msg = str(e)
            # 如果错误信息已经包含详细的诊断信息，直接抛出
            # 否则添加一些上下文信息
            if "可用数据情况" in error_msg or "建议：" in error_msg:
                # 错误信息已经包含详细诊断，直接抛出
                raise
            else:
                # 添加一些上下文信息
                raise ValueError(
                    f"{error_msg}\n\n"
                    f"调试信息：\n"
                    f"- 策略类型: {type(self._impl).__name__}\n"
                    f"- 执行日期: {as_of}\n"
                    f"- 历史数据形状: {history_prices.shape}\n"
                    f"- 历史数据列: {list(history_prices.columns)}\n"
                    f"- 策略参数: {self._params}"
                ) from e

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            # 特殊处理 'float' object has no attribute 'get' 错误
            if "'float' object has no attribute 'get'" in error_msg or "has no attribute 'get'" in error_msg:
                raise AttributeError(
                    f"策略代码错误: {error_msg}\n\n"
                    f"可能原因：\n"
                    f"1. 策略代码中使用了 prices.get(asset)，但 DataFrame 没有 .get() 方法\n"
                    f"   应该使用 prices[asset] 或 prices.loc[:, asset] 来访问列\n"
                    f"2. 策略代码中某个地方期望字典但得到了浮点数\n"
                    f"   请检查策略代码中所有使用 .get() 的地方，确保对象是字典类型\n"
                    f"3. 策略参数中某个值应该是字典但实际是浮点数\n\n"
                    f"调试信息：\n"
                    f"- 策略类型: {type(self._impl).__name__}\n"
                    f"- 执行日期: {as_of}\n"
                    f"- 历史数据形状: {history_prices.shape}\n"
                    f"- 历史数据列: {list(history_prices.columns)}\n"
                    f"- 策略参数: {self._params}\n\n"
                    f"请检查策略模板代码，特别是第270行附近的代码。"
                ) from e

            raise RuntimeError(
                f"策略执行失败 ({error_type}): {error_msg}\n"
                f"策略类型: {type(self._impl).__name__}\n"
                f"执行日期: {as_of}\n"
                f"历史数据形状: {history_prices.shape}\n"
                f"策略参数: {self._params}"
            ) from e

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        history_prices: pd.DataFrame,
    ) -> Dict[str, Any]:
        if hasattr(self._impl, "compute_monitoring_metrics"):
            return self._impl.compute_monitoring_metrics(
                current_weights=current_weights,
                prices=history_prices,
                **self._params
            )
        return {}

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> tuple[bool, float | None]:
        """代理调用底层的 check_volatility_trigger."""
        if hasattr(self._impl, "check_volatility_trigger"):
            merged_params = {**self._params, **params}
            return self._impl.check_volatility_trigger(
                current_weights=current_weights,
                prices=prices,
                **merged_params
            )
        return False, None

    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> pd.Series | None:
        """代理调用底层的 compute_volatility_reset_weights."""
        if hasattr(self._impl, "compute_volatility_reset_weights"):
            merged_params = {**self._params, **params}
            return self._impl.compute_volatility_reset_weights(
                current_weights=current_weights,
                prices=prices,
                **merged_params
            )
        return None


class StrategyServiceAdapter(IStrategy):
    """基于 StrategyService 的回测策略适配器.

    通过 config_id 调用 StrategyService 计算权重, 并包装为 TargetWeightSignal.
    在回测中使用时, 由 BacktestEngine 提供历史窗口的起止日期.
    
    注意：StrategyService.run_strategy() 是异步方法，
    但 BacktestEngine.run() 是同步的，因此不建议在生产环境中使用此适配器。
    建议直接使用 StrategiesWrapper 包装策略模型。
    """

    def __init__(
            self,
            strategy_service: "StrategyService",
            config_id: str,
    ) -> None:
        self._strategy_service = strategy_service
        self._config_id = config_id

        import warnings
        warnings.warn(
            "StrategyServiceAdapter 不适合在同步回测引擎中使用，"
            "建议使用 StrategiesWrapper 直接包装策略模型",
            DeprecationWarning,
            stacklevel=2
        )

    def generate_target_weights(
            self,
            history_prices: pd.DataFrame,
            as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        """生成目标权重.
        
        注意：此方法在同步上下文中调用异步方法，不建议使用。
        仅保留以保持API兼容性。
        """
        if history_prices.empty:
            raise ValueError("history_prices 为空, 无法生成目标权重")

        start_date = history_prices.index[0].strftime("%Y-%m-%d")
        end_date = history_prices.index[-1].strftime("%Y-%m-%d")
        thscodes = list(history_prices.columns)

        # 警告：在同步上下文中调用异步方法会失败
        # 这里仅为了保持接口兼容性，实际使用中不应调用
        raise RuntimeError(
            "StrategyServiceAdapter 不支持在同步回测引擎中使用。"
            "StrategyService.run_strategy() 是异步方法，但 BacktestEngine.run() 是同步的。"
            "请使用 StrategiesWrapper 直接包装策略模型："
            "strategy = StrategiesWrapper(strategy_impl, params)"
        )


class StrategyAdapterWithSelection(IStrategy):
    """支持资产选择的策略适配器.
    
    在回测时，如果策略启用了资产选择（如动量选择器），
    会先执行资产选择，然后基于选中的资产计算权重。
    """

    def __init__(
            self,
            base_strategy: StrategiesWrapper,
            thscodes: list[str],
            enable_selection: bool,
            selection_info: Dict[str, Any]
    ) -> None:
        """初始化适配器.
        
        Args:
            base_strategy: 基础策略包装器
            thscodes: 候选资产池
            enable_selection: 是否启用资产选择
            selection_info: 选择器配置信息
                - selector_type: 选择器类型（如 "momentum"）
                - n_assets: 选择资产数量
                - n_assets_for_allocation: 在已选池中再选出的参与分配数量（未设或>=n_assets则全部参与，其余本次置0）
                - selection_params: 选择器参数
        """
        self._base_strategy = base_strategy
        self._thscodes = thscodes
        self._enable_selection = enable_selection
        self._selection_info = selection_info or {}

        # 初始化选择服务
        if enable_selection:
            from app.selection.services.selection_service import SelectionService
            from app.selection.selectors.momentum import MomentumSelector
            from app.selection.selectors.momentum_reversal import MomentumReversalSelector
            from app.selection.selectors.reference_engine import ReferenceEngineSelector

            self._selection_service = SelectionService()
            self._selection_service.register("momentum", MomentumSelector)
            self._selection_service.register("momentum_reversal", MomentumReversalSelector)
            self._selection_service.register("reference_engine", ReferenceEngineSelector)

    def generate_target_weights(
            self,
            history_prices: pd.DataFrame,
            as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        """生成目标权重（支持资产选择）.
        
        如果启用资产选择：
        1. 先执行资产选择，从候选池中筛选TopN资产
        2. 基于选中的资产计算权重
        3. 返回包含所有候选资产的权重（未选中的为0）
        
        如果未启用资产选择：
        直接调用基础策略的generate_target_weights方法
        """
        asset_tags_for_allocate = {}  # 选择器产出的资产标签(both/momentum/reversal)，传给策略用于风险预算 2/8、1/8
        if self._enable_selection:
            # 选择器类型：hybrid / momentum_reversal / reversal → momentum_reversal（7+1 逻辑，与 investmentA 一致）
            raw_selector_type = self._selection_info.get("selector_type", "momentum")
            if raw_selector_type == "reference_engine":
                selector_type = "reference_engine"
            elif raw_selector_type in ("reversal", "momentum_reversal", "hybrid"):
                selector_type = "momentum_reversal"
            else:
                selector_type = raw_selector_type
            n_selected = self._selection_info.get("n_assets", len(self._thscodes))
            selection_params = dict(self._selection_info.get("selection_params", {}))

            base_params = self._base_strategy._params
            if selector_type == "reference_engine":
                selection_params.setdefault("min_history_days", base_params.get("min_history_days", 260))
                selection_params.setdefault("n_momentum", 7)
                selection_params.setdefault("n_reversal", 1)
            elif selector_type == "momentum_reversal":
                selection_params.setdefault("min_history_days", base_params.get("min_history_days", 260))
                selection_params.setdefault("n_momentum", 7)
                selection_params.setdefault("n_reversal", 1)
                selection_params.setdefault("momentum_windows", base_params.get("momentum_windows", "20,60,120,250"))
                selection_params.setdefault("macd_windows", base_params.get("macd_windows", "40,80,120,160"))
                selection_params.setdefault("reversal_windows", base_params.get("reversal_windows", "10,22"))
            else:
                if "min_history_days" in base_params:
                    selection_params.setdefault("min_history_days", base_params["min_history_days"])
                if "momentum_windows" in base_params:
                    selection_params.setdefault("momentum_windows", base_params["momentum_windows"])
                if "tie_break_window" in base_params:
                    selection_params.setdefault("tie_break_window", base_params["tie_break_window"])

            try:
                # 将调仓日期传入选择器，便于打印时标注
                selection_params["_rebalance_date"] = as_of
                # 执行资产选择
                selection_result = self._selection_service.select_assets(
                    selector_type=selector_type,
                    prices=history_prices,
                    n_assets=n_selected,
                    **selection_params
                )

                selected_assets = selection_result.selected_assets
                asset_tags_for_allocate = getattr(selection_result, "tags", None) or {}

                # 混合动量导出：收集资产选择结果
                sel_collector = self._selection_info.get("_selection_collector")
                if sel_collector is not None:
                    tags = asset_tags_for_allocate
                    mom_sel = [a for a in tags if tags.get(a) in ("momentum", "both")]
                    rev_sel = [a for a in tags if tags.get(a) in ("reversal", "both")]
                    ranking_df = getattr(selection_result, "ranking", None)
                    valid = list(ranking_df.index) if ranking_df is not None and not ranking_df.empty else list(selected_assets)
                    sel_collector.append({
                        "calc_date": as_of,
                        "valid_assets": valid,
                        "momentum_selected": mom_sel,
                        "reversal_selected": rev_sel,
                        "final_selected": selected_assets,
                        "ranking_df": ranking_df,
                    })

                logger.info(
                    "[权重计算-选择] 调仓日 as_of=%s | selected_assets=%s | tags=%s",
                    as_of, selected_assets, asset_tags_for_allocate
                )

                # 如果选中的资产为空，使用所有资产
                if not selected_assets:
                    selected_assets = list(history_prices.columns)

                # 检查选中的资产数量
                # 如果资产数量少于2个，且策略需要多个资产（如target_return模式），给出警告
                if len(selected_assets) < 2:
                    import warnings
                    warnings.warn(
                        f"资产选择后只剩下 {len(selected_assets)} 个资产，"
                        f"某些优化模式（如target_return）可能需要至少2个资产。"
                        f"如果优化失败，请增加资产选择数量或切换到其他优化模式。"
                    )

                # 在已选资产池上再跑一次选择模型，决定本次调仓哪些参与分配、哪些置0
                # momentum_reversal / reference_engine 已按 7+1 产出 7～8 个资产，不再做池内再选
                n_for_alloc = None if selector_type in ("momentum_reversal", "reference_engine") else self._selection_info.get("n_assets_for_allocation")
                if (
                    n_for_alloc is not None
                    and len(selected_assets) > 1
                    and 1 <= int(n_for_alloc) < len(selected_assets)
                ):
                    n_active = int(n_for_alloc)
                    try:
                        # selection_params 已含 _rebalance_date
                        within_pool_result = self._selection_service.select_assets(
                            selector_type=selector_type,
                            prices=history_prices[selected_assets],
                            n_assets=n_active,
                            **selection_params
                        )
                        active_assets = within_pool_result.selected_assets
                    except Exception as e:
                        import warnings
                        warnings.warn(
                            f"在已选池内再选择失败({e})，本次使用全部已选资产参与分配"
                        )
                        active_assets = selected_assets
                else:
                    active_assets = selected_assets

                # 只保留参与分配的资产的历史数据（未参与的本轮置0）
                selected_history = history_prices[active_assets] if active_assets else history_prices[selected_assets]
                # 未做池内再选时 active_assets 已在上方 else 中设为 selected_assets
            except Exception as e:
                # 如果选择失败，使用所有资产并记录警告
                import warnings
                warnings.warn(f"资产选择失败: {str(e)}，使用所有资产")
                selected_assets = list(history_prices.columns)
                active_assets = selected_assets
                selected_history = history_prices
        else:
            # 未启用资产选择，使用所有资产
            selected_assets = self._thscodes
            active_assets = self._thscodes
            selected_history = history_prices

        # 调用基础策略计算权重（仅基于参与分配的资产；已选但未参与的本轮为0）
        # 权重计算接收参数：selected_history（仅 n_assets 列）、strategy_params（不含选择器相关键）
        original_params = self._base_strategy._params.copy()
        # 注意：min_history_days 需传给 allocate，否则 selection 用模型配置(如100)而 allocate 用默认260，会导致选中资产被分配模型排除
        _exclude = [
            'enable_momentum_selection', 'selector_type', 'asset_selection_count', 'n_assets_for_allocation',
            'momentum_windows', 'macd_windows', 'tie_break_window',
            'n_momentum', 'n_reversal', 'reversal_windows',
        ]
        strategy_params = {k: v for k, v in original_params.items()
                          if not k.startswith('_') and k not in _exclude}
        if asset_tags_for_allocate:
            strategy_params["_asset_tags"] = asset_tags_for_allocate
        # reference_engine：以 step2 为核心，需传入入选矩阵行和完整价格
        use_ref_engine = self._selection_info.get("use_reference_engine", False)
        if use_ref_engine:
            strategy_params["_use_reference_engine"] = True
            selection_row = {}
            for code in self._thscodes:
                tag = asset_tags_for_allocate.get(code, "")
                if tag == "both":
                    selection_row[code] = 2
                elif tag in ("momentum", "reversal"):
                    selection_row[code] = 1
                else:
                    selection_row[code] = 0
            strategy_params["_selection_row"] = selection_row
        # 启用动量选择时透明化打印权重计算过程
        trace_output = {}
        if self._enable_selection:
            strategy_params["_enable_weight_trace"] = True
            strategy_params["_trace_output"] = trace_output

        # 透明化：打印传入 allocate 的资产与标签
        if self._enable_selection:
            logger.info(
                "[权重计算-入口] 调仓日 as_of=%s | active_assets=%s | asset_tags=%s",
                as_of, active_assets, asset_tags_for_allocate
            )

        # reference_engine 需完整价格；其他选择器仅传入选中的历史数据
        allocate_prices = history_prices if use_ref_engine else selected_history
        weights_series = self._base_strategy._impl.allocate(allocate_prices, **strategy_params)

        # 转换为字典
        if isinstance(weights_series, pd.Series):
            weights_dict = weights_series.to_dict()
        else:
            weights_dict = weights_series if isinstance(weights_series, dict) else {}

        # 保存 allocate 原始返回（cap 前），用于 0 权重诊断
        weights_before_cap = dict(weights_dict) if self._enable_selection else {}

        # 透明化：打印 allocate 返回的权重
        if self._enable_selection:
            nonzero = [(c, v) for c, v in weights_dict.items() if v is not None and float(v) > 1e-9]
            logger.info(
                "[权重计算-出口] allocate 返回 %d 个资产 | 权重>0: %s",
                len(weights_dict),
                [(c, f"{float(v)*100:.2f}%") for c, v in sorted(nonzero, key=lambda x: -x[1])]
            )

        # 若分配模型返回的资产少于参与分配的资产，说明部分资产被策略内部排除（常见原因：数据不足、波动率为0等）
        alloc_keys = set(weights_dict.keys())
        active_set = set(active_assets) if active_assets else set(selected_assets) if selected_assets else set()
        if active_set and alloc_keys != active_set:
            missing = sorted(active_set - alloc_keys)
            if missing:
                impl_name = type(self._base_strategy._impl).__name__
                logger.warning(
                    "[调仓] 分配模型 %s 未返回以下资产的权重(本轮为0): %s。"
                    "常见原因：有效数据不足、波动率为0、协方差含NaN等，请检查资产历史数据或策略参数。",
                    impl_name, missing
                )

        # 动量选择策略下：若设置了杠杆倍数，按杠杆缩放权重，不归一化（资产权重和可为杠杆倍数）
        # 注意：risk_budget_target_vol 等策略的 allocate 已在内部使用 max_total_leverage，
        # 输出权重和已可达 max_total_leverage（如 4 倍），此处不再乘杠杆，否则会导致双重缩放
        # 进而被风控压回后等效归一化到 100%，违背「杠杆放开到 4 倍时总比重超过 100%」的要求
        impl_cls = type(self._base_strategy._impl).__name__
        skip_leverage_scale = impl_cls == "RiskBudgetTargetVolStrategy"
        if not skip_leverage_scale:
            max_lev = original_params.get("max_leverage") or original_params.get("max_total_leverage")
            if max_lev is not None:
                try:
                    max_lev_f = float(max_lev)
                    if max_lev_f > 1:
                        weights_dict = {k: v * max_lev_f for k, v in weights_dict.items()}
                except (TypeError, ValueError):
                    pass

        # 按浙银理财编制规则（或用户配置）限制单资产权重上限，避免杠杆缩放后超出
        max_weight_dict = original_params.get("max_weight_dict")
        if isinstance(max_weight_dict, dict) and max_weight_dict:
            default_max = 0.10  # 与 zy_document 默认一致
            for code in list(weights_dict.keys()):
                cap = max_weight_dict.get(code, default_max)
                try:
                    cap_f = float(cap)
                    if cap_f <= 0 and weights_dict.get(code, 0) > 0:
                        logger.warning(
                            "[调仓] 资产 %s 的 max_weight_dict 上限为 %s，将权重置为0。"
                            "编制规则应为 ZQGZ10=60%%/ZQGZ2=90%%，请检查前端传参或策略配置。",
                            code, cap
                        )
                    if weights_dict[code] > cap_f:
                        weights_dict[code] = cap_f
                except (TypeError, ValueError):
                    pass

        # 创建TargetWeightSignal
        temp_signal = TargetWeightSignal(time=as_of, target_weights=weights_dict)

        # 确保返回的权重包含所有候选池资产（未选中的为0）
        target_weights = temp_signal.target_weights.copy()

        # 为所有候选资产初始化权重（未选中的为0）
        for code in self._thscodes:
            if code not in target_weights:
                target_weights[code] = 0.0

        # 只保留候选池中的资产
        final_weights = {code: target_weights.get(code, 0.0) for code in self._thscodes}

        # 混合动量导出：收集权重计算结果
        weight_collector = self._selection_info.get("_weight_collector")
        if weight_collector is not None and isinstance(trace_output, dict):
            tr = trace_output
            risk_budgets = {}
            asset_vols = {}
            initial_weights = tr.get("_weights_init", {})
            scaled_weights = tr.get("_weights_scaled", {})
            for code in self._thscodes:
                info = tr.get(code)
                if isinstance(info, dict):
                    risk_budgets[code] = info.get("risk_budget", 0)
                    asset_vols[code] = info.get("vol", float("nan"))
                else:
                    risk_budgets[code] = 0
                    asset_vols[code] = float("nan")
            # 入选状态 0/1/2（与资产选择一致）
            selection_status = {}
            for code in self._thscodes:
                tag = asset_tags_for_allocate.get(code, "")
                if tag == "both":
                    selection_status[code] = 2
                elif tag in ("momentum", "reversal"):
                    selection_status[code] = 1
                else:
                    selection_status[code] = 0
            weight_collector.append({
                "calc_date": as_of,
                "final_weights": final_weights,
                "portfolio_vol": tr.get("_portfolio_vol", 0.0),
                "scale": tr.get("_final_scale", 1.0),
                "total_leverage": sum(final_weights.values()),
                "risk_budgets": risk_budgets,
                "asset_vols": asset_vols,
                "initial_weights": {c: initial_weights.get(c, 0) for c in self._thscodes},
                "scaled_weights": {c: scaled_weights.get(c, 0) for c in self._thscodes},
                "selection_status": selection_status,
            })

        # 每次调仓打印计算出的权重（便于核对）
        _log_rebalance_weights(as_of, final_weights, self._thscodes)

        # 每个资产结果说明（含未选中、被排除、已分配及权重计算过程）
        if self._enable_selection:
            print("\n" + "=" * 80)
            print("【每个资产结果说明】")
            print("=" * 80)
            mwd = original_params.get("max_weight_dict") or {}
            if isinstance(mwd, dict):
                bond_max = {k: mwd.get(k, "未配置") for k in ("ZQGZ10", "ZQGZ2")}
                print(f"  max_weight_dict 后端配置(国债): ZQGZ10={bond_max.get('ZQGZ10')} ZQGZ2={bond_max.get('ZQGZ2')} (编制规则应为0.6/0.9)")
            active_set = set(active_assets) if active_assets else set()
            alloc_set = set(weights_dict.keys())
            max_lev = original_params.get("max_leverage") or original_params.get("max_total_leverage")
            max_lev_f = float(max_lev) if max_lev is not None else 1.0
            for code in self._thscodes:
                w = final_weights.get(code, 0.0)
                tr = trace_output.get(code) if trace_output else None
                if code not in active_set:
                    print(f"  {code}: 未选中(选择器置0)")
                    print(f"    → 最终权重: 0.00%")
                elif tr and tr.get("status") == "excluded":
                    print(f"  {code}: 选中但分配模型排除")
                    print(f"    {tr.get('reason', '')}")
                    print(f"    → 最终权重: 0.00%")
                elif tr and tr.get("status") == "valid":
                    rb, vol_val, wi, fs, wb = tr.get("risk_budget"), tr.get("vol"), tr.get("w_init"), tr.get("final_scale"), tr.get("weight")
                    tv = tr.get("target_vol", 0.05)
                    max_w = tr.get("max_weight")
                    w_raw = weights_before_cap.get(code) if weights_before_cap else wb
                    print(f"  {code}: 已分配")
                    print(f"    有效数据: {tr.get('data_days')}天 | 标签: {tr.get('tag')} | 风险预算: {rb:.4f} | max_weight_dict上限: {max_w}")
                    print(f"    波动率: {vol_val:.6f} | w_init = {rb:.4f} * {tv} / {vol_val:.4f} = {wi:.4f}")
                    print(f"    缩放: {wi:.4f} * {fs:.4f} = {wb:.4f}")
                    if max_lev_f > 1:
                        scaled = wb * max_lev_f
                        print(f"    杠杆: {wb:.4f} * {max_lev_f} = {scaled:.4f}")
                    print(f"    → 最终权重: {w:.6f} ({w*100:.2f}%)")
                    if w <= 0 and (wb > 0 or (w_raw is not None and float(w_raw) > 0)):
                        print(f"    ※ 分配模型输出={wb:.4f}，allocate原始返回={w_raw}，最终为0。可能原因: final_scale=0 或 max_weight_dict cap=0")
                    elif w <= 0 and wb <= 0:
                        zero_reason = trace_output.get("_final_scale_zero_reason") if trace_output else None
                        if zero_reason:
                            print(f"    ※ 分配模型输出即为0。具体原因: final_scale=0 ← {zero_reason}")
                        else:
                            print(f"    ※ 分配模型输出即为0。可能原因: final_scale=0 导致所有权重为0，请检查步骤6是否有 vol_scale/leverage_scale/weight_scale 为0")
                else:
                    w_raw = weights_before_cap.get(code) if weights_before_cap else None
                    in_alloc = code in alloc_set
                    print(f"  {code}: 已分配 → {w*100:.2f}%")
                    # 权重为0或接近0时必打诊断（含浮点误差如 1e-10 显示为 0.00% 的情况）
                    effectively_zero = w <= 0 or (w is not None and float(w) < 1e-9)
                    if effectively_zero:
                        cap_val = (mwd.get(code) if isinstance(mwd, dict) else None) if mwd else None
                        w_raw_str = f"{float(w_raw):.6f}" if w_raw is not None else "未返回"
                        print(f"    【为何为0】 allocate返回={w_raw_str}, 在alloc_set={in_alloc}, max_weight_dict={cap_val}")
                        zero_reason = trace_output.get("_final_scale_zero_reason") if trace_output else None
                        if in_alloc and (w_raw is None or float(w_raw) < 1e-9):
                            if zero_reason:
                                print(f"    ※ 具体原因: final_scale=0 ← {zero_reason}")
                            else:
                                print(f"    ※ 分配模型(risk_budget)输出即为0。原因: final_scale=0 → 检查步骤6-三重约束缩放输出")
                        elif in_alloc and w_raw is not None and float(w_raw) >= 1e-9:
                            print(f"    ※ 分配模型输出{w_raw:.4f}>0，但最终为0 → 检查 strategy_api 层 cap 是否将权重合规至0")
                        elif not in_alloc:
                            print(f"    ※ 未在 alloc_set(allocate未返回该资产) → 分配模型已排除，常见原因: data_days不足、波动率为0")
                print()
            print("=" * 80 + "\n")

        return TargetWeightSignal(time=as_of, target_weights=final_weights)

    def compute_monitoring_metrics(
            self,
            current_weights: pd.Series,
            history_prices: pd.DataFrame,
    ) -> Dict[str, Any]:
        """计算监控指标."""
        return self._base_strategy.compute_monitoring_metrics(
            current_weights=current_weights,
            history_prices=history_prices
        )

    def check_volatility_trigger(
            self,
            current_weights: pd.Series,
            prices: pd.DataFrame,
            **params
    ) -> tuple[bool, float]:
        """检查波动率触发（合并策略参数，确保 vol_reset_threshold 等生效）."""
        merged = {**getattr(self._base_strategy, "_params", {}), **params}
        return self._base_strategy.check_volatility_trigger(
            current_weights=current_weights,
            prices=prices,
            **merged
        )

    def compute_volatility_reset_weights(
            self,
            current_weights: pd.Series,
            prices: pd.DataFrame,
            **params
    ) -> pd.Series | None:
        """计算波动率重置权重（合并策略参数）."""
        merged = {**getattr(self._base_strategy, "_params", {}), **params}
        return self._base_strategy.compute_volatility_reset_weights(
            current_weights=current_weights,
            prices=prices,
            **merged
        )
