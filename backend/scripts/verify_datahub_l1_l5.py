"""
DataHub L1-L5 语义画像全量验证脚本

验证项:
  1. L1 字段画像数量
  2. L2 域内画像
  3. L3 跨域画像
  4. L4 共振场景 (新增2个)
  5. 场景视图 (5个) 并执行查询
"""
import sys
import json

sys.path.insert(0, r"d:\portfilio-end")

from pymongo import MongoClient


def main():
    print("=" * 70)
    print("  DataHub L1-L5 语义画像全量验证")
    print("=" * 70)

    errors = []
    passes = []

    # ─── L1 验证 ─────────────────────────────────────────
    print("\n[1] L1 单表画像 + 字段画像")
    try:
        from app.services.semantic_profiles.static_profiles.l1_data_hub import TABLE_PROFILES, DOMAIN_OVERVIEW

        assert DOMAIN_OVERVIEW.domain_code == "data_hub"
        assert len(TABLE_PROFILES) == 6, f"期望6张表，实际{len(TABLE_PROFILES)}"
        passes.append(f"L1: 6张表画像 ✓")

        # 检查字段画像
        core_tables = ["subject_risk_records", "zysc_ptl_info_records", "zysc_ptl_holder_records"]
        for t in core_tables:
            tp = TABLE_PROFILES.get(t)
            assert tp is not None, f"表 {t} 不存在"
            fp_count = len(tp.field_profiles)
            assert fp_count > 0, f"表 {t} 无字段画像"
            passes.append(f"L1: {t} 字段画像={fp_count} ✓")
            print(f"    {t}: {fp_count}个FieldProfile")

        # 批次表无字段画像
        batch_tables = [
            "subject_risk_import_batches",
            "zysc_ptl_info_import_batches",
            "zysc_ptl_holder_import_batches",
        ]
        for t in batch_tables:
            tp = TABLE_PROFILES.get(t)
            assert tp is not None, f"表 {t} 不存在"
            print(f"    {t}: {len(tp.field_profiles)}个FieldProfile (批次表)")

    except Exception as e:
        errors.append(f"L1 验证失败: {e}")
        print(f"    ✗ {e}")

    # ─── L2 验证 ─────────────────────────────────────────
    print("\n[2] L2 域内画像")
    try:
        from app.services.semantic_profiles.static_profiles.l2_profiles import INTRA_DOMAIN_PROFILES

        l2 = INTRA_DOMAIN_PROFILES.get("data_hub")
        assert l2 is not None, "data_hub L2画像不存在"
        assert len(l2.tables_involved) == 6
        assert len(l2.scenarios) >= 5
        passes.append(f"L2: data_hub域内画像 ✓ (场景数={len(l2.scenarios)})")
        print(f"    tables: {len(l2.tables_involved)}, scenarios: {len(l2.scenarios)}")
        print(f"    join_keys: {list(l2.join_keys.keys())}")
    except Exception as e:
        errors.append(f"L2 验证失败: {e}")
        print(f"    ✗ {e}")

    # ─── L3 验证 ─────────────────────────────────────────
    print("\n[3] L3 跨域画像")
    try:
        from app.services.semantic_profiles.static_profiles.l3_profiles import CROSS_DOMAIN_PROFILES

        datahub_l3 = {k: v for k, v in CROSS_DOMAIN_PROFILES.items()
                      if "data_hub" in v.domains_involved}
        assert len(datahub_l3) >= 2, f"data_hub跨域画像不足2个: {len(datahub_l3)}"
        passes.append(f"L3: data_hub跨域画像={len(datahub_l3)} ✓")
        for k, v in datahub_l3.items():
            print(f"    {k}: {v.profile_name} → {v.domains_involved}")
    except Exception as e:
        errors.append(f"L3 验证失败: {e}")
        print(f"    ✗ {e}")

    # ─── L4 验证 ─────────────────────────────────────────
    print("\n[4] L4 共振画像")
    try:
        from app.services.semantic_profiles.static_profiles.l4_profiles import RESONANCE_PROFILES

        datahub_l4 = {k: v for k, v in RESONANCE_PROFILES.items()
                      if "data_hub" in v.domains_involved}
        assert len(datahub_l4) >= 2, f"data_hub共振画像不足2个: {len(datahub_l4)}"
        passes.append(f"L4: data_hub共振画像={len(datahub_l4)} ✓")
        total_l4 = len(RESONANCE_PROFILES)
        print(f"    总共振场景: {total_l4}, data_hub相关: {len(datahub_l4)}")
        for k, v in datahub_l4.items():
            print(f"    {k}: {v.scenario_name}")
            print(f"      域: {v.domains_involved}")
            print(f"      预警指标: {len(v.warning_indicators)}个")
    except Exception as e:
        errors.append(f"L4 验证失败: {e}")
        print(f"    ✗ {e}")

    # ─── 场景视图验证 ──────────────────────────────────────
    print("\n[5] 场景视图 (5个)")
    try:
        from app.services.semantic_profiles.static_profiles.datahub_scenario_views import (
            DATAHUB_SCENARIO_VIEWS, execute_scenario
        )

        assert len(DATAHUB_SCENARIO_VIEWS) == 5, f"期望5个场景，实际{len(DATAHUB_SCENARIO_VIEWS)}"
        passes.append(f"场景视图: 5个场景定义 ✓")

        for sid, sv in DATAHUB_SCENARIO_VIEWS.items():
            print(f"    {sid}: {sv.scenario_name}")
            print(f"      涉及表: {sv.tables_involved}")
            print(f"      分析维度: {len(sv.analysis_dimensions)}个")
            print(f"      关联画像: {sv.related_profiles}")

        # 执行场景查询
        print("\n    --- 执行场景查询 ---")
        db = MongoClient("mongodb://localhost:27017")["asset_allocation"]

        for sid in DATAHUB_SCENARIO_VIEWS:
            try:
                results = execute_scenario(sid, db)
                total_records = 0
                for name, data in results.items():
                    if isinstance(data, list):
                        total_records += len(data)
                    elif isinstance(data, dict):
                        # multi-table results
                        for sub_name, sub_data in data.items():
                            if isinstance(sub_data, list):
                                total_records += len(sub_data)
                passes.append(f"场景 {sid}: 查询成功, 结果{total_records}条 ✓")
                print(f"    {sid}: 查询成功, {total_records}条结果")
            except Exception as e:
                errors.append(f"场景 {sid} 查询失败: {e}")
                print(f"    {sid}: ✗ {e}")

    except Exception as e:
        errors.append(f"场景视图验证失败: {e}")
        print(f"    ✗ {e}")

    # ─── ProfileEngine加载验证 ────────────────────────────
    print("\n[6] ProfileEngine 加载验证")
    try:
        from app.services.semantic_profiles.profile_engine import ProfileEngine

        engine = ProfileEngine.get_instance()
        dh_tables = [t for t, p in engine._table_profiles.items() if p.domain == "data_hub"]
        assert len(dh_tables) == 6, f"data_hub表画像数异常: {len(dh_tables)}"
        passes.append(f"ProfileEngine: 加载data_hub 6张表 ✓")

        l2_dh = engine._intra_domain_profiles.get("data_hub")
        assert l2_dh is not None
        passes.append(f"ProfileEngine: L2 data_hub ✓")

        l4_dh = {k: v for k, v in engine._resonance_profiles.items()
                 if "data_hub" in v.domains_involved}
        passes.append(f"ProfileEngine: L4 data_hub共振={len(l4_dh)} ✓")

        print(f"    data_hub表: {dh_tables}")
        print(f"    L2: ✓")
        print(f"    L4 data_hub共振: {list(l4_dh.keys())}")
    except Exception as e:
        errors.append(f"ProfileEngine加载失败: {e}")
        print(f"    ✗ {e}")

    # ─── 汇总 ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"  验证结果: {len(passes)}通过, {len(errors)}失败")
    print("=" * 70)

    if passes:
        print("\n  ✓ 通过项:")
        for p in passes:
            print(f"    {p}")

    if errors:
        print("\n  ✗ 失败项:")
        for e in errors:
            print(f"    {e}")
        sys.exit(1)
    else:
        print("\n  全部验证通过!")


if __name__ == "__main__":
    main()
