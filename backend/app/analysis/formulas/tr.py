"""TR样本点位计算公式.

根据文档《不同类型资产收益计算公式.md》实现三种资产类型的TR计算：
1. 指数类：直接使用指数收盘价计算累计收益
2. 期货类：处理主力合约展期，使用加权平均收益率
3. 现货类：上市前用替代标的，上市后切换到实际ETF

核心公式：F_t^c = F_{t-1}^c × (1 + r_t^c)
所有资产的TR序列从基日点位1开始累积计算。
"""

from __future__ import annotations

from typing import Optional, Dict

import pandas as pd

from app.models.asset import Asset, InstrumentType


def _compute_futures_tr_simple(df: pd.DataFrame) -> pd.Series:
    """简化版期货TR计算（无展期逻辑）.
    
    直接使用结算价计算收益率，适用于：
    1. 单合约数据
    2. 已经处理好的连续合约数据
    3. 缺少展期所需字段的情况
    
    参数:
        df: 价格数据DataFrame，需包含time和settlement(或close)列
    
    返回:
        TR序列
    """
    price_col = "settlement" if "settlement" in df.columns else "close"
    df["daily_return"] = df[price_col].pct_change(fill_method=None)
    
    df["F"] = (1 + df["daily_return"]).cumprod()
    df.loc[0, "F"] = 1.0
    
    return pd.Series(df["F"].values, index=pd.to_datetime(df["time"]), name="TR")


def _compute_futures_tr_with_rollover(df: pd.DataFrame, config: Asset) -> pd.Series:
    """完整版期货TR计算（含展期逻辑）.
    
    实现文档3.2节的完整展期算法：
    1. 识别主力合约
    2. 判定展期开始日
    3. 在展期期间使用加权平均收益率
    
    参数:
        df: 价格数据，需包含：time, contract, settlement, open_interest, last_trade_date
        config: 资产对象（包含p, q, k, th参数）
    
    返回:
        TR序列
    """
    df = df.copy()
    df['time_dt'] = pd.to_datetime(df['time'])
    df['last_trade_date_dt'] = pd.to_datetime(df['last_trade_date'])
    
    # 获取展期参数
    k = config.rollover_days  # 展期天数
    th = config.rollover_threshold  # 持仓量阈值
    p = config.rollover_window_p  # 观察窗口起点（LTD-p）
    q = config.rollover_window_q  # 观察窗口终点（LTD-q）
    
    # 步骤1: 识别每日的主力合约和次主力合约
    df = _identify_dominant_contracts(df)
    
    # 步骤2: 判定展期开始日
    df = _identify_rollover_periods(df, p, q, k, th)
    
    # 步骤3: 计算收益率（展期日使用加权平均）
    df = _compute_rollover_returns(df, k)
    
    # 步骤4: 累积计算TR序列
    df["F"] = (1 + df["daily_return"]).cumprod()
    df.loc[0, "F"] = 1.0
    
    return pd.Series(df["F"].values, index=df['time_dt'], name="TR")


def _identify_dominant_contracts(df: pd.DataFrame) -> pd.DataFrame:
    """识别每日的主力合约和次主力合约.
    
    主力合约定义：当日持仓量最大的合约
    次主力合约：当日持仓量第二大的合约
    
    参数:
        df: 包含contract和open_interest的DataFrame
    
    返回:
        增加了dominant_contract和next_dominant_contract列的DataFrame
    """
    # 按日期分组，找出每日持仓量最大的合约
    result_rows = []
    
    for date, group in df.groupby('time_dt'):
        # 按持仓量降序排序
        sorted_group = group.sort_values('open_interest', ascending=False)
        
        if len(sorted_group) >= 1:
            dominant = sorted_group.iloc[0]['contract']
            dominant_oi = sorted_group.iloc[0]['open_interest']
            dominant_settlement = sorted_group.iloc[0]['settlement'] if 'settlement' in sorted_group.columns else sorted_group.iloc[0]['close']
            dominant_ltd = sorted_group.iloc[0]['last_trade_date_dt']
        else:
            dominant = None
            dominant_oi = 0
            dominant_settlement = None
            dominant_ltd = None
        
        if len(sorted_group) >= 2:
            next_dominant = sorted_group.iloc[1]['contract']
            next_oi = sorted_group.iloc[1]['open_interest']
            next_settlement = sorted_group.iloc[1]['settlement'] if 'settlement' in sorted_group.columns else sorted_group.iloc[1]['close']
        else:
            next_dominant = None
            next_oi = 0
            next_settlement = None
        
        result_rows.append({
            'time_dt': date,
            'dominant_contract': dominant,
            'dominant_oi': dominant_oi,
            'dominant_settlement': dominant_settlement,
            'dominant_ltd': dominant_ltd,
            'next_dominant_contract': next_dominant,
            'next_dominant_oi': next_oi,
            'next_dominant_settlement': next_settlement
        })
    
    result_df = pd.DataFrame(result_rows)
    return result_df


