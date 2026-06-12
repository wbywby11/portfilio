"""
ZY 数据域辅助工具模块

提供时序生成、随机金融指标、虚构编号生成等通用工具。
"""
from __future__ import annotations
import math
import random
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

# =============== 中国法定节假日（2024-2025 简化版）===============
HOLIDAYS_2024_2025 = {
    # 元旦
    '20240101', '20250101',
    # 春节
    '20240210', '20240211', '20240212', '20240213', '20240214', '20240215', '20240216', '20240217',
    '20250128', '20250129', '20250130', '20250131', '20250201', '20250202', '20250203', '20250204',
    # 清明
    '20240404', '20240405', '20240406', '20250404', '20250405', '20250406',
    # 劳动节
    '20240501', '20240502', '20240503', '20240504', '20240505',
    '20250501', '20250502', '20250503', '20250504', '20250505',
    # 端午
    '20240610', '20250531', '20250602',
    # 中秋
    '20240915', '20240916', '20240917', '20251006',
    # 国庆
    '20241001', '20241002', '20241003', '20241004', '20241005', '20241006', '20241007',
    '20251001', '20251002', '20251003', '20251004', '20251005', '20251006', '20251007', '20251008',
}

# =============== 日期工具 ===============

def parse_dt(s: str) -> datetime:
    """支持 'YYYYMMDD' / 'YYYY-MM-DD' 两种格式"""
    s = s.strip()
    if '-' in s:
        return datetime.strptime(s, '%Y-%m-%d')
    return datetime.strptime(s, '%Y%m%d')


def fmt_dt(d: datetime) -> str:
    return d.strftime('%Y%m%d')


def is_trade_day(d: datetime) -> bool:
    """判断是否交易日（跳过周末和节假日）"""
    if d.weekday() >= 5:  # 周六周日
        return False
    if fmt_dt(d) in HOLIDAYS_2024_2025:
        return False
    return True


def gen_trade_dates(end_dt: str, n_days: int) -> List[str]:
    """生成最近 N 个交易日（包含 end_dt 当日，从过去到现在升序）"""
    end = parse_dt(end_dt)
    out: List[str] = []
    cur = end
    while len(out) < n_days:
        if is_trade_day(cur):
            out.append(fmt_dt(cur))
        cur = cur - timedelta(days=1)
        # 防止无限循环
        if (end - cur).days > n_days * 3:
            break
    return list(reversed(out))


def shift_trade_dates(d: str, n: int) -> str:
    """从 d 前后偏移 n 个交易日（n 为正向后，为负向前）"""
    cur = parse_dt(d)
    step = 1 if n > 0 else -1
    cnt = 0
    while cnt < abs(n):
        cur = cur + timedelta(days=step)
        if is_trade_day(cur):
            cnt += 1
    return fmt_dt(cur)


# =============== 行情时序生成（GBM / Vasicek 简化）===============

def gbm_path(start: float, n_days: int,
             mu_annual: float = 0.05, sigma_annual: float = 0.20,
             dt_year: float = 1 / 250, seed: Optional[int] = None) -> List[float]:
    """
    几何布朗运动（适用于股票/基金净值时序）：
        S_{t+1} = S_t * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)
    """
    rng = random.Random(seed) if seed is not None else random
    out = [start]
    drift = (mu_annual - 0.5 * sigma_annual ** 2) * dt_year
    diffu = sigma_annual * math.sqrt(dt_year)
    for _ in range(n_days - 1):
        z = rng.gauss(0, 1)
        prev = out[-1]
        new = prev * math.exp(drift + diffu * z)
        out.append(round(new, 4))
    return out


def vasicek_path(start: float, n_days: int,
                 long_term: float = 0.025, kappa: float = 0.15, sigma: float = 0.005,
                 dt_year: float = 1 / 250, seed: Optional[int] = None,
                 floor: float = 0.001, cap: float = 0.10) -> List[float]:
    """
    Vasicek 利率/收益率均值回归模型：
        r_{t+1} = r_t + kappa*(theta - r_t)*dt + sigma*sqrt(dt)*Z
    """
    rng = random.Random(seed) if seed is not None else random
    out = [start]
    diffu = sigma * math.sqrt(dt_year)
    for _ in range(n_days - 1):
        z = rng.gauss(0, 1)
        prev = out[-1]
        new = prev + kappa * (long_term - prev) * dt_year + diffu * z
        new = max(floor, min(cap, new))
        out.append(round(new, 6))
    return out


