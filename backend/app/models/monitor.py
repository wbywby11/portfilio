"""
监控模块数据模型
用于日常组合监控、主观调仓和日报生成
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class OverrideStatus(str, Enum):
    """主观调仓状态"""
    PENDING = "pending"      # 待执行
    EXECUTED = "executed"    # 已执行
    CANCELLED = "cancelled"  # 已取消


class OperationType(str, Enum):
    """操作指令类型"""
    MONTHLY_REBALANCE = "monthly_rebalance"  # 月度调仓（目标仓位）
    VOL_RESET = "vol_reset"                  # 波动率重置（仓位调整建议）
    SUBJECTIVE = "subjective"                # 主观调仓（额外调仓/比例优化）


class OperationStatus(str, Enum):
    """操作指令状态"""
    PENDING = "pending"        # 待执行（信号已生成，未到执行日）
    EXECUTED = "executed"      # 已执行（执行日落地）
    SUPERSEDED = "superseded"  # 已被主观比例优化替代
    CANCELLED = "cancelled"    # 已取消（信号失效/冲突跳过）


class BatchStatus(str, Enum):
    """监控运行批次状态（与 monitor_task_service 的任务状态同值，便于互相对账）"""
    PENDING = "pending"          # 已创建，未开始计算
    RUNNING = "running"          # 计算中
    PAUSED = "paused"            # 主观预设步进暂停（仍有待推演交易日）
    COMPLETED = "completed"      # 计算完成且已落库，展示侧只认这一种
    FAILED = "failed"            # 计算失败
    INTERRUPTED = "interrupted"  # 进程重启导致中断


# 展示侧可见的批次状态：resolve_batch 只返回 COMPLETED，
# 计算中/失败/中断的批次对展示不可见，页面自动回落上一个 completed 批次，不空窗。
VISIBLE_BATCH_STATUSES = (BatchStatus.COMPLETED.value,)


class BatchKind(str, Enum):
    """监控对象类型（与 monitor_id 的三种形态一一对应）"""
    STRATEGY = "strategy"      # 单策略模型监控
    PORTFOLIO = "portfolio"    # 投资组合监控
    RESEARCHER = "researcher"  # 研究员独立策略（sharpe_18 / hybrid_12）


class BatchRunMode(str, Enum):
    """批次触发方式"""
    INIT = "init"    # 初始化：从起点单段跑完整个区间
    DAILY = "daily"  # 日常推进：单策略增量续接 / 组合全量重跑
    RANGE = "range"  # 区间推演（主观预设步进）


# 批次化改造前的存量文档统一挂这个批次号（由 index_bootstrap 启动时补齐），
# 保证旧数据在新查询口径下仍可读，不需单独跑迁移脚本。
LEGACY_BATCH_ID = "legacy"



class NavHistoryPoint(BaseModel):
    """净值历史点"""
    date: str = Field(..., description="日期 (YYYY-MM-DD)")
    nav: float = Field(..., description="净值")
    
    class Config:
        populate_by_name = True


class EventLogEntry(BaseModel):
    """事件日志条目（声明口径，与 app.backtesting.events 规范对齐）

    字段与 ``daily_stepper`` 实际写入的键一致。历史上本模型定义的是
    ``event_type``/``details`` 口径（仅组合监控路径在用），与通用步进路径
    写的 ``type``/``stage``/``calc_date`` 互不相认，导致消费方各认一套。
    现已统一为单一规范，异构存量数据由 ``events.normalize_event`` 映射。

    ``MonitorState.event_log`` 仍声明为 ``List[Dict[str, Any]]`` 而不引用本模型：
    存量文档存在两套旧口径，开启校验会让旧状态加载失败；本模型作为写入
    契约与接口文档使用。
    """
    date: str = Field(..., description="事件日期 (YYYY-MM-DD)")
    type: str = Field(..., description="事件类型: init/monthly/vol_reset/subjective")
    stage: str = Field("execute", description="阶段: trigger/execute/skipped（仅 vol_reset 会跨日）")
    seq: Optional[int] = Field(None, description="同日内第几条事件，从 0 起")
    signal_date: Optional[str] = Field(None, description="信号日（月度=计算日，波动率重置=触发日）")
    execute_date: Optional[str] = Field(None, description="计划执行日（仅 vol_reset 触发事件）")
    description: str = Field("", description="事件描述")
    trading_cost: Optional[float] = Field(None, description="本次事件产生的交易费用")
    old_weights: Optional[Dict[str, float]] = Field(None, description="调仓前权重")
    new_weights: Optional[Dict[str, float]] = Field(None, description="调仓后权重")
    vol_trigger: Optional[float] = Field(None, description="触发波动率（vol_reset）")
    scale_factor: Optional[float] = Field(None, description="缩放因子（vol_reset）")
    override_id: Optional[str] = Field(None, description="关联的主观调仓指令 ID")
    
    class Config:
        populate_by_name = True


class PendingRebalance(BaseModel):
    """待执行调仓信息"""
    trigger_date: str = Field(..., description="触发日期")
    reason: str = Field(..., description="调仓原因（如 monthly, vol_reset, subjective）")
    target_weights: Dict[str, float] = Field(default_factory=dict, description="目标权重")
    
    class Config:
        populate_by_name = True


class MonitorOperation(BaseModel):
    """
    监控操作指令（策略维度的操作记录）
    存入 MongoDB monitor_operations 集合

    生命周期：信号日写 pending → 执行日落地转 executed；
    被主观比例优化替代时原指令转 superseded，主观指令携带 linked_operation_id。
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v

    monitor_id: str = Field(..., description="监控实例 ID")
    # 批次归属：指令属于哪一次跑批。新批次从零开始，旧批次指令封存仍可查；
    # None 仅存在于启动补齐前的瞬态，读取侧按 LEGACY_BATCH_ID 归一。
    batch_id: Optional[str] = Field(None, description="所属运行批次号（monitor_batches.batch_id）")
    strategy_key: str = Field(..., description="策略维度键（单策略为 monitor_id；组合为子策略 model_id 或 portfolio）")
    strategy_name: str = Field("", description="策略展示名")
    op_type: str = Field(..., description="指令类型: monthly_rebalance/vol_reset/subjective")
    signal_date: str = Field(..., description="信号生成日期 (YYYY-MM-DD)")
    execute_date: str = Field(..., description="执行日期 (YYYY-MM-DD)")
    status: str = Field(OperationStatus.PENDING.value, description="状态: pending/executed/superseded/cancelled")

    # 权重与建议明细（权重为小数形式）
    target_weights: Dict[str, float] = Field(default_factory=dict, description="目标权重 {资产键: 权重}")
    prev_weights: Dict[str, float] = Field(default_factory=dict, description="执行前权重 {资产键: 权重}")
    suggestion: Dict[str, Any] = Field(default_factory=dict, description="操作建议明细（如波动率重置的当前波动/阈值/建议杠杆）")

    # 组合层两级拆解（仅 strategy_key=portfolio 指令填充）
    strategy_weights: Dict[str, float] = Field(default_factory=dict, description="组合层：当日子策略组合比重 {子策略键: 权重}，合计可 >1（等效杠杆）")
    prev_strategy_weights: Dict[str, float] = Field(default_factory=dict, description="组合层：调整前子策略组合比重")
    strategy_breakdown: List[Dict[str, Any]] = Field(default_factory=list, description="组合层：穿透拆解 [{strategy_key, strategy_name, weight, asset_weights}]")
    prev_strategy_breakdown: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="组合层：上一调仓日的同级穿透拆解；首条指令为空。"
                    "资产行变动须按策略归属，仅凭穿透后的 prev_weights 无法拆回子策略",
    )

    # 主观关联
    source: str = Field("auto", description="来源: auto（系统信号）/subjective（主观）")
    linked_operation_id: Optional[str] = Field(None, description="挂接的原待执行指令 ID（比例优化模式）")
    override_ref: Optional[str] = Field(None, description="关联的主观调仓指令 override_id")

    # 补充说明：权威存储于 monitor_operation_remarks（按业务键挂靠），
    # 本字段仅用于读取回填，不写入 monitor_operations 文档
    remark: Optional[str] = Field(None, description="补充说明（独立集合按业务键挂靠）")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        # remark 权威存储在 monitor_operation_remarks，不写入 ops 文档
        data.pop("remark", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorOperation":
        """从字典创建实例"""
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


class MonitorBatch(BaseModel):
    """监控运行批次（monitor_batches 集合）

    一次运行（初始化 / 日常推进 / 区间推演）一条，``batch_id`` 串联本次运行的
    全部产物：状态文档、净值曲线（``backtest_records`` 中 ``run_kind=monitor``）、
    日报、操作指令、风险预警、绩效缓存。

    计算与展示的分界点就在 ``status``：展示端点只读 ``completed`` 的最新批次，
    跑批写新批次，两者不互相阻塞；跑批失败或进行中时页面自动回落上一个
    ``completed`` 批次，不会出现空窗或半成品数据。

    ``config_snapshot`` 在批次创建时一次性固化（参数 / 版本 / 成交口径 / 资产池），
    运行期间不回读策略库，因此事后可完整重现本次跑批的输入。
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v

    batch_id: str = Field(..., description="批次号（uuid4().hex），全局唯一，本次运行的串联键")
    monitor_id: str = Field(..., description="监控实例 ID（原值，三种形态之一）")
    kind: str = Field(BatchKind.STRATEGY.value, description="监控对象类型: strategy/portfolio/researcher")
    run_mode: str = Field(BatchRunMode.INIT.value, description="触发方式: init/daily/range")
    status: str = Field(BatchStatus.PENDING.value, description="批次状态: pending/running/paused/completed/failed/interrupted")

    # 关联信息
    task_id: Optional[str] = Field(None, description="关联 monitor_tasks.task_id；同步模式为 null")
    source_model_id: Optional[str] = Field(None, description="strategy_models._id；kind=researcher 时为 null")
    researcher_code: Optional[str] = Field(None, description="研究员策略代码 sharpe_18/hybrid_12；其余为 null")
    parent_batch_id: Optional[str] = Field(
        None,
        description="增量推进时指向的上一批次（fold 状态与 pending 主观指令从它继承）；init 为 null"
    )
    backtest_record_id: Optional[str] = Field(
        None,
        description="本批次写入 backtest_records 的记录 ID（run_kind=monitor，仅模型轨）"
    )

    # 区间与数据时效
    start_date: Optional[str] = Field(None, description="本批次覆盖区间起点 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="本批次覆盖区间终点；running 时为 null，完成后回填")
    data_date: Optional[str] = Field(None, description="本次跑批使用的行情最新日期（幂等判重用）")

    # 快照与摘要
    config_snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="本次生效配置快照（template_code/strategy_params/config_versions/execution_policy/asset_codes/sub_strategies）"
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="批次摘要指标（nav/day_count/年化指标/回撤/调仓次数等），完成后回填，不复制曲线"
    )

    # 软删除：DELETE /batches/{id} 只置位不物理删，保留审计痕迹
    deleted: bool = Field(False, description="软删除标记；resolve_batch 跳过已删批次")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="批次创建时间")
    started_at: Optional[datetime] = Field(None, description="计算开始时间")
    finished_at: Optional[datetime] = Field(None, description="终态时间")
    duration_ms: Optional[int] = Field(None, description="计算耗时（毫秒）")
    error: Optional[Dict[str, Any]] = Field(None, description="失败信息 {message, traceback}")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorBatch":
        """从字典创建实例"""
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)



class MonitorState(BaseModel):
    """
    组合监控状态
    存入 MongoDB monitor_states 集合
    对应 monitor_vs 的 PortfolioState
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v
    monitor_id: str = Field(..., description="监控实例 ID（如 'default'）")
    # 一个批次一条状态文档（{monitor_id, batch_id} 唯一）。run_mode=daily 的增量推进
    # 从 parent_batch_id 对应文档读 fold 状态起步，结果写入新批次文档，不覆盖父批次。
    batch_id: Optional[str] = Field(None, description="所属运行批次号（monitor_batches.batch_id）")
    date: str = Field(..., description="当前日期 (YYYY-MM-DD)")
    
    # 净值相关
    nav: float = Field(1.0, description="当前净值（基于人民币）")
    nav_base: float = Field(1.0, description="基准净值（上次调仓日的净值）")
    day_count: int = Field(0, description="从基日起的运行天数（包含所有处理日）")
    trade_day_count: int = Field(0, description="交易日计数（仅计入 trade_dates 中的日期，与原型 trade_day_idx 对齐）")
    
    # 持仓信息
    positions_cny: Dict[str, float] = Field(
        default_factory=dict, 
        description="人民币持仓金额 {资产名: CNY金额}"
    )
    positions_local: Dict[str, float] = Field(
        default_factory=dict, 
        description="本币持仓金额 {资产名: 本币金额}"
    )
    apl_local: Dict[str, float] = Field(
        default_factory=dict, 
        description="本币累计损益 {资产名: PnL}"
    )
    positions_cny_base: Dict[str, float] = Field(
        default_factory=dict,
        description="调仓日基准CNY持仓 = nav × weight（与原型 BacktestState.positions_cny_base 对齐）",
    )

    # 传统持仓模型（主观策略：与回测 engine.py 对齐 NAV = cash + Σ(qty × close)）
    cash: float = Field(0.0, description="现金余额（传统持仓模型，与回测 Position.cash 对齐）")
    quantities: Dict[str, float] = Field(
        default_factory=dict,
        description="资产持仓数量 {asset_code: qty}（传统持仓模型）",
    )
    last_prices: Dict[str, float] = Field(
        default_factory=dict,
        description="上次有效收盘价 {asset_code: price}（任务#12：节假日/停牌价格回退）",
    )
    
    # 权重与调仓
    target_weights: Dict[str, float] = Field(
        default_factory=dict, 
        description="当前目标权重 {资产名: 权重}"
    )
    last_rebalance_date: Optional[str] = Field(
        None, 
        description="上次调仓日期 (YYYY-MM-DD)"
    )
    last_rebalance_fx: Dict[str, float] = Field(
        default_factory=dict, 
        description="上次调仓日汇率 {资产名: 汇率}"
    )
    pending_rebalance: Optional[Dict[str, Any]] = Field(
        None, 
        description="待执行调仓信息"
    )
    
    # 费用统计
    total_trading_cost: float = Field(0.0, description="累计交易费用")
    total_replication_cost: float = Field(0.0, description="累计复制费用")
    
    # 波动率重置
    vol_reset_count: int = Field(0, description="波动率重置次数")
    # 分段运行（run_daily / run_range）的 fold 续接状态：波动率重置的
    # 「触发日到执行日间存在其他信号则跳过」规则依赖历史信号日集合，
    # 不落库就会在每次增量运行时丢失。存量文档无该键时取默认空列表。
    vol_signal_dates: List[str] = Field(
        default_factory=list,
        description="已触发的波动率信号日 YYYY-MM-DD（增量运行续接用）"
    )
    vol_execute_dates: List[str] = Field(
        default_factory=list,
        description="已登记的波动率执行日 YYYY-MM-DD（增量运行续接用）"
    )
    state_version: int = Field(
        1,
        description="落库状态结构版本，用于识别旧文档缺字段"
    )
    
    # 历史记录
    nav_history: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="净值历史（实际口径，含主观调整）[{'date': '...', 'nav': ...}, ...]"
    )
    nav_history_model: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="净值历史（模型口径，纯系统信号自动执行，不含主观调整）"
    )
    sub_strategy_performance: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="组合监控：各子策略模型口径绩效（来源回测管线 sub_results，小数形式）"
    )
    custom_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="策略自定义监控指标（allocator.compute_monitoring_metrics 返回值，每日更新）"
    )
    event_log: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="事件日志（口径见 EventLogEntry；存量异构数据由 events.normalize_event 映射）"
    )
    
    # 关联信息
    strategy_model_id: Optional[str] = Field(
        None, 
        description="关联的策略模型 ID（可选）"
    )

    # 绩效解释：完整初始化、主观步进暂停落库时写入的实盘参数快照（与准入接口同口径）；普通过监控不覆盖
    performance_basis: Optional[Dict[str, Any]] = Field(
        None,
        description="监控净值/绩效曲线对应的实盘参数摘要（初始化或主观步进暂停保存时写入）",
    )

    # 本次运行使用的配置版本与快照指纹（用于核对重新发布后下游是否切到新逻辑）
    config_versions: Optional[Dict[str, Any]] = Field(
        None,
        description="本次运行使用的发布/实盘版本与快照指纹（组合含各子策略版本）",
    )

    # 本次运行的执行口径（见 app.backtesting.policy.ExecutionPolicy）。
    # 监控固定 gross（不计交易成本）而回测可能按策略声明的费率计费，
    # 两侧净值分叉时先看本字段的 cost_basis 与 policy_hash，不用去猜。
    execution_policy: Optional[Dict[str, Any]] = Field(
        None,
        description="本次运行的成交口径（费率/滑点/gross-net + policy_hash）",
    )

    # 主观预设步进：尚有未推演交易日时为 True；已滚到行情末尾则为 False（供前端「继续执行」显隐）
    manual_preset_step_pending: bool = Field(
        False,
        description="主观策略预设调仓步进：完成某调仓日当日推演后暂停，若仍有更晚交易日待跑则为 True",
    )
    manual_preset_next_date: Optional[str] = Field(
        None,
        description="区间内下一档预设调仓日 YYYY-MM-DD；若后续仅有非调仓交易日则可能为空",
    )

    # 信号页快照：跑批收尾时把 get_signal_status() 的结果物化到状态文档，
    # 展示端点（/monitor/signals）直接读它，不再回源行情库做波动率/调仓日计算。
    # 存量文档无该键时为 None，端点返回 404 提示重跑一次。
    signal_snapshot: Optional[Dict[str, Any]] = Field(
        None,
        description="本次批次收尾时的信号状态快照（monthly_rebalance/vol_reset/volatility_history 等）",
    )
    signal_snapshot_at: Optional[datetime] = Field(
        None,
        description="信号快照生成时间",
    )

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        # replace_one/insert_one 不得带与文档不一致的 _id，否则触发 immutable _id 错误
        data.pop("_id", None)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorState":
        """从字典创建实例"""
        # 处理 _id 到 id 的映射
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


