"""
静态画像定义包 - 基于Schema和金融业务规则的静态画像模板
"""
from typing import Dict
from ..models import (
    DomainOverview, TableProfile, IntraDomainProfile,
    CrossDomainProfile, ResonanceProfile
)


def get_all_domain_overviews() -> Dict[str, DomainOverview]:
    """获取所有域概览"""
    from .l1_asset import DOMAIN_OVERVIEW as asset_ov
    from .l1_subject import DOMAIN_OVERVIEW as subject_ov
    from .l1_product import DOMAIN_OVERVIEW as product_ov
    from .l1_valuation import DOMAIN_OVERVIEW as valuation_ov
    from .l1_transaction import DOMAIN_OVERVIEW as transaction_ov
    from .l1_seller import DOMAIN_OVERVIEW as seller_ov
    from .l1_customer import DOMAIN_OVERVIEW as customer_ov
    from .l1_risk import DOMAIN_OVERVIEW as risk_ov
    from .l1_market import DOMAIN_OVERVIEW as market_ov
    from .l1_data_hub import DOMAIN_OVERVIEW as data_hub_ov
    
    return {
        "asset": asset_ov,
        "subject": subject_ov,
        "product": product_ov,
        "valuation": valuation_ov,
        "transaction": transaction_ov,
        "seller": seller_ov,
        "customer": customer_ov,
        "risk": risk_ov,
        "market": market_ov,
        "data_hub": data_hub_ov
    }


def get_all_table_profiles() -> Dict[str, TableProfile]:
    """获取所有L1单表画像"""
    all_profiles = {}
    from .l1_asset import TABLE_PROFILES as asset_profiles
    from .l1_subject import TABLE_PROFILES as subject_profiles
    from .l1_product import TABLE_PROFILES as product_profiles
    from .l1_valuation import TABLE_PROFILES as valuation_profiles
    from .l1_transaction import TABLE_PROFILES as transaction_profiles
    from .l1_seller import TABLE_PROFILES as seller_profiles
    from .l1_customer import TABLE_PROFILES as customer_profiles
    from .l1_risk import TABLE_PROFILES as risk_profiles
    from .l1_market import TABLE_PROFILES as market_profiles
    from .l1_data_hub import TABLE_PROFILES as data_hub_profiles
    
    for profiles in [
        asset_profiles, subject_profiles, product_profiles,
        valuation_profiles, transaction_profiles, seller_profiles,
        customer_profiles, risk_profiles, market_profiles, data_hub_profiles
    ]:
        all_profiles.update(profiles)
    
    return all_profiles


def get_all_intra_domain_profiles() -> Dict[str, IntraDomainProfile]:
    """获取所有L2域内画像"""
    from .l2_profiles import INTRA_DOMAIN_PROFILES
    return INTRA_DOMAIN_PROFILES


def get_all_cross_domain_profiles() -> Dict[str, CrossDomainProfile]:
    """获取所有L3跨域画像"""
    from .l3_profiles import CROSS_DOMAIN_PROFILES
    return CROSS_DOMAIN_PROFILES


def get_all_resonance_profiles() -> Dict[str, ResonanceProfile]:
    """获取所有L4联动画像"""
    from .l4_profiles import RESONANCE_PROFILES
    return RESONANCE_PROFILES


def get_datahub_scenario_views() -> dict:
    """获取 data_hub 域的5个典型分析场景视图"""
    from .datahub_scenario_views import DATAHUB_SCENARIO_VIEWS
    return DATAHUB_SCENARIO_VIEWS