def random_walk_pct(start: float, n_days: int,
                    daily_drift: float = 0.0001, daily_vol: float = 0.005,
                    seed: Optional[int] = None) -> List[float]:
    """简易日收益率序列累乘（适用于指数/价格）"""
    rng = random.Random(seed) if seed is not None else random
    out = [start]
    for _ in range(n_days - 1):
        r = rng.gauss(daily_drift, daily_vol)
        out.append(round(out[-1] * (1 + r), 4))
    return out


def ohlc_from_close(close_prices: List[float], intraday_vol: float = 0.005,
                    seed: Optional[int] = None) -> List[Tuple[float, float, float, float]]:
    """从收盘价序列推导 OHLC（开高低收）"""
    rng = random.Random(seed) if seed is not None else random
    out = []
    prev_close = close_prices[0]
    for c in close_prices:
        # 开盘 = 上一日收盘 ± 0~30% 日波动
        open_p = prev_close * (1 + rng.uniform(-intraday_vol * 0.3, intraday_vol * 0.3))
        body_lo, body_hi = sorted([open_p, c])
        high = body_hi * (1 + rng.uniform(0, intraday_vol * 0.6))
        low = body_lo * (1 - rng.uniform(0, intraday_vol * 0.6))
        out.append((round(open_p, 4), round(high, 4), round(low, 4), round(c, 4)))
        prev_close = c
    return out


# =============== 编号 / 标识符生成 ===============

# GB 11643 行政区划码（部分）
PROVINCE_CODES = ['110000', '120000', '130000', '310000', '320000', '330000', '370000',
                  '410000', '420000', '430000', '440000', '500000', '510000', '610000']


def gen_id_no(birth_dt: str, gender: str = 'M', seed: Optional[int] = None) -> str:
    """
    生成符合校验位规则的虚构身份证号
    （不会对应任何真实公民——前 6 位用合规行政区划，后 4 位测试段）
    """
    rng = random.Random(seed) if seed is not None else random
    prov = rng.choice(PROVINCE_CODES)
    # 行政区划后两位用 99（民政部预留测试段）
    area = prov[:4] + '99'
    # 出生日期 YYYYMMDD
    if '-' in birth_dt:
        bd = birth_dt.replace('-', '')
    else:
        bd = birth_dt
    # 顺序号（17 位前共 17 位，第 17 位偶数=女、奇数=男）
    seq2 = rng.randint(0, 99)
    seq3 = rng.randint(0, 9) * 2 + (1 if gender == 'M' else 0)
    seq3 = min(seq3, 9)
    body = f'{area}{bd}{seq2:02d}{seq3}'
    # 校验位
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
    s = sum(int(body[i]) * weights[i] for i in range(17))
    check = check_codes[s % 11]
    return body + check


def gen_credit_code(seed: Optional[int] = None) -> str:
    """
    生成 18 位统一社会信用代码（国家市场监督管理总局规则）
    格式：1 位登记管理部门代码 + 1 位机构类别代码 + 6 位行政区划码 + 9 位主体标识码 + 1 位校验码
    """
    rng = random.Random(seed) if seed is not None else random
    # 字符表（不含 I O Z S V）
    charset = '0123456789ABCDEFGHJKLMNPQRTUWXY'
    char_map = {c: i for i, c in enumerate(charset)}
    weights = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]
    # 工商登记 91xxxx
    prefix = '91' + rng.choice(PROVINCE_CODES)
    # 9 位主体标识码
    body = ''.join(rng.choice(charset) for _ in range(9))
    code17 = prefix + body
    s = sum(char_map[code17[i]] * weights[i] for i in range(17))
    check_idx = (31 - s % 31) % 31
    return code17 + charset[check_idx]


def gen_phone(seed: Optional[int] = None) -> str:
    """生成虚构手机号（138/139/186/188 等运营商前缀）"""
    rng = random.Random(seed) if seed is not None else random
    prefix = rng.choice(['133', '139', '156', '177', '180', '186', '188', '189', '199'])
    return prefix + ''.join(str(rng.randint(0, 9)) for _ in range(8))


def gen_email(name_pinyin: Optional[str] = None, seed: Optional[int] = None) -> str:
    rng = random.Random(seed) if seed is not None else random
    name = name_pinyin or ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(rng.randint(4, 8)))
    domain = rng.choice(['163.com', '126.com', 'qq.com', 'gmail.com', 'sina.com', 'foxmail.com'])
    return f'{name}{rng.randint(1, 999)}@{domain}'