class SubjectiveOverride(BaseModel):
    """
    主观调仓指令
    存入 MongoDB subjective_overrides 集合
    用于手动指定目标权重进行调仓
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v
    override_id: str = Field(..., description="唯一调仓指令 ID")
    monitor_id: str = Field(..., description="关联的监控实例 ID")
    # 批次归属：未执行（pending）的主观指令在创建新批次时被继承到新批次，
    # 已执行（executed）的随旧批次封存归档，两边各自可查。
    batch_id: Optional[str] = Field(None, description="所属运行批次号（monitor_batches.batch_id）")
    inherited_from_batch_id: Optional[str] = Field(
        None,
        description="继承来源批次号：本条是从上一批次的 pending 指令复制而来时回填，原批次新建为 null"
    )
    
    # 调仓配置
    weights: Dict[str, float] = Field(..., description="目标权重 {资产名: 权重}")
    execute_date: str = Field(..., description="执行日期 (YYYY-MM-DD)")
    
    # 状态
    status: OverrideStatus = Field(
        OverrideStatus.PENDING, 
        description="状态: pending/executed/cancelled"
    )
    description: Optional[str] = Field(None, description="调仓描述/备注")
    linked_operation_id: Optional[str] = Field(
        None,
        description="挂接的待执行操作指令 ID（调仓日比例优化模式，非空时表示替代该指令）"
    )
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    executed_at: Optional[datetime] = Field(None, description="执行时间")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        # 枚举转为字符串值
        if "status" in data and isinstance(data["status"], OverrideStatus):
            data["status"] = data["status"].value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubjectiveOverride":
        """从字典创建实例"""
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


class MonitorRiskAlert(BaseModel):
    """风险预警记录（monitor_risk_alerts 集合）

    策略通道与组合通道共用一份记录，`monitor_kind` 区分来源：
    - ``vol_compare``：短窗口年化波动率 / 长窗口年化波动率；
    - ``corr_reversal``：近 N 日相关性与历史中枢偏离（状态反转升级 red）。

    每次运行按 ``(monitor_id, signal_date)`` 覆盖写入，重跑幂等、历史日期保留。
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v

    alert_id: str = Field(..., description="预警唯一 ID（UUID）")
    monitor_id: str = Field(..., description="监控实例 ID")
    batch_id: Optional[str] = Field(None, description="所属运行批次号（monitor_batches.batch_id）")
    monitor_kind: str = Field("strategy", description="通道类型: strategy / portfolio")
    signal_type: str = Field(..., description="信号类型: vol_compare / corr_reversal")
    severity: str = Field(..., description="级别: green / yellow / red")
    trigger_value: float = Field(..., description="触发指标值（波动率比值 / 相关系数）")
    threshold: float = Field(..., description="对应级别的阈值")
    window_pair: Dict[str, Any] = Field(default_factory=dict, description="窗口参数")
    asset_codes: List[str] = Field(default_factory=list, description="单资产或资产对")
    signal_date: str = Field(..., description="预警信号日期 YYYY-MM-DD")
    detail: Dict[str, Any] = Field(default_factory=dict, description="上下文（历史中枢/分项波动率等）")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        return data


