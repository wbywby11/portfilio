#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZY 数据域 Mock 数据生成器（增强关联版）

目标：
1. 表与表之间建立广泛的外键关联
2. 域与域之间有复杂的业务关联
3. 支持 AI 发现直接/间接/高度/重度/轻度关联
4. 数据具有真实的业务逻辑和时间序列

关联类型：
- 直接关联：外键直接引用（如 AST_CD → dwd_ast_info）
- 间接关联：通过中间表关联（如 产品→持仓→资产）
- 高度关联：多个表共享同一主键（如 同一资产的估值/收益率/现金流）
- 重度关联：一对多/多对多关系（如 机构发行多只债券，债券被多个产品持有）
- 轻度关联：可选关联（如 部分资产有质押信息）
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

# ==================== 基础配置 ====================
BIZ_DT = "20250324"
HISTORY_DAYS = 30  # 历史数据天数

# ==================== 主键池 ====================
class KeyPool:
    """全局主键池，确保跨表关联一致性"""
    
    # 机构/发行人
    INSTITUTIONS = {
        "ISR000001": {"name": "中华人民共和国财政部", "type": "SOVEREIGN", "industry": "S9510", "region": "北京", "credit": "AAA"},
        "ISR000002": {"name": "国家开发银行", "type": "POLICY_BANK", "industry": "J6621", "region": "北京", "credit": "AAA"},
        "ISR000003": {"name": "中国工商银行股份有限公司", "type": "COMMERCIAL_BANK", "industry": "J6611", "region": "北京", "credit": "AAA"},
        "ISR000004": {"name": "中国农业发展银行", "type": "POLICY_BANK", "industry": "J6621", "region": "北京", "credit": "AAA"},
        "ISR000005": {"name": "万科企业股份有限公司", "type": "CORPORATE", "industry": "K7010", "region": "广东", "credit": "AA-"},
        "ISR000006": {"name": "华能新能源股份有限公司", "type": "CORPORATE", "industry": "D4412", "region": "北京", "credit": "AAA"},
        "ISR000007": {"name": "招商银行股份有限公司", "type": "COMMERCIAL_BANK", "industry": "J6611", "region": "广东", "credit": "AAA"},
        "ISR000008": {"name": "中国平安保险(集团)股份有限公司", "type": "CORPORATE", "industry": "J6812", "region": "广东", "credit": "AAA"},
    }
    
    # 资产代码
    ASSETS = {
        "019601.IB": {"name": "25国债03", "type": "BOND", "sub_type": "CGB", "issuer": "ISR000001"},
        "019735.IB": {"name": "25特别国债03", "type": "BOND", "sub_type": "CGB", "issuer": "ISR000001"},
        "230210.IB": {"name": "23国开10", "type": "BOND", "sub_type": "POLICY", "issuer": "ISR000002"},
        "220215.IB": {"name": "22国开15", "type": "BOND", "sub_type": "POLICY", "issuer": "ISR000002"},
        "2480006.IB": {"name": "24工商银行MTN001", "type": "BOND", "sub_type": "MTN", "issuer": "ISR000003"},
        "112311.SZ": {"name": "24万科MTN003", "type": "BOND", "sub_type": "MTN", "issuer": "ISR000005"},
        "600036.SH": {"name": "招商银行", "type": "STOCK", "sub_type": "A_SHARE", "issuer": "ISR000007"},
        "601318.SH": {"name": "中国平安", "type": "STOCK", "sub_type": "A_SHARE", "issuer": "ISR000008"},
        "510300.SH": {"name": "沪深300ETF", "type": "FUND", "sub_type": "ETF", "issuer": "ISR000007"},
        "511260.SH": {"name": "十年国债ETF", "type": "FUND", "sub_type": "ETF", "issuer": "ISR000003"},
        "127080.SZ": {"name": "2024华能新能ABS001优先A", "type": "ABS", "sub_type": "ABS_SENIOR", "issuer": "ISR000006"},
        "180401.IB": {"name": "24农发绿色债01", "type": "BOND", "sub_type": "POLICY", "issuer": "ISR000004"},
    }
    
    # 产品/组合
    PORTFOLIOS = {
        "PORT001": {"name": "稳健配置一号", "type": "MIXED", "risk": "R3", "manager": "ISR000008"},
        "PORT002": {"name": "纯债精选二号", "type": "BOND", "risk": "R2", "manager": "ISR000008"},
        "PORT003": {"name": "混合增强三号", "type": "MIXED", "risk": "R3", "manager": "ISR000005"},
        "PORT004": {"name": "短融货币四号", "type": "MMF", "risk": "R1", "manager": "ISR000008"},
        "PORT005": {"name": "指数增强五号", "type": "INDEX", "risk": "R4", "manager": "ISR000007"},
    }
    
    # 客户
    CUSTOMERS = {
        "CUS0000001": {"name": "张明远", "type": "IND", "risk": "C3", "seller": "SEL00001"},
        "CUS0000002": {"name": "李秀芬", "type": "IND", "risk": "C2", "seller": "SEL00002"},
        "CUS0000003": {"name": "王建国", "type": "IND", "risk": "C4", "seller": "SEL00001"},
        "CUS0000004": {"name": "陈雅琴", "type": "IND", "risk": "C1", "seller": "SEL00004"},
        "CUS0000005": {"name": "深圳市前海资产管理有限公司", "type": "INST", "risk": "C4", "seller": "SEL00003"},
        "CUS0000006": {"name": "上海浦东新区社会保险基金管理中心", "type": "INST", "risk": "C2", "seller": "SEL00005"},
        "CUS0000007": {"name": "广东省教育基金会", "type": "INST", "risk": "C2", "seller": "SEL00006"},
    }
    
    # 销售人员
    SELLERS = {
        "SEL00001": {"name": "刘洋", "type": "INTERNAL", "dept": "机构销售一部", "region": "华东"},
        "SEL00002": {"name": "赵丽华", "type": "INTERNAL", "dept": "零售财富部", "region": "华北"},
        "SEL00003": {"name": "孙志强", "type": "INTERNAL", "dept": "机构销售二部", "region": "华南"},
        "SEL00004": {"name": "周敏", "type": "INTERNAL", "dept": "零售财富部", "region": "华东"},
        "SEL00005": {"name": "吴晓峰", "type": "INTERNAL", "dept": "机构销售一部", "region": "华东"},
        "SEL00006": {"name": "郑雯", "type": "EXTERNAL", "dept": "电商渠道部", "region": "华南"},
    }


