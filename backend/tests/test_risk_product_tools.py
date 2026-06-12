"""subject_risk / product_hub 工具：日期窗与过滤器构造单测."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase, mock

# App 根目录加入 path（直接 python -m unittest 时）

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.agent.tools.risk_product_tools import (
    SubjectRiskSearchTool,
    biz_date_window_for_months,
    build_subject_risk_filters,
    ProductHubQueryTool,
)
import app.agent.tools.risk_product_tools as risk_tools


class RiskProductToolFiltersTests(TestCase):
    def test_biz_date_window_span(self):
        fixed = date(2026, 4, 24)
        with mock.patch("app.agent.tools.risk_product_tools.date") as mdate:
            mdate.today = mock.Mock(return_value=fixed)
            start, end = biz_date_window_for_months(3)
        self.assertEqual(end, "2026-04-24")
        # 90 日前
        self.assertEqual(start, "2026-01-24")

    def test_subject_risk_filters_has_date_province_levels(self):
        fixed = date(2026, 4, 24)
        with mock.patch("app.agent.tools.risk_product_tools.date") as mdate:
            mdate.today = mock.Mock(return_value=fixed)
            clauses = build_subject_risk_filters(
                months=3,
                biz_date_field="biz_date",
                affiliated_province="江苏省",
                industry_contains="制造业",
                risk_signal_level=["高", "中"],
                signal_keyword="处罚",
            )
        dumped = [c.model_dump() for c in clauses]
        self.assertTrue(any(x["field"] == "biz_date" and x["op"] == "gte" for x in dumped))
        self.assertTrue(any(x["field"] == "biz_date" and x["op"] == "lte" for x in dumped))
        self.assertEqual(
            next(x for x in dumped if x["field"] == "affiliated_province"),
            {"field": "affiliated_province", "op": "eq", "value": "江苏省"},
        )
        self.assertEqual(
            next(x for x in dumped if x["field"] == "industry_classification_gb"),
            {"field": "industry_classification_gb", "op": "regex", "value": "制造业"},
        )
        self.assertEqual(
            next(x for x in dumped if x["field"] == "risk_signal_level"),
            {"field": "risk_signal_level", "op": "in", "value": ["高", "中"]},
        )
        self.assertEqual(
            next(x for x in dumped if x["field"] == "signal_dascribe"),
            {"field": "signal_dascribe", "op": "regex", "value": "处罚"},
        )


class SubjectRiskToolExecuteTests(IsolatedAsyncioTestCase):
    async def test_execute_calls_upstream_then_query(self):
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION = True
            hub.import_from_upstream = mock.AsyncMock(
                return_value={
                    "status": "success",
                    "batch_id": "b1",
                    "inserted": 1,
                    "updated": 0,
                    "total_returned": 5,
                }
            )
            hub.query_records = mock.AsyncMock(
                return_value={"items": [], "total": 0, "page": 1, "page_size": 30, "pages": 0}
            )
            tool = SubjectRiskSearchTool()
            r = await tool.execute(months=3)
        self.assertTrue(r.get("success"))
        hub.import_from_upstream.assert_awaited_once()
        hub.query_records.assert_awaited_once()
        self.assertIn("upstream_sync", r["data"])

    async def test_execute_skips_upstream_when_flag(self):
        with mock.patch("app.agent.tools.risk_product_tools._hub") as hub:
            hub.import_from_upstream = mock.AsyncMock()
            hub.query_records = mock.AsyncMock(
                return_value={"items": [], "total": 0, "page": 1, "page_size": 30, "pages": 0}
            )
            tool = SubjectRiskSearchTool()
            r = await tool.execute(months=3, skip_upstream_sync=True)
        self.assertTrue(r.get("success"))
        hub.import_from_upstream.assert_not_called()
        self.assertEqual(r["data"]["upstream_sync"].get("attempted"), False)

    async def test_execute_second_call_same_conversation_skips_upstream(self):
        risk_tools._subject_risk_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION = True
            hub.import_from_upstream = mock.AsyncMock(
                return_value={
                    "status": "success",
                    "batch_id": "b1",
                    "inserted": 1,
                    "updated": 0,
                    "total_returned": 5,
                }
            )
            hub.query_records = mock.AsyncMock(
                return_value={"items": [], "total": 0, "page": 1, "page_size": 30, "pages": 0}
            )
            tool = SubjectRiskSearchTool()
            await tool.execute(months=3, conversation_id="c-demo")
            await tool.execute(months=3, conversation_id="c-demo")
        self.assertEqual(hub.import_from_upstream.await_count, 1)
        self.assertEqual(hub.query_records.await_count, 2)


class SubjectRiskAPIFailureFallbackTests(IsolatedAsyncioTestCase):
    """P3 环境 API 失败流程测试：上游异常 + 本地无数据、有数据场景"""

    async def test_upstream_exception_local_empty_returns_no_retry_hint(self):
        """上游 API 抛异常且本地库无数据：应返回 _no_retry=True + _instruction"""
        risk_tools._subject_risk_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION = True
            # 模拟上游超时/网络异常
            hub.import_from_upstream = mock.AsyncMock(
                side_effect=Exception("ConnectionTimeout: P3 内网 API 不可达")
            )
            # 本地库无数据
            hub.query_records = mock.AsyncMock(
                return_value={"items": [], "total": 0, "page": 1, "page_size": 30, "pages": 0}
            )
            tool = SubjectRiskSearchTool()
            r = await tool.execute(months=6, conversation_id="c-p3-fail")

        self.assertTrue(r.get("success"))
        data = r["data"]
        self.assertEqual(data["total"], 0)
        self.assertTrue(data.get("_no_retry"))
        self.assertIn("请勿重复调用", data.get("_instruction", ""))
        # upstream_sync 应记录异常信息
        sync = data["upstream_sync"]
        self.assertTrue(sync["attempted"])
        self.assertEqual(sync["outcome"], "exception")
        self.assertIn("P3", sync.get("error", ""))

    async def test_upstream_failed_status_local_empty(self):
        """上游返回 status=failed 且本地库无数据"""
        risk_tools._subject_risk_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION = True
            hub.import_from_upstream = mock.AsyncMock(
                return_value={
                    "status": "failed",
                    "batch_id": "b-fail",
                    "error": "upstream returned HTTP 500",
                    "inserted": 0,
                    "updated": 0,
                    "total_returned": 0,
                }
            )
            hub.query_records = mock.AsyncMock(
                return_value={"items": [], "total": 0, "page": 1, "page_size": 30, "pages": 0}
            )
            tool = SubjectRiskSearchTool()
            r = await tool.execute(months=3, conversation_id="c-p3-fail2")

        data = r["data"]
        self.assertTrue(data.get("_no_retry"))
        self.assertEqual(data["upstream_sync"]["outcome"], "failed_or_empty")

    async def test_upstream_exception_local_has_data_returns_normally(self):
        """上游异常但本地库有历史数据：应正常返回结果（无 _no_retry）"""
        risk_tools._subject_risk_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION = True
            hub.import_from_upstream = mock.AsyncMock(
                side_effect=Exception("ConnectionTimeout")
            )
            # 本地库有历史数据
            hub.query_records = mock.AsyncMock(
                return_value={
                    "items": [
                        {"risk_id": "R001", "biz_date": "2026-04-01", "risk_signal_level": "高",
                         "affiliated_province": "江苏省", "signal_dascribe": "处罚信息"},
                        {"risk_id": "R002", "biz_date": "2026-03-15", "risk_signal_level": "中",
                         "affiliated_province": "浙江省", "signal_dascribe": "舆情事件"},
                    ],
                    "total": 1173,
                    "page": 1,
                    "page_size": 30,
                    "pages": 40,
                }
            )
            tool = SubjectRiskSearchTool()
            r = await tool.execute(months=6, conversation_id="c-p3-local")

        data = r["data"]
        self.assertEqual(data["total"], 1173)
        self.assertFalse(data.get("_no_retry", False))
        self.assertEqual(len(data["items"]), 2)
        # 应有大数据量提示
        self.assertIn("1173", r.get("summary", ""))
        self.assertIn("无需再次调用", r.get("summary", ""))

    async def test_large_dataset_summary_hint(self):
        """当返回 total > 100 时，summary 应包含“无需再次调用”提示"""
        risk_tools._subject_risk_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION = True
            hub.import_from_upstream = mock.AsyncMock(
                return_value={
                    "status": "success", "batch_id": "b-big",
                    "inserted": 500, "updated": 673, "total_returned": 1173,
                }
            )
            hub.query_records = mock.AsyncMock(
                return_value={
                    "items": [{"risk_id": f"R{i}", "biz_date": "2026-04-01"} for i in range(30)],
                    "total": 1173,
                    "page": 1,
                    "page_size": 30,
                    "pages": 40,
                }
            )
            tool = SubjectRiskSearchTool()
            r = await tool.execute(months=6, conversation_id="c-big")

        self.assertIn("无需再次调用", r.get("summary", ""))
        self.assertIn("1173", r.get("summary", ""))


class ProductHubQueryToolExecuteTests(IsolatedAsyncioTestCase):
    async def test_execute_slims_ptl_fields(self):
        risk_tools._product_hub_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_PRODUCT_HUB_ONE_SYNC_PER_CONVERSATION = False
            hub.import_from_upstream = mock.AsyncMock(
                return_value={
                    "status": "success",
                    "batch_id": "b1",
                    "inserted": 1,
                    "updated": 0,
                    "total_returned": 3,
                }
            )
            hub.query_records = mock.AsyncMock(
                return_value={
                    "items": [
                        {
                            "产品代码": "2024DEMO001",
                            "产品名称": "示例理财",
                            "产品简称": "示例",
                            "合约基准_上限": "0.025",
                            "合约基准_平均": "0.024",
                            "noise_col_should_drop": "x" * 500,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 25,
                    "pages": 1,
                }
            )
            tool = ProductHubQueryTool()
            r = await tool.execute(
                connector_id="zysc_dwd_ptl_info",
                conversation_id="c-ph1",
            )
        self.assertTrue(r.get("success"))
        item = r["data"]["items"][0]
        self.assertEqual(item.get("产品代码"), "2024DEMO001")
        self.assertEqual(item.get("合约基准上限"), "0.025")
        self.assertEqual(item.get("合约基准平均"), "0.024")
        self.assertNotIn("noise_col_should_drop", item)
        self.assertTrue(r["data"].get("items_full_fields_in_db"))

    async def test_execute_second_call_same_conversation_skips_upstream(self):
        risk_tools._product_hub_conv_upstream_done.clear()
        with (
            mock.patch("app.agent.tools.risk_product_tools.settings") as ms,
            mock.patch("app.agent.tools.risk_product_tools._hub") as hub,
        ):
            ms.AGENT_SYNC_HUB_BEFORE_QUERY = True
            ms.AGENT_HUB_IMPORT_ROWNUM = 1000
            ms.AGENT_HUB_IMPORT_TIMEOUT = 30.0
            ms.AGENT_PRODUCT_HUB_ONE_SYNC_PER_CONVERSATION = True
            hub.import_from_upstream = mock.AsyncMock(
                return_value={
                    "status": "success",
                    "batch_id": "b1",
                    "inserted": 1,
                    "updated": 0,
                    "total_returned": 3,
                }
            )
            hub.query_records = mock.AsyncMock(
                return_value={"items": [], "total": 0, "page": 1, "page_size": 25, "pages": 0}
            )
            tool = ProductHubQueryTool()
            await tool.execute(
                connector_id="zysc_dwd_ptl_info", conversation_id="c-ph2"
            )
            await tool.execute(
                connector_id="zysc_dwd_ptl_info", conversation_id="c-ph2"
            )
        self.assertEqual(hub.import_from_upstream.await_count, 1)
        self.assertEqual(hub.query_records.await_count, 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
