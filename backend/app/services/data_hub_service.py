"""
通用数据接入 Hub：HTTP 执行、导入、查询、统计

由 SubjectRiskService 与各连接器配置驱动；集合名 / 主键 / 图表配方均来自连接器注册表。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from loguru import logger
from pymongo import ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import BulkWriteError, PyMongoError

from app.config.database import Database
from app.models.data_connector import ConnectorDefinition, get_connector
from app.models.data_hub import (
    DataHubQueryRequest,
    DataHubImportJsonBody,
    build_get_py_result_payload,
    PtlInfoImportRequest,
    build_ptl_param_maps_payload,
)
from app.models.subject_risk import SubjectRiskImportRequest, SubjectRiskQueryRequest
from app.models.data_hub import DataHubFilterClause

_SUCCESS_CODES = {"0", "200", 0, 200}
_BULK_CHUNK = 500

# 主体舆情：上游 / 历史数据常见别名（标准键见 SUBJECT_RISK_FIELDS）
_SUBJECT_RISK_NAME_ALIASES: tuple[str, ...] = (
    "subject_name",
    "SUBJECT_NAME",
    "SubjectName",
    "subjectName",
    "客户名称",
    "主体名称",
    "COMPANY_NAME",
    "company_name",
)
_SUBJECT_RISK_LEVEL_ALIASES: tuple[str, ...] = (
    "risk_signal_level",
    "RISK_SIGNAL_LEVEL",
    "RiskSignalLevel",
    "风险等级",
    "signal_level",
    "RISK_LEVEL",
)
_SUBJECT_RISK_DESC_ALIASES: tuple[str, ...] = (
    "signal_dascribe",
    "signal_describe",
    "SIGNAL_DESCRIBE",
    "SignalDescribe",
    "风险描述",
    "信号描述",
    "signal_description",
)


def _coalesce_str_from_keys(doc: Dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k not in doc:
            continue
        v = doc.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("null", "none", ""):
            return s
    return None


def _enrich_subject_risk_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """库内或上游仅带别名键时，补齐 subject_name / risk_signal_level / signal_dascribe。"""
    if not doc:
        return doc
    out = dict(doc)
    name = _coalesce_str_from_keys(out, _SUBJECT_RISK_NAME_ALIASES)
    if name and not (str(out.get("subject_name") or "").strip()):
        out["subject_name"] = name
    lvl = _coalesce_str_from_keys(out, _SUBJECT_RISK_LEVEL_ALIASES)
    if lvl and not (str(out.get("risk_signal_level") or "").strip()):
        out["risk_signal_level"] = lvl
    if not (str(out.get("signal_dascribe") or "").strip()):
        desc = _coalesce_str_from_keys(out, _SUBJECT_RISK_DESC_ALIASES)
        if desc:
            out["signal_dascribe"] = desc
    return out


def _nested_get(root: Any, dotted: str) -> Any:
    cur: Any = root
    if not dotted:
        return cur
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _escape_regex(raw: str) -> str:
    if not raw:
        return ""
    return "".join("\\" + c if c in r".^$*+?()[]{}|\\" else c for c in raw)


def _connector_batch_filter(connector_id: str) -> Dict[str, Any]:
    """历史批次可能没有 connector_id 字段——仅主体风险连接器视作 subject_opinion_risk"""

    if connector_id == "subject_opinion_risk":
        return {"$or": [{"connector_id": connector_id}, {"connector_id": {"$exists": False}}]}
    return {"connector_id": connector_id}


class DataHubService:
    def __init__(self) -> None:
        self._db = None
        self._indexes: Dict[str, bool] = {}

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    def _coll(self, name: str):
        return self.db[name]

    def _index_key(self, connector_id: str, which: str) -> str:
        return f"{connector_id}:{which}"

    async def ensure_indexes(self, conn: ConnectorDefinition) -> None:
        k = self._index_key(conn.connector_id, "all")
        if self._indexes.get(k):
            return
        try:
            rec = self._coll(conn.records_collection)
            bat = self._coll(conn.batches_collection)
            for spec in conn.records_indexes:
                idx = [(f, d) for f, d in spec.fields]
                try:
                    await rec.create_index(idx, unique=spec.unique, name=spec.name)
                except Exception as idx_err:
                    # 索引已存在或名称冲突时跳过，不影响其他索引创建
                    logger.debug("[data-hub] 连接器 {} 索引 {} 跳过: {}", conn.connector_id, spec.name, idx_err)
            for spec in conn.batches_indexes:
                idx = [(f, d) for f, d in spec.fields]
                try:
                    await bat.create_index(idx, unique=spec.unique, name=spec.name)
                except Exception as idx_err:
                    logger.debug("[data-hub] 连接器 {} 批次索引 {} 跳过: {}", conn.connector_id, spec.name, idx_err)
            # 无论是否有单个索引失败，都标记为已尝试，避免重复尝试
            self._indexes[k] = True
            logger.debug("[data-hub] 连接器 {} 索引就绪", conn.connector_id)
        except Exception as e:
            # 集合级别异常（如连接失败），也标记避免重复连接失败
            self._indexes[k] = True
            logger.warning("[data-hub] 连接器 {} 创建索引失败: {}", conn.connector_id, e)

    @staticmethod
    async def _post_upstream(url: str, body: Dict[str, Any], timeout: float) -> Tuple[Dict[str, Any], float]:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"上游返回非 JSON：{resp.text[:200]}") from e
        if not isinstance(data, dict):
            raise RuntimeError(f"上游返回非对象类型：{type(data).__name__}")
        return data, elapsed_ms

    @staticmethod
    def _normalize_record(conn: ConnectorDefinition, raw: Dict[str, Any]) -> Dict[str, Any]:
        allow = set(conn.allowlist_fields)
        dates = set(conn.date_fields)
        out: Dict[str, Any] = {}
        for key in conn.allowlist_fields:
            if key not in raw:
                continue
            val = raw.get(key)
            if isinstance(val, str):
                stripped = val.strip()
                if stripped == "" or stripped.lower() in ("null", "none"):
                    val = None
                else:
                    val = stripped
            if key in dates and isinstance(val, str):
                val = DataHubService._try_parse_date(val)
            out[key] = val
        for key, val in raw.items():
            if key in out:
                continue
            if key.startswith("_"):
                continue
            if isinstance(val, (str, int, float, bool)) or val is None:
                out.setdefault(key, None if val == "" else val)

        parts_opt = getattr(conn, "compound_primary_fields", ()) or ()
        if parts_opt:
            sep = getattr(conn, "compound_primary_separator", None) or "|"
            plist: Optional[List[str]] = []
            for fld in parts_opt:
                v = out.get(fld)
                if v is None or v == "":
                    plist = None
                    break
                plist.append(str(v).strip())
            pk_name = conn.primary_key
            if plist is not None and len(plist) == len(parts_opt) and plist:
                out[pk_name] = sep.join(plist)

        if conn.connector_id == "subject_opinion_risk":
            merged = {**raw, **out}
            tmp = _enrich_subject_risk_document(merged)
            for fld in ("subject_name", "risk_signal_level", "signal_dascribe"):
                if fld not in allow:
                    continue
                v = tmp.get(fld)
                if v is not None and str(v).strip() and not (str(out.get(fld) or "").strip()):
                    out[fld] = v

        return out

    @staticmethod
    def _try_parse_date(val: str) -> str:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return val

    def _filter_allowed_field(self, conn: ConnectorDefinition, field: str) -> bool:
        allow = set(conn.distinct_allowlist_fields or conn.allowlist_fields)
        allow.update({"_batch_id", "_imported_at", conn.primary_key})
        return field in allow

    def _mongo_filter(self, conn: ConnectorDefinition, q: DataHubQueryRequest) -> Dict[str, Any]:
        filter_: Dict[str, Any] = {}
        if q.batch_id and q.batch_id.strip():
            filter_["_batch_id"] = q.batch_id.strip()

        rng: Dict[str, Dict[str, Any]] = {}
        for clause in q.filters:
            fld = clause.field.strip()
            if not self._filter_allowed_field(conn, fld):
                continue
            if clause.op == "eq":
                filter_[fld] = clause.value
            elif clause.op == "in" and isinstance(clause.value, list):
                filter_[fld] = {"$in": list(clause.value)}
            elif clause.op == "regex" and clause.value:
                filter_[fld] = {"$regex": _escape_regex(str(clause.value)), "$options": "i"}
            elif clause.op == "gte":
                rng.setdefault(fld, {})["$gte"] = clause.value
            elif clause.op == "lte":
                rng.setdefault(fld, {})["$lte"] = clause.value
        for fld, op in rng.items():
            filter_[fld] = op

        if q.keyword and q.keyword.strip():
            kw = _escape_regex(q.keyword.strip())
            ors = []
            for fld in conn.keyword_search_fields:
                if self._filter_allowed_field(conn, fld):
                    ors.append({fld: {"$regex": kw, "$options": "i"}})
            if ors:
                filter_["$or"] = ors
        return filter_

    async def import_from_upstream(
        self,
        connector_id: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """导入：connector_id + 请求体字典（get_py_result 族用 SubjectRiskImportRequest 校验）"""

        conn = get_connector(connector_id)
        if conn is None:
            return {"status": "failed_unknown", "error": f"未知连接器: {connector_id}"}

        if conn.family == "get_py_result":
            style = getattr(conn, "import_param_style", "date_range")
            if style == "ptl_param_maps":
                m = PtlInfoImportRequest(**body)
                url = (m.upstream_url or conn.default_upstream_url).strip()
                payload = build_ptl_param_maps_payload(m, conn.resource_default)
                timeout = m.timeout
            else:
                m = SubjectRiskImportRequest(**body)
                url = (m.upstream_url or conn.default_upstream_url).strip()
                payload = build_get_py_result_payload(
                    DataHubImportJsonBody(
                        startDate=m.startDate,
                        endDate=m.endDate,
                        rownum=m.rownum,
                        startrow=m.startrow,
                        resource=m.resource or conn.resource_default,
                        timeout=m.timeout,
                        upstream_url=m.upstream_url,
                    ),
                    conn.resource_default,
                )
                timeout = m.timeout
        else:
            return {"status": "failed_unknown", "error": "暂不支持的 family"}

        await self.ensure_indexes(conn)
        batch_id = uuid.uuid4().hex
        started = datetime.utcnow()
        started_at = started.strftime("%Y-%m-%dT%H:%M:%SZ")

        batch_doc: Dict[str, Any] = {
            "batch_id": batch_id,
            "connector_id": connector_id,
            "status": "running",
            "started_at": started_at,
            "finished_at": None,
            "duration_ms": 0,
            "params": payload,
            "upstream_url": url,
            "upstream_code": None,
            "upstream_message": None,
            "msg_list": [],
            "ind_name_list": [],
            "total_returned": 0,
            "inserted": 0,
            "updated": 0,
            "skipped_no_key": 0,
            "failed": 0,
            "error": None,
            "sample_errors": [],
            "upstream_page_msg": None,
            "upstream_records_count": None,
            "upstream_total_hint": None,
        }

        bound = logger.bind(connector_id=connector_id, batch_id=batch_id)
        bound.info("[data-hub][{}][{}] 开始导入 url={} params={}", connector_id, batch_id, url, payload)

        try:
            upstream, req_ms = await self._post_upstream(url, payload, timeout)
            bound.info("[data-hub][{}][{}] 上游成功 耗时={}ms", connector_id, batch_id, int(req_ms))
        except httpx.TimeoutException as e:
            bound.exception("[data-hub][{}] 上游超时: {}", connector_id, e)
            return await self._finalize_batch(conn, batch_doc, "failed_network", f"上游请求超时（{timeout}s）：{e}", started)
        except httpx.ConnectError as e:
            bound.exception("[data-hub][{}] 上游连接失败: {}", connector_id, e)
            return await self._finalize_batch(conn, batch_doc, "failed_network", f"上游连接失败：{e}", started)
        except httpx.HTTPStatusError as e:
            tb = e.response.text[:500] if e.response else ""
            bound.exception("[data-hub][{}] HTTP 错误 {}", connector_id, e.response.status_code if e.response else "")
            return await self._finalize_batch(
                conn, batch_doc, "failed_upstream", f"上游 HTTP {e.response.status_code if e.response else '?'}",
                started,
                upstream_code=str(e.response.status_code) if e.response else None,
                upstream_message=tb,
            )
        except Exception as e:
            bound.exception("[data-hub][{}] 上游异常: {}", connector_id, e)
            return await self._finalize_batch(conn, batch_doc, "failed_network", f"上游调用异常：{e}", started)

        upstream_code = str(upstream.get("code")) if upstream.get("code") is not None else None
        upstream_status = upstream.get("status")
        upstream_message = upstream.get("message")

        ml_path = conn.msg_list_path or "msg_list"
        ind_path = conn.ind_name_list_path or "ind_name_list"

        batch_doc["upstream_code"] = upstream_code
        batch_doc["upstream_message"] = upstream_message
        msg_list = _nested_get(upstream, ml_path) if "." in ml_path else upstream.get(ml_path)
        ind_name_list = _nested_get(upstream, ind_path) if "." in ind_path else upstream.get(ind_path)
        batch_doc["msg_list"] = msg_list if isinstance(msg_list, list) else []
        batch_doc["ind_name_list"] = ind_name_list if isinstance(ind_name_list, list) else []

        pg = upstream.get("pageMsg")
        if pg is None:
            batch_doc["upstream_page_msg"] = None
        elif isinstance(pg, str):
            batch_doc["upstream_page_msg"] = pg
        else:
            batch_doc["upstream_page_msg"] = str(pg)
        rc = upstream.get("records")
        if isinstance(rc, int):
            batch_doc["upstream_records_count"] = rc
        else:
            dc = upstream.get("dataCount")
            if dc is not None:
                try:
                    batch_doc["upstream_records_count"] = int(str(dc).strip())
                except ValueError:
                    batch_doc["upstream_records_count"] = None
            else:
                batch_doc["upstream_records_count"] = None
        th = upstream.get("total")
        batch_doc["upstream_total_hint"] = th if isinstance(th, int) else th

        rp = conn.records_path or "data"
        data_list = _nested_get(upstream, rp) if "." in rp else upstream.get(rp)
        if not isinstance(data_list, list):
            data_list = []

        batch_doc["total_returned"] = len(data_list)

        if upstream_code is not None and str(upstream_code) not in {str(x) for x in _SUCCESS_CODES}:
            bound.warning("[data-hub][{}][{}] 上游 code 非成功 code={}", connector_id, batch_id, upstream_code)
            return await self._finalize_batch(
                conn, batch_doc, "failed_upstream", f"上游返回 code={upstream_code}: {upstream_message}", started
            )
        if upstream_status is False:
            return await self._finalize_batch(
                conn, batch_doc, "failed_upstream", f"上游 status=false: {upstream_message}", started
            )

        if not data_list:
            empty_status = "partial" if batch_doc.get("upstream_page_msg") else "success"
            bound.info(
                "[data-hub][{}][{}] data 为空 status={} pageMsg={}",
                connector_id,
                batch_id,
                empty_status,
                batch_doc.get("upstream_page_msg"),
            )
            return await self._finalize_batch(conn, batch_doc, empty_status, None, started)

        pk = conn.primary_key
        records = self._coll(conn.records_collection)

        imported_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        ops: List[UpdateOne] = []
        inserted = updated = skipped_no_key = failed = 0
        sample_errors: List[str] = []

        for idx, raw in enumerate(data_list):
            if not isinstance(raw, dict):
                failed += 1
                if len(sample_errors) < 5:
                    sample_errors.append(f"idx={idx} 非对象：{type(raw).__name__}")
                continue
            try:
                rec = self._normalize_record(conn, raw)
            except Exception as e:
                failed += 1
                if len(sample_errors) < 5:
                    sample_errors.append(f"idx={idx} 解析失败：{e}")
                continue
            rid = rec.get(pk)
            if not rid or not isinstance(rid, str):
                skipped_no_key += 1
                if skipped_no_key <= 3:
                    bound.warning("[data-hub][{}][{}] 跳过无主键 idx={}", connector_id, batch_id, idx)
                continue
            rec["_batch_id"] = batch_id
            update_doc = {"$set": {**rec, "_imported_at": imported_at}, "$setOnInsert": {"_created_at": imported_at}}
            ops.append(UpdateOne({pk: rid}, update_doc, upsert=True))

            if len(ops) >= _BULK_CHUNK:
                ins, upd, f2, errs = await self._flush_ops(ops, records, bound, connector_id, batch_id)
                inserted += ins
                updated += upd
                failed += f2
                sample_errors.extend([x for x in errs if len(sample_errors) < 5])
                ops = []

        if ops:
            ins, upd, f2, errs = await self._flush_ops(ops, records, bound, connector_id, batch_id)
            inserted += ins
            updated += upd
            failed += f2
            sample_errors.extend([x for x in errs if len(sample_errors) < 5])

        batch_doc.update(
            inserted=inserted,
            updated=updated,
            skipped_no_key=skipped_no_key,
            failed=failed,
            sample_errors=sample_errors,
        )

        final_status = "success"
        if failed > 0 or skipped_no_key > 0:
            final_status = "partial"
        bound.info(
            "[data-hub][{}][{}] 完成 total={} ins={} upd={} skip={} fail={}",
            connector_id, batch_id, batch_doc["total_returned"], inserted, updated, skipped_no_key, failed,
        )
        return await self._finalize_batch(conn, batch_doc, final_status, None, started)

    async def _flush_ops(self, ops, collection, bound, connector_id: str, batch_id: str):
        if not ops:
            return 0, 0, 0, []
        try:
            result = await collection.bulk_write(ops, ordered=False)
            ins = int(getattr(result, "upserted_count", 0) or 0)
            matched = int(getattr(result, "matched_count", 0) or 0)
            bound.debug("[data-hub][{}][{}] bulk n={} upserted={} matched={}", connector_id, batch_id, len(ops), ins, matched)
            return ins, max(matched, 0), 0, []
        except BulkWriteError as bwe:
            details = getattr(bwe, "details", {}) or {}
            ins = int(details.get("nUpserted", 0) or 0)
            matched = int(details.get("nMatched", 0) or 0)
            write_errors = details.get("writeErrors") or []
            sample = [f"code={e.get('code')} msg={str(e.get('errmsg'))[:160]}" for e in write_errors[:3]]
            return ins, matched, len(write_errors), sample
        except PyMongoError as e:
            bound.exception("[data-hub][{}] bulk 异常 {}", connector_id, e)
            return 0, 0, len(ops), [f"PyMongoError: {e}"]
        except Exception as e:
            bound.exception("[data-hub][{}] bulk 未知异常 {}", connector_id, e)
            return 0, 0, len(ops), [f"Unknown: {e}"]

    async def _finalize_batch(
        self,
        conn: ConnectorDefinition,
        batch_doc: Dict[str, Any],
        status: str,
        error: Optional[str],
        started: datetime,
        upstream_code: Optional[str] = None,
        upstream_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        finished = datetime.utcnow()
        batch_doc["status"] = status
        batch_doc["error"] = error
        batch_doc["finished_at"] = finished.strftime("%Y-%m-%dT%H:%M:%SZ")
        batch_doc["duration_ms"] = int((finished - started).total_seconds() * 1000)
        if upstream_code is not None:
            batch_doc["upstream_code"] = upstream_code
        if upstream_message is not None and not batch_doc.get("upstream_message"):
            batch_doc["upstream_message"] = upstream_message

        try:
            await self._coll(conn.batches_collection).update_one(
                {"batch_id": batch_doc["batch_id"]}, {"$set": batch_doc}, upsert=True,
            )
        except Exception as e:
            logger.exception("[data-hub] 写入批次失败 {}: {}", batch_doc.get("batch_id"), e)

        return batch_doc

    async def query_records(self, connector_id: str, q: DataHubQueryRequest) -> Dict[str, Any]:
        conn = get_connector(connector_id)
        if not conn:
            raise ValueError("未知连接器")

        sort_allow = set(conn.allowlist_fields) | {"_imported_at", "_created_at", conn.primary_key}
        sort_field = q.sort_by if q.sort_by in sort_allow else "_imported_at"
        sort_dir = DESCENDING if q.sort_desc else ASCENDING

        await self.ensure_indexes(conn)
        filter_ = self._mongo_filter(conn, q)
        col = self._coll(conn.records_collection)
        total = await col.count_documents(filter_)
        skip = (q.page - 1) * q.page_size
        cur = (
            col.find(filter_, {"_id": 0}).sort(sort_field, sort_dir).skip(skip).limit(q.page_size)
        )
        items = [doc async for doc in cur]
        if connector_id == "subject_opinion_risk":
            items = [_enrich_subject_risk_document(dict(d)) for d in items]
        return {
            "items": items,
            "total": total,
            "page": q.page,
            "page_size": q.page_size,
            "pages": (total + q.page_size - 1) // q.page_size if q.page_size else 0,
        }

    async def list_batches(self, connector_id: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        conn = get_connector(connector_id)
        if not conn:
            raise ValueError("未知连接器")

        await self.ensure_indexes(conn)
        col = self._coll(conn.batches_collection)
        merged = _connector_batch_filter(connector_id)
        total = await col.count_documents(merged)
        cursor = (
            col.find(merged, {"_id": 0}).sort("started_at", DESCENDING).skip((page - 1) * page_size).limit(page_size)
        )
        items = [doc async for doc in cursor]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "pages": (total + page_size - 1) // page_size if page_size else 0}

    async def get_batch(self, connector_id: str, batch_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connector(connector_id)
        if not conn:
            return None
        await self.ensure_indexes(conn)
        doc = await self._coll(conn.batches_collection).find_one({"batch_id": batch_id}, {"_id": 0})
        if not doc:
            return None
        cid = doc.get("connector_id")
        if cid and cid != connector_id:
            return None
        if cid is None and connector_id != "subject_opinion_risk":
            return None
        return doc

    async def get_record_by_pk(self, connector_id: str, pk_val: str) -> Optional[Dict[str, Any]]:
        conn = get_connector(connector_id)
        if not conn:
            return None
        doc = await self._coll(conn.records_collection).find_one({conn.primary_key: pk_val}, {"_id": 0})
        if doc and connector_id == "subject_opinion_risk":
            return _enrich_subject_risk_document(dict(doc))
        return doc

    async def get_latest_fields(self, connector_id: str) -> List[Dict[str, Any]]:
        conn = get_connector(connector_id)
        if not conn:
            return []
        await self.ensure_indexes(conn)
        bf = _connector_batch_filter(connector_id)
        raw = await self._coll(conn.batches_collection).find_one(
            {"$and": [bf, {"ind_name_list": {"$exists": True, "$ne": []}}]},
            {"_id": 0, "ind_name_list": 1},
            sort=[("started_at", DESCENDING)],
        )
        if not raw:
            return []
        return raw.get("ind_name_list") or []

    async def distinct_values(self, connector_id: str, field: str, limit: int = 200) -> List[str]:
        conn = get_connector(connector_id)
        if not conn:
            return []
        if field not in (conn.distinct_allowlist_fields or []):
            return []
        await self.ensure_indexes(conn)
        try:
            vals = await self._coll(conn.records_collection).distinct(field, {field: {"$ne": None}})
            out = sorted([v for v in vals if isinstance(v, str) and v])[:limit]
            return out
        except Exception as e:
            logger.warning("[data-hub] distinct {} 失败 {}", field, e)
            return []

    async def stats_overview(self, connector_id: str) -> Dict[str, Any]:
        conn = get_connector(connector_id)
        if not conn:
            raise ValueError("未知连接器")

        await self.ensure_indexes(conn)
        col = self._coll(conn.records_collection)
        bcol = self._coll(conn.batches_collection)

        total = await col.count_documents({})

        merged = _connector_batch_filter(connector_id)
        total_batches = await bcol.count_documents(merged)

        def _norm(arr):
            return [
                {"label": (item.get("_id") or "未知"), "value": int(item.get("count") or 0)}
                for item in arr
            ]

        charts: Dict[str, Any] = {}
        legacy: Dict[str, Any] = {}
        recipes_out: List[Dict[str, Any]] = []

        for recipe in conn.chart_recipes:
            grp = recipe.group_by_field
            pipe = [
                {"$match": {grp: {"$ne": None}}},
                {"$group": {"_id": "$" + grp, "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": recipe.limit},
            ]
            agg = [x async for x in col.aggregate(pipe)]
            items = _norm(agg)

            charts[recipe.id] = {
                "title": recipe.title,
                "chart_type": recipe.chart_type,
                "group_by_field": grp,
                "items": items,
            }

            recipes_out.append({"id": recipe.id, **charts[recipe.id]})

            if recipe.legacy_flat_key:
                legacy[recipe.legacy_flat_key] = items

        latest_batch = await bcol.find_one(merged, {"_id": 0}, sort=[("started_at", DESCENDING)])

        out = {
            "connector_id": connector_id,
            "total_records": total,
            "total_batches": total_batches,
            "latest_batch": latest_batch,
            **legacy,
            "charts": charts,
            "chart_hints": recipes_out,
            "connector": {"title": conn.title, "badge_field": conn.badge_field},
        }
        return out


def subject_risk_legacy_query_to_hub(q: SubjectRiskQueryRequest) -> DataHubQueryRequest:
    """将 SubjectRiskQueryRequest 转为通用 Hub 查询"""

    clauses: List[DataHubFilterClause] = []
    if q.risk_signal_level:
        clauses.append(
            DataHubFilterClause(field="risk_signal_level", op="in", value=list(q.risk_signal_level)),
        )

    mapping = [
        ("subject_name", q.subject_name, "regex"),
        ("unified_social_credit_code", q.unified_social_credit_code, "eq"),
        ("affiliated_province", q.affiliated_province, "eq"),
        ("affiliated_city", q.affiliated_city, "eq"),
        ("enterprise_nature", q.enterprise_nature, "eq"),
        ("subject_type", q.subject_type, "eq"),
    ]

    for field, val, typ in mapping:
        if val and str(val).strip():
            v = val.strip()
            if typ == "regex":
                clauses.append(DataHubFilterClause(field=field, op="regex", value=v))
            else:
                clauses.append(DataHubFilterClause(field=field, op="eq", value=v))

    if q.biz_date_start:
        clauses.append(DataHubFilterClause(field="biz_date", op="gte", value=q.biz_date_start))
    if q.biz_date_end:
        clauses.append(DataHubFilterClause(field="biz_date", op="lte", value=q.biz_date_end))

    return DataHubQueryRequest(
        page=q.page,
        page_size=q.page_size,
        sort_by=q.sort_by or "_imported_at",
        sort_desc=q.sort_desc,
        batch_id=q.batch_id,
        keyword=q.keyword,
        filters=clauses,
    )