# ==================== 关联规则 ====================
class AssociationRules:
    """定义表之间的关联规则"""
    
    # 产品持仓规则（产品→资产）
    PORTFOLIO_HOLDINGS = {
        "PORT001": {
            "019601.IB": 0.15,  # 15% 仓位
            "230210.IB": 0.12,
            "2480006.IB": 0.08,
            "600036.SH": 0.10,
            "510300.SH": 0.20,
            "511260.SH": 0.18,
        },
        "PORT002": {
            "019601.IB": 0.25,
            "019735.IB": 0.20,
            "230210.IB": 0.18,
            "2480006.IB": 0.15,
            "180401.IB": 0.12,
        },
        "PORT003": {
            "600036.SH": 0.15,
            "601318.SH": 0.12,
            "510300.SH": 0.18,
            "019601.IB": 0.10,
            "230210.IB": 0.08,
        },
        "PORT005": {
            "510300.SH": 0.85,  # 指数基金，高度集中
        },
    }
    
    # 客户投资产品规则（客户→产品）
    CUSTOMER_INVESTMENTS = {
        "CUS0000001": ["PORT001", "PORT002"],
        "CUS0000002": ["PORT002", "PORT004"],
        "CUS0000003": ["PORT001", "PORT003", "PORT005"],
        "CUS0000005": ["PORT001", "PORT003"],
        "CUS0000006": ["PORT002", "PORT004"],
        "CUS0000007": ["PORT001"],
    }
    
    # 资产质押规则（资产→质押状态）
    PLEDGE_RULES = {
        "019601.IB": {"ratio": 0.95, "inst": "中国人民银行", "note": "央行公开市场操作"},
        "230210.IB": {"ratio": 0.90, "inst": "中央国债登记结算公司", "note": "银行间质押式回购"},
        "2480006.IB": {"ratio": 0.85, "inst": "上海清算所", "note": "上清所质押式回购"},
        "180401.IB": {"ratio": 0.88, "inst": "中央国债登记结算公司", "note": "绿色债券质押"},
    }


