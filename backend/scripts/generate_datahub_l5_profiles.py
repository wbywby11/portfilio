"""
生成 data_hub 域 L5 统计语义画像 (L5.1/L5.2/L5.3)

基于 StatsProfileEngine 的动态计算引擎，为 data_hub 三张核心表生成：
  L5.1 单表统计画像 (TableStatsProfile)
  L5.2 域级宏观画像 (DomainMacroProfile)
  L5.3 跨域联动画像 (CrossDomainResonance)

用法:
  python scripts/generate_datahub_l5_profiles.py          # 生成并打印
  python scripts/generate_datahub_l5_profiles.py --apply  # 写入MongoDB
"""
import asyncio
import json
import sys

sys.path.insert(0, r"d:\portfilio-end")

from loguru import logger


CORE_TABLES = [
    "subject_risk_records",
    "zysc_ptl_info_records",
    "zysc_ptl_holder_records",
]


async def generate_l5_profiles(apply: bool = False):
    """生成 data_hub 域 L5 画像"""

    # 初始化引擎（需要先加载静态画像）
    from app.services.semantic_profiles.profile_engine import ProfileEngine
    from app.services.semantic_profiles.stats_profile_engine import StatsProfileEngine

    engine = ProfileEngine.get_instance()
    stats_engine = StatsProfileEngine.get_instance()

    # ─── L5.1 单表统计画像 ─────────────────────────────────
    print("\n" + "=" * 70)
    print("  L5.1 单表统计画像")
    print("=" * 70)

    for table_name in CORE_TABLES:
        try:
            profile = await stats_engine.generate_table_stats_profile(table_name)
            print(f"\n  [{table_name}]")
            print(f"    物理基础: {profile.physical_basis[:100]}...")
            print(f"    截面分布: {profile.distribution[:100]}...")
            print(f"    时序趋势: {profile.trend[:100]}...")
            print(f"    异常极值: {profile.anomaly[:100]}...")
            print(f"    生成时间: {profile.computed_at}")
        except Exception as e:
            print(f"\n  [{table_name}] 生成失败: {e}")
            logger.exception(f"L5.1 生成失败 [{table_name}]")

    # ─── L5.2 域级宏观画像 ─────────────────────────────────
    print("\n" + "=" * 70)
    print("  L5.2 域级宏观画像 (data_hub)")
    print("=" * 70)

    try:
        macro = await stats_engine.generate_domain_macro("data_hub")
        print(f"\n  域边界: {macro.boundary[:120]}...")
        print(f"  宏观分布: {macro.macro_distribution[:120]}...")
        print(f"  宏观趋势: {macro.macro_trend[:120]}...")
        print(f"  系统预警: {macro.system_warning[:120]}...")
        print(f"  生成时间: {macro.computed_at}")
        if macro.tables_stats_summary:
            print(f"  表统计摘要:")
            for t, s in macro.tables_stats_summary.items():
                print(f"    {t}: records={s.get('record_count')}, fields={s.get('field_count')}")
    except Exception as e:
        print(f"\n  域宏观画像生成失败: {e}")
        logger.exception("L5.2 生成失败")

    # ─── L5.3 跨域联动画像 ─────────────────────────────────
    print("\n" + "=" * 70)
    print("  L5.3 跨域联动画像")
    print("=" * 70)

    try:
        cross_list = await stats_engine.generate_cross_resonance()
        # 只打印 data_hub 相关的
        datahub_cross = [c for c in cross_list if "data_hub" in c.domains_involved]
        all_cross = cross_list

        print(f"\n  全部场景数: {len(all_cross)}")
        print(f"  data_hub相关场景数: {len(datahub_cross)}")

        for item in datahub_cross:
            print(f"\n  [{item.scenario_id}] {item.scenario_name}")
            print(f"    涉及域: {', '.join(item.domains_involved)}")
            print(f"    场景定义: {item.scenario_definition[:100]}...")
            print(f"    跨域结构: {item.cross_structure[:100]}...")
            print(f"    共振趋势: {item.resonance_trend[:100]}...")
            print(f"    极端脱钩: {item.extreme_decoupling[:100]}...")
    except Exception as e:
        print(f"\n  跨域联动画像生成失败: {e}")
        logger.exception("L5.3 生成失败")

    if not apply:
        print("\n[DRY-RUN] 未写入数据库。使用 --apply 参数写入。")
    else:
        print("\n[APPLY] 已通过引擎自动写入 MongoDB。")

    print("\n生成完成。")


def main():
    apply_mode = "--apply" in sys.argv
    asyncio.run(generate_l5_profiles(apply=apply_mode))


if __name__ == "__main__":
    main()