class PositionDetail(BaseModel):
    """持仓明细"""
    asset_name: str = Field(..., description="资产名称")
    weight: float = Field(..., description="权重")
    position_cny: float = Field(..., description="人民币持仓金额")
    position_local: float = Field(..., description="本币持仓金额")
    daily_return: Optional[float] = Field(None, description="日收益率")
    pnl_local: Optional[float] = Field(None, description="本币损益")
    
    class Config:
        populate_by_name = True


class SignalStatus(BaseModel):
    """信号状态"""
    vol_breach: bool = Field(False, description="波动率突破信号")
    drawdown_warning: bool = Field(False, description="回撤预警信号")
    rebalance_due: bool = Field(False, description="需要调仓信号")
    details: Optional[Dict[str, Any]] = Field(None, description="信号详情")
    
    class Config:
        populate_by_name = True


class PerformanceMetrics(BaseModel):
    """绩效指标"""
    cumulative_return: float = Field(0.0, description="累计收益率")
    annual_return: Optional[float] = Field(None, description="年化收益率")
    annual_volatility: Optional[float] = Field(None, description="年化波动率")
    sharpe_ratio: Optional[float] = Field(None, description="夏普比率")
    max_drawdown: float = Field(0.0, description="最大回撤")
    current_drawdown: float = Field(0.0, description="当前回撤")
    calmar_ratio: Optional[float] = Field(None, description="卡玛比率")
    
    class Config:
        populate_by_name = True