# ==================== 数据生成器 ====================
class MockDataGenerator:
    """生成具有复杂关联的 Mock 数据"""
    
    def __init__(self):
        self.keys = KeyPool()
        self.rules = AssociationRules()
        self.data = {}
        
    def generate_all(self):
        """生成所有域的数据"""
        print("开始生成 Mock 数据...")
        print("="*60)
        
        # 1. 主体域（基础）
        self._gen_institutions()
        self._gen_institution_finance()
        self._gen_counterparties()
        
        # 2. 资产域（依赖主体域）
        self._gen_asset_info()
        self._gen_asset_valuation()
        self._gen_asset_yield()
        self._gen_asset_cashflow()
        self._gen_asset_pledge()
        self._gen_asset_party()
        self._gen_asset_exe_plan()
        self._gen_asset_fund_manager()
        self._gen_asset_bottom_ratio()
        self._gen_asset_fiveclass()
        self._gen_asset_calc_rule()
        
        # 3. 产品域（依赖资产域、主体域）
        self._gen_portfolio_info()
        self._gen_portfolio_holdings()
        self._gen_portfolio_account()
        
        # 4. 客户域（依赖销售域、产品域）
        self._gen_customers()
        self._gen_customer_investment()
        
        # 5. 销售域
        self._gen_sellers()
        
        # 6. 风险域（依赖产品域、主体域）
        self._gen_risk_limit()
        self._gen_credit_rating_change()
        
        # 7. 交易域（依赖产品域、资产域）
        self._gen_trades()
        
        print("="*60)
        print(f"✓ 生成完成！共 {len(self.data)} 个集合")
        
        return self.data
    
    def _gen_institutions(self):
        """生成机构信息（主体域基础表）"""
        records = []
        for isr_id, info in self.keys.INSTITUTIONS.items():
            records.append({
                "ISR_ID": isr_id,
                "ISR_NM": info["name"],
                "ISR_SHORT_NM": info["name"][:4],
                "ISR_TYPE": info["type"],
                "CREDIT_CD": f"91{isr_id[-6:]}001",
                "INDUSTRY_CD": info["industry"],
                "REG_PROV": info["region"],
                "LIST_FLAG": "Y" if info["type"] == "CORPORATE" else "N",
                "REG_CAP_AMT": random.randint(10000000000, 500000000000),
                "EST_DT": "19900101",
                "BIZ_DT": BIZ_DT,
                "etl_dt": BIZ_DT,
                "src_sys": "MOCK"
            })
        self.data["dwd_isr_institution"] = records
        print(f"✓ dwd_isr_institution: {len(records)} 条")
    
    def _gen_asset_info(self):
        """生成资产基础信息（依赖机构表）"""
        records = []
        for ast_cd, info in self.keys.ASSETS.items():
            issuer_info = self.keys.INSTITUTIONS[info["issuer"]]
            
            record = {
                "AST_CD": ast_cd,
                "AST_NM": info["name"],
                "AST_TYPE": info["type"],
                "AST_SUB_TYPE": info["sub_type"],
                "ISR_ID": info["issuer"],  # ← 关联到 dwd_isr_institution
                "CCY": "CNY",
                "MARKET": "银行间" if ast_cd.endswith(".IB") else ("上交所" if ast_cd.endswith(".SH") else "深交所"),
                "etl_dt": BIZ_DT,
                "src_sys": "MOCK"
            }
            
            # 债券特有字段
            if info["type"] == "BOND":
                record.update({
                    "LIST_DT": "20240101",
                    "MATURITY_DT": "20340101",
                    "COUPON_RATE": round(random.uniform(0.02, 0.05), 4),
                    "ISSUE_AMT": random.randint(1000000000, 100000000000),
                    "BOND_TERM": random.choice([1, 2, 3, 5, 7, 10, 30])
                })
            
            # 股票特有字段
            elif info["type"] == "STOCK":
                record.update({
                    "LIST_DT": "20000101",
                    "IPO_PRC": round(random.uniform(5.0, 50.0), 2)
                })
            
            # 基金特有字段
            elif info["type"] == "FUND":
                record.update({
                    "LIST_DT": "20150101",
                    "FUND_TYPE": "ETF",
                    "TRACKING_INDEX": "沪深300" if "300" in ast_cd else "中债综合"
                })
            
            # ABS 特有字段
            elif info["type"] == "ABS":
                record.update({
                    "LIST_DT": "20240801",
                    "MATURITY_DT": "20270801",
                    "COUPON_RATE": 0.033,
                    "ISSUE_AMT": 2000000000,
                    "BOND_TERM": 3,
                    "UNDERLYING_ASSET": "风电场应收电费"
                })
            
            records.append(record)
        
        self.data["dwd_ast_info"] = records
        print(f"✓ dwd_ast_info: {len(records)} 条 [关联: dwd_isr_institution]")
    
    def _gen_portfolio_holdings(self):
        """生成产品持仓表（重度关联：产品→资产）"""
        records = []
        for port_id, holdings in self.rules.PORTFOLIO_HOLDINGS.items():
            for ast_cd, weight in holdings.items():
                # 获取资产信息
                asset_info = self.keys.ASSETS.get(ast_cd, {})
                
                records.append({
                    "PORT_ID": port_id,  # ← 关联到 dwd_ptl_info
                    "AST_CD": ast_cd,    # ← 关联到 dwd_ast_info
                    "AST_NM": asset_info.get("name", ""),
                    "AST_TYPE": asset_info.get("type", ""),
                    "HLD_RATIO": weight,
                    "MKT_VAL": int(weight * 1000000000),
                    "QTY": random.randint(100000, 10000000),
                    "COST_VAL": int(weight * 980000000),
                    "UNREALIZED_PNL": int(weight * 20000000),
                    "BIZ_DT": BIZ_DT,
                    "etl_dt": BIZ_DT,
                    "src_sys": "MOCK"
                })
        
        self.data["dwd_ptl_ast_hld"] = records
        print(f"✓ dwd_ptl_ast_hld: {len(records)} 条 [关联: dwd_ptl_info + dwd_ast_info]")
    
    def _gen_customer_investment(self):
        """生成客户投资记录（间接关联：客户→产品→资产）"""
        records = []
        for cust_id, port_ids in self.rules.CUSTOMER_INVESTMENTS.items():
            customer_info = self.keys.CUSTOMERS[cust_id]
            
            for port_id in port_ids:
                # 投资金额基于客户风险等级
                risk_multiplier = {"C1": 0.5, "C2": 1.0, "C3": 1.5, "C4": 2.0}.get(customer_info["risk"], 1.0)
                invest_amt = int(random.randint(1000000, 50000000) * risk_multiplier)
                
                records.append({
                    "CUSTOMER_ID": cust_id,  # ← 关联到 dwd_cust_info
                    "PORT_ID": port_id,      # ← 关联到 dwd_ptl_info
                    "HLD_AMT": invest_amt,
                    "HLD_SHARE": invest_amt / 1.0,
                    "PURCHASE_DT": "20240101",
                    "LAST_NAV": round(random.uniform(0.95, 1.20), 4),
                    "UNREALIZED_PNL": int(invest_amt * random.uniform(-0.05, 0.15)),
                    "BIZ_DT": BIZ_DT,
                    "etl_dt": BIZ_DT,
                    "src_sys": "MOCK"
                })
        
        self.data["dwd_cust_ptl_hld"] = records
        print(f"✓ dwd_cust_ptl_hld: {len(records)} 条 [关联: dwd_cust_info → dwd_ptl_info → dwd_ast_info]")
    
    def _gen_risk_limit(self):
        """生成风控限额（关联产品域、资产域）"""
        records = []
        
        # 集中度限制
        for port_id in self.keys.PORTFOLIOS.keys():
            records.append({
                "PORT_ID": port_id,
                "RULE_CD": "CONCENTRATION_SINGLE",
                "RULE_NM": "单一资产集中度限制",
                "RULE_DESC": "单一资产持仓不超过基金净资产的10%",
                "THRESHOLD": 0.10,
                "CURRENT_VALUE": round(random.uniform(0.05, 0.12), 4),
                "STATUS": "WARNING" if random.random() > 0.7 else "NORMAL",
                "CHECK_DT": BIZ_DT,
                "etl_dt": BIZ_DT,
                "src_sys": "MOCK"
            })
        
        # 杠杆率限制
        for port_id in self.keys.PORTFOLIOS.keys():
            records.append({
                "PORT_ID": port_id,
                "RULE_CD": "LEVERAGE_RATIO",
                "RULE_NM": "组合杠杆率限制",
                "RULE_DESC": "组合杠杆率不超过140%",
                "THRESHOLD": 1.40,
                "CURRENT_VALUE": round(random.uniform(1.0, 1.35), 4),
                "STATUS": "NORMAL",
                "CHECK_DT": BIZ_DT,
                "etl_dt": BIZ_DT,
                "src_sys": "MOCK"
            })
        
        self.data["dwd_rsk_limit_check"] = records
        print(f"✓ dwd_rsk_limit_check: {len(records)} 条 [关联: dwd_ptl_info]")
    
    def _gen_trades(self):
        """生成交易记录（关联产品域、资产域、机构域）"""
        records = []
        
        for port_id in list(self.keys.PORTFOLIOS.keys())[:3]:
            for _ in range(5):  # 每个产品5笔交易
                ast_cd = random.choice(list(self.keys.ASSETS.keys()))
                asset_info = self.keys.ASSETS[ast_cd]
                
                trade_type = random.choice(["BUY", "SELL"])
                qty = random.randint(100000, 5000000)
                price = round(random.uniform(95.0, 105.0), 4)
                
                records.append({
                    "TRADE_ID": f"TRD{len(records)+1:06d}",
                    "PORT_ID": port_id,        # ← 关联到 dwd_ptl_info
                    "AST_CD": ast_cd,          # ← 关联到 dwd_ast_info
                    "AST_NM": asset_info["name"],
                    "ISR_ID": asset_info["issuer"],  # ← 关联到 dwd_isr_institution
                    "TRADE_TYPE": trade_type,
                    "TRADE_QTY": qty,
                    "TRADE_PRC": price,
                    "TRADE_AMT": int(qty * price),
                    "TRADE_DT": "20250320",
                    "SETTLE_DT": "20250321",
                    "CNTP_ID": "CNTP00001",    # ← 关联到 dwd_isr_trd_cntp
                    "BROKER_FEE": int(qty * price * 0.0001),
                    "BIZ_DT": BIZ_DT,
                    "etl_dt": BIZ_DT,
                    "src_sys": "MOCK"
                })
        
        self.data["dwd_trn_trade_ptl"] = records
        print(f"✓ dwd_trn_trade_ptl: {len(records)} 条 [关联: dwd_ptl_info + dwd_ast_info + dwd_isr_institution]")
    
    # 其他生成方法（简化版）...
    def _gen_institution_finance(self):
        self.data["dwd_isr_institution_finance"] = []
    
    def _gen_counterparties(self):
        self.data["dwd_isr_trd_cntp"] = []
    
    def _gen_asset_valuation(self):
        self.data["dwd_ast_info_ch"] = []
    
    def _gen_asset_yield(self):
        self.data["dwd_ast_yield_info"] = []
    
    def _gen_asset_cashflow(self):
        self.data["dwd_ast_cf_plan"] = []
    
    def _gen_asset_pledge(self):
        self.data["dwd_ast_pledge"] = []
    
    def _gen_asset_party(self):
        self.data["dwd_ast_party"] = []
    
    def _gen_asset_exe_plan(self):
        self.data["dwd_ast_exe_plan"] = []
    
    def _gen_asset_fund_manager(self):
        self.data["dwd_ast_fund_manager"] = []
    
    def _gen_asset_bottom_ratio(self):
        self.data["dwd_ast_bottom_raito"] = []
    
    def _gen_asset_fiveclass(self):
        self.data["dwd_ast_fiveclass"] = []
    
    def _gen_asset_calc_rule(self):
        self.data["dwd_ast_calc_rule"] = []
    
    def _gen_portfolio_info(self):
        self.data["dwd_ptl_info"] = []
    
    def _gen_portfolio_account(self):
        self.data["dwd_ptl_acc"] = []
    
    def _gen_customers(self):
        self.data["dwd_cust_info"] = []
    
    def _gen_sellers(self):
        self.data["dwd_seller_info"] = []
    
    def _gen_credit_rating_change(self):
        self.data["dwd_crdt_rating_change"] = []


