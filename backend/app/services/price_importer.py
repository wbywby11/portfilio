# -*- coding: utf-8 -*-
"""
资产服务 Mixin：行情导入引擎（写入、预览、交易日历、缺口检测）

自 asset_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 行情行解析辅助（稀疏字段、收盘价校验、日期归一）
2. 导入主流程 import_price_data（按日合并 / 全量替换，分批写入，进度上报）
3. 导入预览与库状态查询（已有日期、正收盘价日期、区间边界）
4. 交易日历加载与行情缺口检测
"""

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any

import pandas as pd
from pymongo import UpdateOne

from app.models.asset import AssetPrice
from app.services.price_import_progress import touch_progress

PRICE_IMPORT_BATCH_SIZE = 2000

_PRICE_NUM_FIELDS = ("open", "high", "low", "close", "volume", "amount", "scale")


def _is_blank_val(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    return False


def _sparse_price_fields(price_data: dict) -> Dict[str, Any]:
    """从一行导入数据中提取非空的行情数字字段（不含 date）。"""
    sparse: Dict[str, Any] = {}
    for k in _PRICE_NUM_FIELDS:
        if k not in price_data:
            continue
        v = price_data.get(k)
        if _is_blank_val(v):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if isinstance(fv, float) and pd.isna(fv):
            continue
        if k == "close" and fv <= 0:
            continue
        if k == "volume":
            sparse[k] = int(round(fv))
        else:
            sparse[k] = fv
    return sparse

def _effective_close_for_sparse(sp: Dict[str, Any]) -> Optional[float]:
    """（保留）由 OHLC 推断有效价；新交易日插入已改为须显式收盘价，本函数仅用于兼容旧逻辑/文档。"""
    for k in ("close", "high", "low", "open"):
        v = sp.get(k)
        if v is not None and float(v) > 0:
            return float(v)
    return None

def _explicit_close_positive(sp: Dict[str, Any]) -> bool:
    """是否在本行提供了大于 0 的收盘价（新交易日插入、全量覆盖行的必要条件）。"""
    v = sp.get("close")
    if v is None or _is_blank_val(v):
        return False
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False

def _normalize_import_date(date_raw: Any) -> str:
    if date_raw is None:
        raise ValueError("日期为空")
    if hasattr(date_raw, "strftime"):
        return date_raw.strftime("%Y-%m-%d")
    if isinstance(date_raw, str):
        s0 = date_raw.strip()
        ds = s0.replace("-", "").replace("/", "").strip()
        if len(ds) == 8 and ds.isdigit():
            return datetime.strptime(ds, "%Y%m%d").strftime("%Y-%m-%d")
        try:
            return datetime.strptime(s0.replace("/", "-"), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"日期格式错误: {date_raw}")
    raise ValueError(f"日期类型不支持: {type(date_raw)}")

def _full_price_document(
    asset_code: str, date_formatted: str, sparse: Dict[str, Any], close_val: float
) -> dict:
    """写入新文档时的完整行情行（未出现的 OHLC 为 None）。"""
    return {
        "asset_code": asset_code,
        "date": date_formatted,
        "open": sparse.get("open"),
        "high": sparse.get("high"),
        "low": sparse.get("low"),
        "close": close_val,
        "volume": sparse.get("volume"),
        "amount": sparse.get("amount"),
        "scale": sparse.get("scale"),
    }



class PriceImporterMixin:
    """行情导入引擎方法群。

    依赖宿主（AssetService）：price_collection / db 属性。
    """

    async def load_trade_calendar_date_set(self) -> Optional[Set[str]]:
        """
        加载交易日集合（YYYY-MM-DD），用于导入时跳过非交易日。

        同时读取 Mongo ``trade_dates`` 集合与 ``data/trade_dates.xlsx`` 并取并集，
        任一来源认为是交易日即视为交易日，避免增量只同步了某一边（如只更新了 xlsx 
        但未同步到 Mongo）时部分交易日被误判为非交易日。两者皆无有效数据时返回 None，
        导入不做日历过滤。
        """
        out: Set[str] = set()

        # 来源 1：Mongo trade_dates 集合
        mongo_count = 0
        try:
            from app.config.collections import COL_TRADE_DATES
            col = self.db[COL_TRADE_DATES]
            cursor = col.find({}).sort("date", 1)
            records = await cursor.to_list(length=None)
            for r in records or []:
                dt = r.get("date")
                if dt is None:
                    continue
                if hasattr(dt, "strftime"):
                    out.add(dt.strftime("%Y-%m-%d")[:10])
                    mongo_count += 1
                elif isinstance(dt, str):
                    s = dt.strip()
                    if len(s) >= 10:
                        out.add(s[:10])
                        mongo_count += 1
        except Exception:
            pass

        # 来源 2：data/trade_dates.xlsx，无论 Mongo 是否有值都合并
        xlsx_count = 0
        try:
            from app.data.trade_dates import load_trade_dates

            loaded = load_trade_dates()
            if loaded:
                _, td_set = loaded
                for d in td_set:
                    out.add(pd.Timestamp(d).strftime("%Y-%m-%d"))
                    xlsx_count += 1
        except Exception:
            pass

        if not out:
            return None
        # 调试日志：便于后续排查两侧是否同步
        try:
            max_date = max(out)
            print(
                f"[trade_calendar] mongo={mongo_count} xlsx={xlsx_count} "
                f"union={len(out)} max_date={max_date}"
            )
        except Exception:
            pass
        return out

    async def get_price_coverage_gaps(
        self,
        asset_code: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """
        对比「区间内应有交易日」与 Mongo 中已有行情日期，返回缺失日列表。
        优先使用 data/trade_dates.xlsx；若无文件则用工作日（周一至周五）近似。
        """
        from app.data.trade_dates import load_trade_dates

        s_str = start_date.strftime("%Y-%m-%d")
        e_str = end_date.strftime("%Y-%m-%d")

        loaded = load_trade_dates()
        if loaded:
            td_list, _ = loaded
            expected: List[str] = []
            for d in td_list:
                ds = pd.Timestamp(d).strftime("%Y-%m-%d")
                if s_str <= ds <= e_str:
                    expected.append(ds)
            mode = "trade_calendar"
        else:
            bdays = pd.bdate_range(start=s_str, end=e_str)
            expected = [x.strftime("%Y-%m-%d") for x in bdays]
            mode = "business_days"

        expected_set = set(expected)
        existing: set = set()
        cursor = self.price_collection.find(
            {"asset_code": asset_code, "date": {"$gte": s_str, "$lte": e_str}},
            {"date": 1},
        )
        async for doc in cursor:
            dt = doc.get("date")
            if isinstance(dt, str):
                existing.add(dt[:10])
            elif hasattr(dt, "strftime"):
                existing.add(dt.strftime("%Y-%m-%d"))
            else:
                existing.add(str(dt)[:10])

        missing = sorted(expected_set - existing)
        first_missing = missing[0] if missing else None
        last_missing = missing[-1] if missing else None
        return {
            "asset_code": asset_code,
            "start_date": s_str,
            "end_date": e_str,
            "calendar_mode": mode,
            "expected_trade_days": len(expected_set),
            "existing_days": len(existing),
            "missing_dates": missing,
            "first_missing": first_missing,
            "last_missing": last_missing,
        }

    async def bulk_insert_prices(self, prices: List[AssetPrice]) -> int:
        """批量插入价格数据"""
        if not prices:
            return 0
        
        price_dicts = [p.dict(by_alias=True, exclude={'id'}) for p in prices]
        result = await self.price_collection.insert_many(price_dicts)
        return len(result.inserted_ids)

    async def import_price_data(
        self,
        asset_code: str,
        price_data_list: List[dict],
        replace_existing: bool = False,
        only_missing_dates: bool = False,
        progress_id: Optional[str] = None,
        progress_asset_name: Optional[str] = None,
        progress_import_metric: Optional[str] = None,
    ) -> dict:
        """
        导入价格数据（批量 bulk_write / insert_many）。
        replace_existing=False 时按日合并：仅 $set 文件中出现的字段。
        only_missing_dates=True 时（须与 replace_existing=False 联用）：库中已有该交易日的行一律跳过，仅插入文件中尚未存在的日期。
        新交易日：须在行内提供大于 0 的收盘价（不接受仅用开/高/低推断），以便先建收盘价再补其他字段。
        已存在交易日：若本行未带有效收盘价，则库中该日须已有大于 0 的收盘价，否则拒绝（规模/成交额/OHLC 等须在收盘价之后导入）。
        replace_existing=True 时全量替换：每行均须提供大于 0 的收盘价（此时忽略 only_missing_dates）。
        若系统存在交易日历（Mongo ``trade_dates`` 或 ``data/trade_dates.xlsx``），则文件中**非交易日**的行一律跳过（不计错），避免收盘价含假期时把 OHLC/规模/成交额等写入非交易日。
        progress_*：可选，供前端轮询展示导入进度。
        """
        if replace_existing:
            only_missing_dates = False

        total_count = len(price_data_list)
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        skipped_non_trade_days = 0
        error_count = 0
        errors: List[str] = []
        pan = (progress_asset_name or "").strip()

        async def _prog(
            phase: str,
            prepare_done: int = 0,
            write_done: int = 0,
            write_total: int = 0,
            message: str = "",
        ):
            await touch_progress(
                progress_id,
                asset_code=asset_code,
                asset_name=pan,
                import_metric=progress_import_metric,
                phase=phase,
                prepare_done=prepare_done,
                file_line_total=total_count,
                write_done=write_done,
                write_total=write_total,
                message=message,
            )

        # 须在 load_trade_calendar_date_set 等耗时步骤之前写入进度，否则前端轮询长时间 data=null
        if progress_id and total_count:
            await _prog("prepare", prepare_done=0, message="开始处理（加载交易日历…）")

        trade_calendar: Optional[Set[str]] = await self.load_trade_calendar_date_set()
        if trade_calendar:
            print(
                f"[行情导入-service] 已加载交易日历 {len(trade_calendar)} 天，将跳过不在历内的日期"
            )
        else:
            print(
                "[行情导入-service] 未加载到交易日历（Mongo trade_dates 与 data/trade_dates.xlsx 均为空），"
                "不按日历过滤日期"
            )

        print(
            f"[行情导入-service] asset_code={asset_code} 待导入 {total_count} 条 "
            f"replace_existing={replace_existing} only_missing_dates={only_missing_dates}"
        )
        if progress_id and total_count:
            await _prog("prepare", prepare_done=0, message="解析与校验数据…")

        def _prepare_row(idx: int, price_data: dict, errs: List[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
            nonlocal error_count
            try:
                date_formatted = _normalize_import_date(price_data.get("date"))
                sparse = _sparse_price_fields(price_data)
                if not sparse:
                    raise ValueError("未提供任何有效行情数值列")
                return date_formatted, sparse
            except Exception as e:
                error_count += 1
                err_msg = f"第{idx + 1}行错误: {str(e)}"
                errs.append(err_msg)
                if error_count <= 3:
                    print(f"[行情导入-service] {err_msg}")
                return None

        if replace_existing:
            deleted = await self.price_collection.delete_many({"asset_code": asset_code})
            print(f"[行情导入-service] 已删除旧数据: {deleted.deleted_count} 条")

            documents: List[dict] = []
            for idx, pd_item in enumerate(price_data_list):
                prep = _prepare_row(idx, pd_item, errors)
                if not prep:
                    continue
                date_formatted, sparse = prep
                if trade_calendar is not None and date_formatted not in trade_calendar:
                    skipped_non_trade_days += 1
                    continue
                if not _explicit_close_positive(sparse):
                    error_count += 1
                    err_msg = (
                        f"第{idx + 1}行错误: 全量覆盖每行均须提供大于 0 的收盘价"
                    )
                    errors.append(err_msg)
                    if error_count <= 3:
                        print(f"[行情导入-service] {err_msg}")
                    continue
                ec = float(sparse["close"])
                documents.append(_full_price_document(asset_code, date_formatted, sparse, ec))
                if progress_id and total_count and ((idx + 1) % 200 == 0 or (idx + 1) == total_count):
                    await _prog(
                        "prepare",
                        prepare_done=idx + 1,
                        message=f"准备全量数据 {idx + 1}/{total_count}",
                    )
            n_doc = len(documents)
            # 即使 n_doc=0 也要刷新进度，避免前端卡在 "写入数据库 0/xxx"
            if progress_id:
                if n_doc > 0:
                    await _prog(
                        "write",
                        prepare_done=total_count,
                        write_done=0,
                        write_total=n_doc,
                        message=f"写入数据库 0/{n_doc}（文件共 {total_count} 行）",
                    )
                else:
                    # n_doc=0 说明没有可写入的数据，告知前端跳过原因
                    reason = f"无待写入数据（已跳过 {skipped_non_trade_days} 条非交易日，"
                    reason += f"{error_count} 条无效数据）"
                    await _prog(
                        "done",
                        prepare_done=total_count,
                        write_done=0,
                        write_total=1,
                        message=reason,
                    )
            batch_size = PRICE_IMPORT_BATCH_SIZE
            for i in range(0, len(documents), batch_size):
                await asyncio.sleep(0)
                batch = documents[i : i + batch_size]
                try:
                    result = await self.price_collection.insert_many(batch, ordered=False)
                    inserted_count += len(result.inserted_ids)
                    done = min(i + batch_size, len(documents))
                    print(f"[行情导入-service] 进度: {done}/{len(documents)}")
                    if progress_id:
                        await _prog(
                            "write",
                            prepare_done=total_count,
                            write_done=done,
                            write_total=n_doc,
                            message=f"写入数据库 {done}/{n_doc}（文件共 {total_count} 行）",
                        )
                        await asyncio.sleep(0)
                except Exception as e:
                    err_msg = f"第{i + 1}-{min(i + batch_size, len(documents))}批写入失败: {str(e)}"
                    errors.append(err_msg)
                    error_count += len(batch)
                    print(f"[行情导入-service] {err_msg}")
            skipped_count = max(0, total_count - inserted_count - error_count)
        else:
            prepared: List[Tuple[int, str, Dict[str, Any]]] = []
            for idx, pd_item in enumerate(price_data_list):
                prep = _prepare_row(idx, pd_item, errors)
                if prep:
                    date_formatted, sparse = prep
                    if trade_calendar is not None and date_formatted not in trade_calendar:
                        skipped_non_trade_days += 1
                        continue
                    prepared.append((idx, date_formatted, sparse))
                if progress_id and total_count and ((idx + 1) % 200 == 0 or (idx + 1) == total_count):
                    await _prog(
                        "prepare",
                        prepare_done=idx + 1,
                        message=f"解析与校验 {idx + 1}/{total_count}",
                    )

            dates_unique = sorted({p[1] for p in prepared})
            existing_dates, dates_with_positive_close = await self.load_existing_dates_and_positive_close_bulk(
                asset_code, dates_unique
            )

            operations: List[UpdateOne] = []
            skipped_existing_rows = 0
            opi = 0
            for idx, date_formatted, sparse in prepared:
                if date_formatted in existing_dates:
                    if only_missing_dates:
                        skipped_existing_rows += 1
                        continue
                    if not sparse:
                        continue
                    if not _explicit_close_positive(sparse):
                        if date_formatted not in dates_with_positive_close:
                            error_count += 1
                            err_msg = (
                                f"第{idx + 1}行错误: 日期 {date_formatted} 库中尚无有效收盘价，"
                                "须先导入该日收盘价后再导入规模/成交额/成交量/OHLC 等；若本行含收盘价请填大于 0"
                            )
                            errors.append(err_msg)
                            if error_count <= 3:
                                print(f"[行情导入-service] {err_msg}")
                            continue
                    operations.append(
                        UpdateOne(
                            {"asset_code": asset_code, "date": date_formatted},
                            {"$set": sparse},
                            upsert=False,
                        )
                    )
                else:
                    if not _explicit_close_positive(sparse):
                        error_count += 1
                        err_msg = (
                            f"第{idx + 1}行错误: 库中无日期 {date_formatted} 的行情时，"
                            "须在本行提供大于 0 的收盘价（须先导入收盘价后再补其他字段）"
                        )
                        errors.append(err_msg)
                        if error_count <= 3:
                            print(f"[行情导入-service] {err_msg}")
                        continue
                    ec = float(sparse["close"])
                    full_doc = _full_price_document(asset_code, date_formatted, sparse, ec)
                    operations.append(
                        UpdateOne(
                            {"asset_code": asset_code, "date": date_formatted},
                            {"$set": full_doc},
                            upsert=True,
                        )
                    )
                opi += 1
                if progress_id and len(prepared) and (opi % 300 == 0 or opi == len(prepared)):
                    await _prog(
                        "prepare",
                        prepare_done=opi,
                        message=f"构建待写入操作 {opi}/{len(prepared)}（文件 {total_count} 行）",
                    )

            n_op = len(operations)
            # 即使 n_op=0 也要刷新进度，避免前端卡在 "写入数据库 0/xxx"
            if progress_id:
                if n_op > 0:
                    await _prog(
                        "write",
                        prepare_done=len(prepared),
                        write_done=0,
                        write_total=n_op,
                        message=f"写入数据库 0/{n_op}（文件共 {total_count} 行）",
                    )
                else:
                    # n_op=0 说明没有可写入的数据，告知前端跳过原因
                    reason = f"无待写入操作（已跳过 {skipped_existing_rows} 条已有日期，"
                    reason += f"{skipped_non_trade_days} 条非交易日）"
                    await _prog(
                        "done",
                        prepare_done=len(prepared),
                        write_done=0,
                        write_total=1,
                        message=reason,
                    )
            batch_size = PRICE_IMPORT_BATCH_SIZE
            for i in range(0, len(operations), batch_size):
                await asyncio.sleep(0)
                batch = operations[i : i + batch_size]
                try:
                    result = await self.price_collection.bulk_write(batch, ordered=False)
                    inserted_count += result.upserted_count
                    updated_count += result.modified_count
                    done = min(i + batch_size, len(operations))
                    if progress_id:
                        await _prog(
                            "write",
                            prepare_done=len(prepared),
                            write_done=done,
                            write_total=n_op,
                            message=f"写入数据库 {done}/{n_op}（文件共 {total_count} 行）",
                        )
                        await asyncio.sleep(0)
                except Exception as e:
                    batch_start, batch_end = i + 1, min(i + batch_size, len(operations))
                    err_msg = f"第{batch_start}-{batch_end}批写入失败: {str(e)}"
                    errors.append(err_msg)
                    error_count += len(batch)
                    print(f"[行情导入-service] {err_msg}")
            bulk_tail_skipped = max(0, len(operations) - inserted_count - updated_count)
            skipped_count = skipped_existing_rows + bulk_tail_skipped + skipped_non_trade_days

        print(f"[行情导入-service] 结束 inserted={inserted_count} updated={updated_count} skipped={skipped_count} error={error_count} skipped_non_trade={skipped_non_trade_days}")

        out = {
            "total_count": total_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "skipped_non_trade_days": skipped_non_trade_days,
            "error_count": error_count,
            "errors": errors,
        }
        if progress_id:
            await _prog(
                "done",
                prepare_done=total_count,
                write_done=out.get("inserted_count", 0) + out.get("updated_count", 0),
                write_total=max(1, total_count),
                message="导入完成",
            )
        return out

    async def get_price_date_bounds_and_count(
        self, asset_code: str
    ) -> Tuple[Optional[str], Optional[str], int]:
        """库中该资产行情最小/最大日期与总条数；无数据时 (None, None, 0)。"""
        if not asset_code:
            return None, None, 0
        pipeline = [
            {"$match": {"asset_code": asset_code}},
            {
                "$group": {
                    "_id": None,
                    "date_min": {"$min": "$date"},
                    "date_max": {"$max": "$date"},
                    "cnt": {"$sum": 1},
                }
            },
        ]
        cursor = self.price_collection.aggregate(pipeline)
        async for doc in cursor:
            return (
                doc.get("date_min"),
                doc.get("date_max"),
                int(doc.get("cnt") or 0),
            )
        return None, None, 0

    async def find_existing_price_dates_in_set(
        self, asset_code: str, dates: List[str]
    ) -> Set[str]:
        """在给定日期列表中，返回库中已存在的日期（用于预览重叠）。"""
        if not asset_code or not dates:
            return set()
        out: Set[str] = set()
        chunk = 800
        for i in range(0, len(dates), chunk):
            part = dates[i : i + chunk]
            cursor = self.price_collection.find(
                {"asset_code": asset_code, "date": {"$in": part}},
                {"date": 1, "_id": 0},
            )
            async for doc in cursor:
                d = doc.get("date")
                if d:
                    out.add(d)
        return out

    async def find_dates_with_positive_close(
        self, asset_code: str, dates: List[str]
    ) -> Set[str]:
        """在给定日期中，返回库中已存在且 close>0 的日期（用于校验「先收盘价再补其他字段」）。"""
        if not asset_code or not dates:
            return set()
        out: Set[str] = set()
        chunk = 800
        for i in range(0, len(dates), chunk):
            part = dates[i : i + chunk]
            cursor = self.price_collection.find(
                {
                    "asset_code": asset_code,
                    "date": {"$in": part},
                    "close": {"$gt": 0},
                },
                {"date": 1, "_id": 0},
            )
            async for doc in cursor:
                d = doc.get("date")
                if d:
                    out.add(str(d)[:10])
        return out

    async def load_existing_dates_and_positive_close_bulk(
        self, asset_code: str, dates: List[str]
    ) -> Tuple[Set[str], Set[str]]:
        """
        单次按日期分批查询库里已有行情（含 close），导入与预览共用。
        避免先 find_existing_dates 再 find_dates_with_positive_close 的两倍 round-trip。
        """
        if not asset_code or not dates:
            return set(), set()
        existing: Set[str] = set()
        positive: Set[str] = set()
        chunk = 1500
        for i in range(0, len(dates), chunk):
            part = dates[i : i + chunk]
            cursor = self.price_collection.find(
                {"asset_code": asset_code, "date": {"$in": part}},
                {"date": 1, "close": 1, "_id": 0},
            )
            async for doc in cursor:
                d = doc.get("date")
                if not d:
                    continue
                ds = str(d)[:10]
                existing.add(ds)
                cv = doc.get("close")
                try:
                    if cv is not None and float(cv) > 0:
                        positive.add(ds)
                except (TypeError, ValueError):
                    pass
        return existing, positive

    async def compute_price_import_preview_stats(
        self, target_code: str, prices: List[dict]
    ) -> dict:
        """
        预览导入影响：库内已有区间 + 按日合并 vs 全量覆盖 两种模式下的条数/日期区间。
        replace_existing=false：同日 upsert，重叠日为更新、新日为插入。
        replace_existing=true：删除该资产全部行情后插入文件中的行。
        与 import_price_data 一致：若已加载交易日历，文件中不在历内的日期不计入预览（避免「显示将新增」实际写入被跳过）。
        """
        empty = {
            "target_code": target_code or "",
            "existing_date_min": None,
            "existing_date_max": None,
            "existing_price_count": 0,
            "file_unique_date_count": 0,
            "file_row_count": len(prices) if prices else 0,
            "skipped_non_trade_rows": 0,
            "merge_import": {
                "will_insert_count": 0,
                "will_update_count": 0,
                "new_dates_min": None,
                "new_dates_max": None,
                "overlap_dates_min": None,
                "overlap_dates_max": None,
            },
            "full_replace": {
                "will_delete_count": 0,
                "will_insert_count": 0,
                "result_date_min": None,
                "result_date_max": None,
            },
        }
        if not target_code or not prices:
            return empty

        trade_calendar: Optional[Set[str]] = await self.load_trade_calendar_date_set()
        skipped_non_trade_rows = 0
        norm_file_dates: List[str] = []
        for p in prices:
            pd = p if isinstance(p, dict) else (
                p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            )
            try:
                ds = _normalize_import_date(pd.get("date"))
            except Exception:
                continue
            if trade_calendar is not None and ds not in trade_calendar:
                skipped_non_trade_rows += 1
                continue
            norm_file_dates.append(ds)
        empty["skipped_non_trade_rows"] = skipped_non_trade_rows
        file_dates_unique = sorted(set(norm_file_dates))
        empty["file_unique_date_count"] = len(file_dates_unique)
        d_file_min = file_dates_unique[0] if file_dates_unique else None
        d_file_max = file_dates_unique[-1] if file_dates_unique else None

        e_min, e_max, e_cnt = await self.get_price_date_bounds_and_count(target_code)
        empty["existing_date_min"] = e_min
        empty["existing_date_max"] = e_max
        empty["existing_price_count"] = e_cnt

        existing_on_dates, dates_with_close = await self.load_existing_dates_and_positive_close_bulk(
            target_code, file_dates_unique
        )
        overlap = sorted(existing_on_dates)
        new_only = [d for d in file_dates_unique if d not in existing_on_dates]
        new_only_set = set(new_only)

        date_to_sparses: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in prices:
            pd = p if isinstance(p, dict) else (
                p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            )
            try:
                ds = _normalize_import_date(pd.get("date"))
            except Exception:
                continue
            if trade_calendar is not None and ds not in trade_calendar:
                continue
            date_to_sparses[ds].append(_sparse_price_fields(pd))

        def _file_has_explicit_close_for_date(d: str) -> bool:
            return any(_explicit_close_positive(sp) for sp in date_to_sparses.get(d, []))

        new_dates_insertable: Set[str] = set()
        for d in new_only:
            if _file_has_explicit_close_for_date(d):
                new_dates_insertable.add(d)

        will_update = 0
        for d in overlap:
            if d in dates_with_close or _file_has_explicit_close_for_date(d):
                will_update += 1

        merge = empty["merge_import"]
        merge["will_update_count"] = will_update
        merge["will_insert_count"] = len(new_dates_insertable)
        ins_sorted = sorted(new_dates_insertable)
        if ins_sorted:
            merge["new_dates_min"] = ins_sorted[0]
            merge["new_dates_max"] = ins_sorted[-1]
        if overlap:
            merge["overlap_dates_min"] = overlap[0]
            merge["overlap_dates_max"] = overlap[-1]

        full = empty["full_replace"]
        full["will_delete_count"] = e_cnt
        ins_full = 0
        for p in prices:
            pd = p if isinstance(p, dict) else (
                p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            )
            try:
                ds = _normalize_import_date(pd.get("date"))
            except Exception:
                continue
            if trade_calendar is not None and ds not in trade_calendar:
                continue
            if _explicit_close_positive(_sparse_price_fields(pd)):
                ins_full += 1
        full["will_insert_count"] = ins_full
        full["result_date_min"] = d_file_min
        full["result_date_max"] = d_file_max

        return empty