class MonitorDailyReport(BaseModel):
    """
    日报快照
    存入 MongoDB monitor_daily_reports 集合
    记录每日监控快照数据
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")
    monitor_id: str = Field(..., description="监控实例 ID")
    batch_id: Optional[str] = Field(None, description="所属运行批次号（monitor_batches.batch_id）")
    date: str = Field(..., description="日期 (YYYY-MM-DD)")
    
    # 净值数据
    nav: float = Field(..., description="净值")
    daily_return: float = Field(0.0, description="日收益率")
    
    # 杠杆
    total_leverage: float = Field(1.0, description="总杠杆")
    
    # 持仓明细
    positions: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="持仓明细列表"
    )
    
    # 信号状态
    signals: Dict[str, Any] = Field(
        default_factory=dict, 
        description="信号状态（波动率突破、回撤预警等）"
    )
    
    # 绩效指标
    performance: Dict[str, Any] = Field(
        default_factory=dict, 
        description="绩效指标（累计收益、年化收益、波动、夏普、回撤等）"
    )
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorDailyReport":
        """从字典创建实例"""
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


# ============================================================
# 请求/响应模型（用于 API 接口）
# ============================================================

class MonitorStateCreate(BaseModel):
    """创建监控状态请求"""
    monitor_id: str = Field(..., description="监控实例 ID")
    strategy_model_id: Optional[str] = Field(None, description="关联的策略模型 ID")
    initial_nav: float = Field(1.0, description="初始净值")
    initial_date: str = Field(..., description="初始日期 (YYYY-MM-DD)")
    target_weights: Dict[str, float] = Field(
        default_factory=dict, 
        description="初始目标权重"
    )


class MonitorStateUpdate(BaseModel):
    """更新监控状态请求"""
    nav: Optional[float] = Field(None, description="净值")
    positions_cny: Optional[Dict[str, float]] = Field(None, description="人民币持仓")
    positions_local: Optional[Dict[str, float]] = Field(None, description="本币持仓")
    target_weights: Optional[Dict[str, float]] = Field(None, description="目标权重")
    pending_rebalance: Optional[Dict[str, Any]] = Field(None, description="待执行调仓")


class SubjectiveOverrideCreate(BaseModel):
    """创建主观调仓请求"""
    monitor_id: str = Field(..., description="监控实例 ID")
    weights: Dict[str, float] = Field(..., description="目标权重")
    execute_date: str = Field(..., description="执行日期 (YYYY-MM-DD)")
    description: Optional[str] = Field(None, description="调仓描述")
    linked_operation_id: Optional[str] = Field(
        None,
        description="挂接的待执行操作指令 ID（比例优化模式）；不传则为额外调仓"
    )
    record_executed: bool = Field(
        False,
        description="补录模式：创建时直接标记为已执行，提交后按执行日重算净值"
    )


class OperationRemarkUpdate(BaseModel):
    """操作指令补充说明更新请求"""
    remark: str = Field(
        "",
        max_length=500,
        description="补充说明；空字符串表示清除已有备注"
    )


class MonitorDailyReportQuery(BaseModel):
    """日报查询请求"""
    monitor_id: str = Field(..., description="监控实例 ID")
    start_date: Optional[str] = Field(None, description="开始日期 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="结束日期 (YYYY-MM-DD)")
    limit: int = Field(30, description="返回条数限制")


# ============================================================
# 夏普策略权重缓存 (sharpe_rebalance_weights 集合)
# ============================================================

class SharpeRebalanceWeight(BaseModel):
    """夏普策略权重缓存 (sharpe_rebalance_weights 集合)

    写入时机: 夏普策略监控计算后缓存，避免重复计算。
    索引: calc_date
    """
    id: Optional[str] = Field(None, alias="_id")
    calc_date: str = Field(..., description="计算日期 (YYYY-MM-DD)")
    asset_code: str = Field("", description="资产代码")
    weight: float = Field(0.0, description="权重")
    # 完整权重快照以 dict 形式存储，key 为资产名/代码，value 为权重
    weights: Dict[str, float] = Field(default_factory=dict, description="完整权重快照 {资产名: 权重}")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        populate_by_name = True