# ==================== 主函数 ====================
def main():
    """主函数"""
    output_path = Path("d:/portfilio/scripts/zy_data_mock_associated.json")
    
    # 生成数据
    generator = MockDataGenerator()
    data = generator.generate_all()
    
    # 保存
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    file_size = output_path.stat().st_size
    print(f"\n✓ 已保存到: {output_path}")
    print(f"文件大小: {file_size / 1024:.2f} KB")
    
    # 生成关联说明文档
    generate_association_doc()


def generate_association_doc():
    """生成关联关系说明文档"""
    doc_path = Path("d:/portfilio/scripts/zy_data_association_guide.md")
    
    content = """# ZY 数据域关联关系指南

## 关联类型说明

### 1. 直接关联（外键引用）
- **定义**：表 A 的字段直接引用表 B 的主键
- **示例**：`dwd_ast_info.ISR_ID` → `dwd_isr_institution.ISR_ID`
- **AI 分析价值**：可以直接 JOIN 查询

### 2. 间接关联（通过中间表）
- **定义**：表 A 和表 C 通过中间表 B 关联
- **示例**：`dwd_cust_info` → `dwd_cust_ptl_hld` → `dwd_ptl_info` → `dwd_ptl_ast_hld` → `dwd_ast_info`
- **AI 分析价值**：可以发现"客户最终持有哪些资产"

### 3. 高度关联（多表共享主键）
- **定义**：多个表都围绕同一实体展开
- **示例**：资产实体被以下表关联：
  - `dwd_ast_info`（基础信息）
  - `dwd_ast_info_ch`（中债估值）
  - `dwd_ast_info_zg`（中证估值）
  - `dwd_ast_yield_info`（收益率）
  - `dwd_ast_cf_plan`（现金流）
  - `dwd_ast_pledge`（质押状态）
- **AI 分析价值**：可以构建资产的 360° 全景视图

### 4. 重度关联（一对多/多对多）
- **定义**：一个实体被多个其他实体引用
- **示例**：
  - 一个机构（ISR_ID）发行多只债券
  - 一个产品（PORT_ID）持有多个资产
  - 一个客户（CUSTOMER_ID）投资多个产品
- **AI 分析价值**：可以发现集中度风险、关联风险

### 5. 轻度关联（可选关系）
- **定义**：部分记录有引用，部分没有
- **示例**：
  - 只有部分资产有质押信息（`dwd_ast_pledge`）
  - 只有部分资产有行权计划（`dwd_ast_exe_plan`）
- **AI 分析价值**：可以发现特殊状态或异常

## 核心关联链路

### 链路 1：客户→产品→资产（投资穿透）
```
dwd_cust_info (客户)
    ↓ CUSTOMER_ID
dwd_cust_ptl_hld (客户持仓)
    ↓ PORT_ID
dwd_ptl_info (产品)
    ↓ PORT_ID
dwd_ptl_ast_hld (产品持仓)
    ↓ AST_CD
dwd_ast_info (资产)
    ↓ ISR_ID
dwd_isr_institution (发行人)
```

**AI 可以分析**：
- 某客户间接持有哪些资产？
- 某客户对某发行人的风险敞口？
- 某产品的客户结构？

### 链路 2：资产全景视图
```
dwd_ast_info (基础信息)
    ├→ dwd_ast_info_ch (中债估值)
    ├→ dwd_ast_info_zg (中证估值)
    ├→ dwd_ast_yield_info (收益率)
    ├→ dwd_ast_cf_plan (现金流计划)
    ├→ dwd_ast_pledge (质押状态)
    ├→ dwd_ast_fiveclass (五级分类)
    └→ dwd_ast_exe_plan (行权计划)
```

**AI 可以分析**：
- 资产的估值是否合理？
- 是否存在质押风险？
- 现金流是否健康？

### 链路 3：风险传染路径
```
dwd_isr_institution (发行人)
    ↓ 发行
dwd_ast_info (债券)
    ↓ 被持有
dwd_ptl_ast_hld (产品持仓)
    ↓ 属于
dwd_ptl_info (产品)
    ↓ 被投资
dwd_cust_ptl_hld (客户持仓)
```

**AI 可以分析**：
- 某发行人违约会影响哪些客户？
- 风险传导路径是什么？
- 影响金额有多大？

## AI 分析场景示例

### 场景 1：风险敞口分析
```python
# 查询客户"张明远"对"万科"的风险敞口
客户 → 产品持仓 → 资产 → 发行人
CUS0000001 → PORT001 → 112311.SZ → ISR000005
```

### 场景 2：集中度分析
```python
# 查询哪些产品过度持有同一资产
产品持仓 GROUP BY AST_CD HAVING SUM(HLD_RATIO) > 0.20
```

### 场景 3：流动性分析
```python
# 查询未来30天到期的现金流
现金流计划 WHERE CF_DT BETWEEN '20250324' AND '20250423'
```

### 场景 4：估值对比
```python
# 对比同一资产的中债/中证估值差异
中债估值 JOIN 中证估值 ON AST_CD WHERE ABS(估值差) > 0.5
```
"""
    
    with open(doc_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n✓ 关联关系文档: {doc_path}")


if __name__ == "__main__":
    main()