def _identify_rollover_periods(df: pd.DataFrame, p: int, q: int, k: int, th: float) -> pd.DataFrame:
    """判定展期开始日和展期期间.
    
    文档规则：
    1. 观察窗口：[LTD(i)-p, LTD(i)-q]
    2. 触发条件：next_oi / dominant_oi >= th，则次日为展期开始日
    3. 保底规则：截至LTD-q日未触发，则LTD-q+1日为展期开始日
    4. 展期持续k个交易日
    
    参数:
        df: 包含主力合约信息的DataFrame
        p, q: 观察窗口参数
        k: 展期天数
        th: 持仓量比例阈值
    
    返回:
        增加了rollover_day列的DataFrame（标记展期的第n天，0表示非展期）
    """
    df = df.sort_values('time_dt').reset_index(drop=True)
    df['rollover_day'] = 0  # 0表示非展期日，1~k表示展期的第n天
    
    i = 0
    while i < len(df):
        row = df.iloc[i]
        
        # 检查是否已经在展期中
        if df.loc[i, 'rollover_day'] > 0:
            i += 1
            continue
        
        current_contract = row['dominant_contract']
        current_ltd = row['dominant_ltd']
        
        if pd.isna(current_contract) or pd.isna(current_ltd):
            i += 1
            continue
        
        # 计算观察窗口
        # 找到LTD日期在df中的位置
        ltd_mask = df['time_dt'] == current_ltd
        if not ltd_mask.any():
            # LTD不在数据中，跳过
            i += 1
            continue
        
        ltd_idx = df[ltd_mask].index[0]
        
        # 观察窗口：[LTD-p, LTD-q]
        window_start_idx = max(0, ltd_idx - p)
        window_end_idx = max(0, ltd_idx - q)
        
        if window_start_idx >= len(df) or window_end_idx >= len(df):
            i += 1
            continue
        
        # 在观察窗口内检查触发条件
        rollover_triggered = False
        trigger_idx = None
        
        for check_idx in range(window_start_idx, window_end_idx + 1):
            if check_idx >= len(df):
                break
            
            check_row = df.iloc[check_idx]
            
            # 检查是否满足触发条件
            if (check_row['dominant_contract'] == current_contract and 
                check_row['next_dominant_oi'] > 0 and 
                check_row['dominant_oi'] > 0):
                
                oi_ratio = check_row['next_dominant_oi'] / check_row['dominant_oi']
                
                if oi_ratio >= th:
                    # 触发！次日为展期开始日
                    trigger_idx = check_idx + 1
                    rollover_triggered = True
                    break
        
        # 应用保底规则
        if not rollover_triggered and window_end_idx + 1 < len(df):
            trigger_idx = window_end_idx + 1
        
        # 标记展期期间（k个交易日）
        if trigger_idx is not None and trigger_idx < len(df):
            for n in range(k):
                day_idx = trigger_idx + n
                if day_idx >= len(df):
                    break
                df.loc[day_idx, 'rollover_day'] = n + 1  # 第1天, 第2天, ..., 第k天
            
            # 跳到展期结束后继续
            i = trigger_idx + k
        else:
            i += 1
    
    return df


