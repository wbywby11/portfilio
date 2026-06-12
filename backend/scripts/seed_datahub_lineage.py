"""
数据接入域血缘图谱注入脚本

向 lineage_nodes / lineage_edges 注入 data_hub 域的：
1. 上游API源节点（3个）
2. 存储节点（6个集合）
3. 数据流边（SOURCE_API → STORAGE）
4. 跨域引用边（data_hub → 9域表）

用法：
  python scripts/seed_datahub_lineage.py          # 执行注入
  python scripts/seed_datahub_lineage.py --dry-run # 仅预览
"""
import asyncio
import sys
from datetime import datetime

sys.path.insert(0, ".")


def main():
    dry_run = "--dry-run" in sys.argv
    from pymongo import MongoClient
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]

    now = datetime.now().isoformat()

    # ── 1. 上游API源节点 ──
    source_nodes = [
        {
            "node_id": "SOURCE_API:data_hub:adm_subject_opinion_risk_stats:1.0",
            "node_type": "SOURCE_API",
            "domain": "data_hub",
            "name": "adm_subject_opinion_risk_stats",
            "display_name": "上游·主体观点风险统计接口",
            "metadata": {"resource": "adm_subject_opinion_risk_stats", "protocol": "HTTP POST"},
        },
        {
            "node_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_INFO:1.0",
            "node_type": "SOURCE_API",
            "domain": "data_hub",
            "name": "ZYSC_DWD_PTL_INFO",
            "display_name": "上游·产品信息表接口",
            "metadata": {"resource": "ZYSC_DWD_PTL_INFO", "protocol": "HTTP POST"},
        },
        {
            "node_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_HOLDER_SUMMARY:1.0",
            "node_type": "SOURCE_API",
            "domain": "data_hub",
            "name": "ZYSC_DWD_PTL_HOLDER_SUMMARY",
            "display_name": "上游·产品持有人汇总接口",
            "metadata": {"resource": "ZYSC_DWD_PTL_HOLDER_SUMMARY", "protocol": "HTTP POST"},
        },
    ]

    # ── 2. MongoDB 存储节点 ──
    storage_nodes = []
    for col_name, display in [
        ("subject_risk_records", "主体观点风险记录表"),
        ("subject_risk_import_batches", "主体风险导入批次表"),
        ("zysc_ptl_info_records", "产品信息记录表"),
        ("zysc_ptl_info_import_batches", "产品信息导入批次表"),
        ("zysc_ptl_holder_records", "产品持有人汇总记录表"),
        ("zysc_ptl_holder_import_batches", "产品持有人导入批次表"),
    ]:
        cnt = db[col_name].count_documents({})
        storage_nodes.append({
            "node_id": f"STORAGE_MONGO:data_hub:{col_name}:1.0",
            "node_type": "STORAGE_MONGO",
            "domain": "data_hub",
            "name": col_name,
            "display_name": display,
            "metadata": {"record_count": cnt},
        })

    # ── 3. 数据流边（API → Storage） ──
    flow_edges = [
        {
            "edge_id": "SOURCE_API:data_hub:adm_subject_opinion_risk_stats:1.0--DATA_FLOW-->STORAGE_MONGO:data_hub:subject_risk_records:1.0",
            "source_id": "SOURCE_API:data_hub:adm_subject_opinion_risk_stats:1.0",
            "target_id": "STORAGE_MONGO:data_hub:subject_risk_records:1.0",
            "edge_type": "DATA_FLOW",
            "label": "导入风险数据",
        },
        {
            "edge_id": "SOURCE_API:data_hub:adm_subject_opinion_risk_stats:1.0--DATA_FLOW-->STORAGE_MONGO:data_hub:subject_risk_import_batches:1.0",
            "source_id": "SOURCE_API:data_hub:adm_subject_opinion_risk_stats:1.0",
            "target_id": "STORAGE_MONGO:data_hub:subject_risk_import_batches:1.0",
            "edge_type": "DATA_FLOW",
            "label": "记录批次",
        },
        {
            "edge_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_INFO:1.0--DATA_FLOW-->STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0",
            "source_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_INFO:1.0",
            "target_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0",
            "edge_type": "DATA_FLOW",
            "label": "导入产品信息",
        },
        {
            "edge_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_INFO:1.0--DATA_FLOW-->STORAGE_MONGO:data_hub:zysc_ptl_info_import_batches:1.0",
            "source_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_INFO:1.0",
            "target_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_import_batches:1.0",
            "edge_type": "DATA_FLOW",
            "label": "记录批次",
        },
        {
            "edge_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_HOLDER_SUMMARY:1.0--DATA_FLOW-->STORAGE_MONGO:data_hub:zysc_ptl_holder_records:1.0",
            "source_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_HOLDER_SUMMARY:1.0",
            "target_id": "STORAGE_MONGO:data_hub:zysc_ptl_holder_records:1.0",
            "edge_type": "DATA_FLOW",
            "label": "导入持有人数据",
        },
        {
            "edge_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_HOLDER_SUMMARY:1.0--DATA_FLOW-->STORAGE_MONGO:data_hub:zysc_ptl_holder_import_batches:1.0",
            "source_id": "SOURCE_API:data_hub:ZYSC_DWD_PTL_HOLDER_SUMMARY:1.0",
            "target_id": "STORAGE_MONGO:data_hub:zysc_ptl_holder_import_batches:1.0",
            "edge_type": "DATA_FLOW",
            "label": "记录批次",
        },
    ]

    # ── 4. 跨域引用边（data_hub → 9域） ──
    ref_edges = [
        # 风险主体 → 主体域机构表
        {
            "edge_id": "STORAGE_MONGO:data_hub:subject_risk_records:1.0--REFERENCE-->STORAGE_MONGO:subject:dwd_isr_institution:1.0",
            "source_id": "STORAGE_MONGO:data_hub:subject_risk_records:1.0",
            "target_id": "STORAGE_MONGO:subject:dwd_isr_institution:1.0",
            "edge_type": "REFERENCE",
            "label": "主体名称→ISR_NM",
        },
        # 风险主体 → 风险域舆情表
        {
            "edge_id": "STORAGE_MONGO:data_hub:subject_risk_records:1.0--REFERENCE-->STORAGE_MONGO:risk:dwd_rsk_sentiment:1.0",
            "source_id": "STORAGE_MONGO:data_hub:subject_risk_records:1.0",
            "target_id": "STORAGE_MONGO:risk:dwd_rsk_sentiment:1.0",
            "edge_type": "REFERENCE",
            "label": "双源舆情融合",
        },
        # 产品信息 → 产品域产品表
        {
            "edge_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0--REFERENCE-->STORAGE_MONGO:product:dwd_ptl_info:1.0",
            "source_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0",
            "target_id": "STORAGE_MONGO:product:dwd_ptl_info:1.0",
            "edge_type": "REFERENCE",
            "label": "产品代码→PORT_ID",
        },
        # 产品信息 → 主体域(管理人)
        {
            "edge_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0--REFERENCE-->STORAGE_MONGO:subject:dwd_isr_institution:1.0",
            "source_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0",
            "target_id": "STORAGE_MONGO:subject:dwd_isr_institution:1.0",
            "edge_type": "REFERENCE",
            "label": "管理人→ISR_NM",
        },
        # 持有人 → 产品域持有人汇总表
        {
            "edge_id": "STORAGE_MONGO:data_hub:zysc_ptl_holder_records:1.0--REFERENCE-->STORAGE_MONGO:product:dwd_ptl_holder_summary:1.0",
            "source_id": "STORAGE_MONGO:data_hub:zysc_ptl_holder_records:1.0",
            "target_id": "STORAGE_MONGO:product:dwd_ptl_holder_summary:1.0",
            "edge_type": "REFERENCE",
            "label": "双源持有人融合",
        },
        # 持有人 → 产品信息（域内）
        {
            "edge_id": "STORAGE_MONGO:data_hub:zysc_ptl_holder_records:1.0--REFERENCE-->STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0",
            "source_id": "STORAGE_MONGO:data_hub:zysc_ptl_holder_records:1.0",
            "target_id": "STORAGE_MONGO:data_hub:zysc_ptl_info_records:1.0",
            "edge_type": "REFERENCE",
            "label": "产品代码关联",
        },
    ]

    # ── 执行注入 ──
    all_nodes = source_nodes + storage_nodes
    all_edges = flow_edges + ref_edges

    if dry_run:
        print(f"[DRY-RUN] 将注入 {len(all_nodes)} 个节点, {len(all_edges)} 条边")
        for n in all_nodes:
            print(f"  NODE: {n['node_id']}  ({n['display_name']})")
        for e in all_edges:
            print(f"  EDGE: {e['source_id'].split(':')[2]} --{e['edge_type']}--> {e['target_id'].split(':')[2]}  [{e['label']}]")
        return

    # upsert nodes
    for node in all_nodes:
        node["updated_at"] = now
        db["lineage_nodes"].update_one(
            {"node_id": node["node_id"]},
            {"$set": node, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

    # upsert edges
    for edge in all_edges:
        created = edge.pop("created_at", None) or now
        db["lineage_edges"].update_one(
            {"edge_id": edge["edge_id"]},
            {"$set": edge, "$setOnInsert": {"created_at": created}},
            upsert=True,
        )

    # 统计
    total_nodes = db["lineage_nodes"].count_documents({})
    total_edges = db["lineage_edges"].count_documents({})
    print(f"注入完成: {len(all_nodes)} 个节点, {len(all_edges)} 条边")
    print(f"全局统计: {total_nodes} 节点, {total_edges} 边")

    client.close()


def run():
    main()


if __name__ == "__main__":
    run()