def gen_bank_acct(bank_code: str = '6217', length: int = 19, seed: Optional[int] = None) -> str:
    rng = random.Random(seed) if seed is not None else random
    return bank_code + ''.join(str(rng.randint(0, 9)) for _ in range(length - len(bank_code)))


# =============== 金融业务规则计算 ===============

def calc_duration_convexity(coupon_rate: float, ytm: float, years_to_maturity: float,
                            face: float = 100.0, freq: int = 1) -> Tuple[float, float, float]:
    """
    粗略计算债券麦考利久期、修正久期、凸性（仅供生成测试数据）
    返回：(MAC_DURATION, MOD_DURATION, CONVEXITY)
    """
    if years_to_maturity <= 0:
        return (0.0, 0.0, 0.0)
    n = max(1, int(round(years_to_maturity * freq)))
    c = coupon_rate * face / freq
    y = ytm / freq
    pv = 0.0
    weighted_t = 0.0
    convex = 0.0
    for k in range(1, n + 1):
        cf = c + (face if k == n else 0)
        denom = (1 + y) ** k
        pv_k = cf / denom
        pv += pv_k
        weighted_t += (k / freq) * pv_k
        convex += pv_k * (k / freq) * ((k / freq) + 1 / freq)
    if pv <= 0:
        return (0.0, 0.0, 0.0)
    mac = weighted_t / pv
    mod = mac / (1 + ytm / freq)
    cnv = convex / (pv * (1 + ytm) ** 2)
    return (round(mac, 4), round(mod, 4), round(cnv, 4))


def calc_aci(coupon_rate: float, days_since_last: int, face: float = 100.0) -> float:
    """计算应计利息（按实际天数 / 365）"""
    return round(face * coupon_rate * days_since_last / 365.0, 4)


def calc_full_price(net_price: float, aci: float) -> float:
    """全价 = 净价 + 应计利息"""
    return round(net_price + aci, 4)


def years_between(d1: str, d2: str) -> float:
    """返回 d2 - d1 的年数（按 365 日折算）"""
    a = parse_dt(d1)
    b = parse_dt(d2)
    return (b - a).days / 365.0


# =============== 中文姓名 ===============

def gen_chinese_name(surname: str, gender: str, given_pool_m: list, given_pool_f: list,
                     seed: Optional[int] = None) -> str:
    rng = random.Random(seed) if seed is not None else random
    given = rng.choice(given_pool_m if gender == 'M' else given_pool_f)
    return surname + given


def gen_inst_name(prefix: str, suffix_pool: list, industry: str = '',
                  seed: Optional[int] = None) -> str:
    rng = random.Random(seed) if seed is not None else random
    suffix = rng.choice(suffix_pool)
    if industry:
        return f'{prefix}{industry}{suffix}'
    return f'{prefix}{suffix}'


# =============== 自检 ===============

if __name__ == '__main__':
    print('=== 交易日生成 ===')
    days = gen_trade_dates('20250324', 60)
    print(f'最近 60 个交易日: {days[0]} ~ {days[-1]} ({len(days)} 个)')

    print('\n=== GBM 路径 ===')
    p = gbm_path(100.0, 60, mu_annual=0.06, sigma_annual=0.18, seed=42)
    print(f'GBM(100, 60d): start={p[0]} end={p[-1]} min={min(p)} max={max(p)}')

    print('\n=== Vasicek 收益率 ===')
    r = vasicek_path(0.025, 60, long_term=0.025, kappa=0.10, sigma=0.003, seed=42)
    print(f'Vasicek(2.5%, 60d): start={r[0]:.4f} end={r[-1]:.4f}')

    print('\n=== 编号生成 ===')
    print(f'身份证: {gen_id_no("19900801", "M", seed=1)}')
    print(f'信用码: {gen_credit_code(seed=1)}')
    print(f'手机:   {gen_phone(seed=1)}')
    print(f'邮箱:   {gen_email(seed=1)}')
    print(f'银行卡: {gen_bank_acct(seed=1)}')

    print('\n=== 久期凸性 ===')
    mac, mod, cnv = calc_duration_convexity(0.0265, 0.0250, 8.5)
    print(f'10Y 国债 (c=2.65%, y=2.50%, t=8.5y): mac={mac} mod={mod} cnv={cnv}')

    print('\n=== 中文姓名 ===')
    from zy_data_pools import SURNAMES, GIVEN_NAMES_M, GIVEN_NAMES_F
    for _ in range(3):
        sn = random.choice(SURNAMES)
        print(gen_chinese_name(sn, 'M', GIVEN_NAMES_M, GIVEN_NAMES_F))