def _compute_rollover_returns(df: pd.DataFrame, k: int) -> pd.DataFrame:
    """计算收益率（展期日使用加权平均）.
    
    文档公式：
    - 非展期日：r_t = S_t / S_{t-1} - 1
    - 展期日（第n天）：r_t = [(k-n)/k × S_t^old/S_{t-1}^old + n/k × S_t^new/S_{t-1}^new] - 1
    
    参数:
        df: 包含rollover_day标记的DataFrame
        k: 展期天数
    
    返回:
        增加了daily_return列的DataFrame
    """
    df = df.sort_values('time_dt').reset_index(drop=True)
    df['daily_return'] = 0.0
    
    # 记录前一日的价格（用于计算收益率）
    prev_dominant_settlement = None
    prev_next_settlement = None
    
    for i in range(len(df)):
        row = df.iloc[i]
        
        current_dominant_settlement = row['dominant_settlement']
        current_next_settlement = row['next_dominant_settlement']
        rollover_day = row['rollover_day']
        
        if i == 0:
            # 第一天收益率为0
            df.loc[i, 'daily_return'] = 0.0
        elif rollover_day == 0:
            # 非展期日：r_t = S_t / S_{t-1} - 1
            if prev_dominant_settlement is not None and prev_dominant_settlement > 0:
                df.loc[i, 'daily_return'] = (current_dominant_settlement / prev_dominant_settlement) - 1
            else:
                df.loc[i, 'daily_return'] = 0.0
        else:
            # 展期日（第n天）：加权平均
            # n是从1开始的，对应公式中的n
            n = rollover_day
            
            # 检查是否有足够的数据
            if (prev_dominant_settlement is not None and prev_dominant_settlement > 0 and
                prev_next_settlement is not None and prev_next_settlement > 0 and
                current_dominant_settlement > 0 and current_next_settlement > 0):
                
                # 旧合约收益率
                r_old = (current_dominant_settlement / prev_dominant_settlement) - 1
                # 新合约收益率
                r_new = (current_next_settlement / prev_next_settlement) - 1
                
                # 加权平均：r_t = (k-n)/k × (1+r_old) + n/k × (1+r_new) - 1
                weight_old = (k - n) / k
                weight_new = n / k
                
                df.loc[i, 'daily_return'] = weight_old * (1 + r_old) + weight_new * (1 + r_new) - 1
            else:
                # 数据不足，使用主力合约
                if prev_dominant_settlement is not None and prev_dominant_settlement > 0:
                    df.loc[i, 'daily_return'] = (current_dominant_settlement / prev_dominant_settlement) - 1
                else:
                    df.loc[i, 'daily_return'] = 0.0
        
        # 更新前一日价格
        prev_dominant_settlement = current_dominant_settlement
        prev_next_settlement = current_next_settlement
    
    return df


def compute_index_tr(
    price_data: pd.DataFrame,
    base_date: Optional[str] = None,
) -> pd.Series:
    """计算指数类资产的TR（文档2.1节）.
    
    公式：F_t^c = F_{t-1}^c × (close_t / close_{t-1})
    
    计算步骤：
    1. 计算日收益率：r_t = close_t / close_{t-1} - 1
    2. 累积计算：F_t = (1 + r_t) × F_{t-1}，F_0 = 1
    
    参数:
        price_data: 价格数据，必须包含列：time, close
        base_date: 基日（YYYYMMDD格式），默认使用数据第一个日期
    
    返回:
        TR序列（pd.Series，index为time，value为TR_t^c）
    """
    df = price_data.copy()
    df = df.sort_values("time").reset_index(drop=True)
    
    # 计算日收益率
    df["daily_return"] = df["close"].pct_change(fill_method=None)
    
    # 基日点位为1，通过累积乘法计算后续点位
    df["F"] = (1 + df["daily_return"]).cumprod()
    df.loc[0, "F"] = 1.0
    
    # TR = F
    return pd.Series(df["F"].values, index=pd.to_datetime(df["time"]), name="TR")


def compute_futures_tr(
    config: Asset,
    price_data: pd.DataFrame,
    base_date: Optional[str] = None,
) -> pd.Series:
    """计算期货类资产的TR（文档3.2节）.
    
    完整实现期货展期逻辑：
    1. 非展期日：r_t = S_t / S_{t-1} - 1
    2. 展期日（第n天）：r_t = [(k-n)/k × S_t^old / S_{t-1}^old + n/k × S_t^new / S_{t-1}^new] - 1
    
    展期开始日判定：
    - 观察窗口：[LTD(i)-p, LTD(i)-q]
    - 触发条件：新合约持仓量 / 旧合约持仓量 >= th
    - 保底规则：截至LTD(i)-q日未触发，则LTD(i)-q+1为展期开始日
    
    注意：
    - 当前实现为V2版本（完整展期逻辑）
    - 如果price_data中缺少展期所需字段（contract, open_interest, last_trade_date），
      则回退到V1简化版本（直接使用结算价计算）
    
    参数:
        config: 资产对象（包含p, q, k, th参数）
        price_data: 价格数据，必须包含列：
            - time: 交易日期
            - settlement (或 close): 结算价/收盘价
            可选（用于完整展期）：
            - contract: 合约代码（如IF2401）
            - open_interest: 持仓量
            - last_trade_date: 最后交易日
        base_date: 基日（YYYYMMDD格式），默认使用数据第一个日期
    
    返回:
        TR序列（pd.Series，index为time，value为TR_t^c）
    """
    df = price_data.copy()
    df = df.sort_values("time").reset_index(drop=True)
    
    # 检查是否具备完整展期所需字段
    has_rollover_data = all(col in df.columns for col in ['contract', 'open_interest', 'last_trade_date'])
    
    if not has_rollover_data:
        # 回退到V1简化版本
        print(f"警告: 缺少展期所需字段（contract/open_interest/last_trade_date），"
              f"回退到简化模式（直接使用结算价）")
        return _compute_futures_tr_simple(df)
    
    # V2完整版本：实现展期逻辑
    return _compute_futures_tr_with_rollover(df, config)


def compute_spot_tr(
    config: Asset,
    price_data: pd.DataFrame,
    base_date: Optional[str] = None,
    data_connector = None,
) -> pd.Series:
    """计算现货类资产的TR（文档2.4节）.
    
    完整实现数据自动拼接：
    - 上市前（< switch_date）：使用替代标的价格
    - 上市后（>= switch_date）：使用实际ETF价格
    - 在切换日保证连续性
    
    实现版本：
    - V2版本：完整的自动数据拼接
    - 如果price_data包含切换前后的完整数据，直接使用
    - 如果只有ETF数据，则自动获取替代标的数据
    
    参数:
        config: 资产对象（需要substitute_code和switch_date属性）
        price_data: 价格数据，包含：time, close
        base_date: 基日（YYYYMMDD格式），默认使用数据第一个日期
        data_connector: 数据连接器，用于获取替代标的数据（可选）
    
    返回:
        TR序列（pd.Series，index为time，value为TR_t^c）
    """
    if not config.switch_date or not config.substitute_code:
        # 无切换信息，直接作为指数类处理
        return _compute_spot_tr_simple(price_data)
    
    df = price_data.copy()
    df = df.sort_values("time").reset_index(drop=True)
    df['time_dt'] = pd.to_datetime(df['time'])
    
    switch_date_dt = pd.to_datetime(config.switch_date)
    
    # 检查price_data是否已经包含切换前的数据
    min_date = df['time_dt'].min()
    
    if min_date >= switch_date_dt:
        # price_data只有上市后的数据，需要获取替代标的数据
        if data_connector is None:
            # 无数据连接器，输出警告并回退到简化模式
            print(f"警告: 现货类资产 {config.code} 缺少切换前数据，"
                  f"且未提供data_connector。将只使用现有数据计算TR。")
            return _compute_spot_tr_simple(df)
        
        # 自动获取替代标的数据
        try:
            substitute_data = _fetch_substitute_data(
                data_connector,
                config.substitute_code,
                base_date or df['time'].iloc[0],
                config.switch_date
            )
            
            if substitute_data is None or len(substitute_data) == 0:
                print(f"警告: 无法获取替代标的 {config.substitute_code} 的数据。"
                      f"将只使用ETF数据计算TR。")
                return _compute_spot_tr_simple(df)
            
            # 拼接替代标的数据和ETF数据
            df = _splice_spot_data(substitute_data, df, switch_date_dt)
            
        except Exception as e:
            print(f"错误: 获取替代标的数据失败: {e}。"
                  f"将只使用ETF数据计算TR。")
            return _compute_spot_tr_simple(df)
    
    # price_data已经包含完整的数据，直接计算TR
    return _compute_spot_tr_with_switch(df, switch_date_dt)


def _compute_spot_tr_simple(df: pd.DataFrame) -> pd.Series:
    """简化版现货TR计算（无切换逻辑）.
    
    直接使用收盘价计算收益率，适用于：
    1. 无切换日期的现货
    2. 缺少替代标的数据的情况
    
    参数:
        df: 价格数据DataFrame，需包含time和close列
    
    返回:
        TR序列
    """
    df = df.copy()
    df = df.sort_values("time").reset_index(drop=True)
    
    df["daily_return"] = df["close"].pct_change(fill_method=None)
    df["F"] = (1 + df["daily_return"]).cumprod()
    df.loc[0, "F"] = 1.0
    
    return pd.Series(df["F"].values, index=pd.to_datetime(df["time"]), name="TR")


def _compute_spot_tr_with_switch(df: pd.DataFrame, switch_date_dt: pd.Timestamp) -> pd.Series:
    """带切换逻辑的现货TR计算.
    
    在切换日保证TR序列的连续性。
    
    参数:
        df: 包含切换前后完整数据的DataFrame
        switch_date_dt: 切换日期
    
    返回:
        TR序列
    """
    df = df.copy()
    df = df.sort_values('time_dt').reset_index(drop=True)
    
    # 标记是否使用替代标的
    df['use_substitute'] = df['time_dt'] < switch_date_dt
    
    # 计算收益率
    df["daily_return"] = df["close"].pct_change(fill_method=None)
    
    # 累积计算TR
    df["F"] = (1 + df["daily_return"]).cumprod()
    df.loc[0, "F"] = 1.0
    
    return pd.Series(df["F"].values, index=df['time_dt'], name="TR")


def _fetch_substitute_data(
    data_connector,
    substitute_code: str,
    start_date: str,
    end_date: str
) -> Optional[pd.DataFrame]:
    """获取替代标的的数据.
    
    参数:
        data_connector: 数据连接器对象
        substitute_code: 替代标的代码
        start_date: 开始日期
        end_date: 结束日期（切换日前一天）
    
    返回:
        价格数据DataFrame，包含time和close列
    """
    try:
        # 尝试使用数据连接器的query_price方法
        if hasattr(data_connector, 'query_price'):
            data = data_connector.query_price(
                thscode=substitute_code,
                start_date=start_date,
                end_date=end_date
            )
            return data
        
        # 尝试使用get_price方法
        elif hasattr(data_connector, 'get_price'):
            data = data_connector.get_price(
                code=substitute_code,
                start=start_date,
                end=end_date
            )
            return data
        
        # 不支持的数据连接器
        else:
            print(f"警告: 数据连接器不支持query_price或get_price方法")
            return None
            
    except Exception as e:
        print(f"错误: 获取替代标的数据失败: {e}")
        return None


def _splice_spot_data(
    substitute_data: pd.DataFrame,
    spot_data: pd.DataFrame,
    switch_date_dt: pd.Timestamp
) -> pd.DataFrame:
    """拼接替代标的和现货ETF的数据.
    
    在切换日保证价格连续性。
    
    参数:
        substitute_data: 替代标的数据（切换前）
        spot_data: ETF数据（切换后）
        switch_date_dt: 切换日期
    
    返回:
        拼接后的完整数据DataFrame
    """
    substitute_df = substitute_data.copy()
    substitute_df['time_dt'] = pd.to_datetime(substitute_df['time'])
    
    spot_df = spot_data.copy()
    spot_df['time_dt'] = pd.to_datetime(spot_df['time'])
    
    # 切换前：替代标的数据
    before_switch = substitute_df[substitute_df['time_dt'] < switch_date_dt].copy()
    
    # 切换后：ETF数据
    after_switch = spot_df[spot_df['time_dt'] >= switch_date_dt].copy()
    
    # 拼接数据
    combined_df = pd.concat([before_switch, after_switch], ignore_index=True)
    combined_df = combined_df.sort_values('time_dt').reset_index(drop=True)
    
    return combined_df


def batch_compute_tr(
    price_data_dict: Dict[str, pd.DataFrame],
    asset_configs: Dict[str, Asset],
    base_date: Optional[str] = None,
) -> Dict[str, pd.Series]:
    """批量计算多个资产的TR序列.
    
    参数:
        price_data_dict: {thscode: price_data} 价格数据字典
        asset_configs: {thscode: Asset} 资产对象字典
        base_date: 基日（YYYYMMDD格式）
    
    返回:
        {thscode: tr_series} TR序列字典
    """
    results = {}
    
    for thscode, price_data in price_data_dict.items():
        try:
            # 获取资产配置
            config = asset_configs.get(thscode)

            if config is None:
                # 未配置的资产默认作为指数型处理
                tr_series = compute_index_tr(price_data, base_date)
            else:
                # instrument_type 是 Asset 的必填枚举字段，按工具形态分派
                it = config.instrument_type
                if it == InstrumentType.FUTURES_LIKE:
                    tr_series = compute_futures_tr(config, price_data, base_date)
                elif it == InstrumentType.SPOT_LIKE:
                    tr_series = compute_spot_tr(config, price_data, base_date)
                else:
                    tr_series = compute_index_tr(price_data, base_date)

            results[thscode] = tr_series

        except Exception as e:
            print(f"计算 {thscode} 的TR序列失败: {e}")
            continue
    
    return results
