"""
资产查询工具 — 原子能力层

提供资产列表查询和资产价格数据查询两个原子 Tool。
新增资产相关工具时，在本文件中追加新的 BaseTool 子类即可，
框架会自动发现并注册。

重写标准：
- execute() 方法不超过 50 行
- 只调用 Service 方法，不做业务编排
- 不生成图表配置
"""
from datetime import datetime
from typing import Optional

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.validators.data_validator import DataValidator
from app.models.asset import AssetType
from app.services.asset_service import AssetService

# 模块级单例，避免每次调用创建新实例
_asset_service = AssetService()
_data_validator = DataValidator()


def _parse_asset_type(raw: Optional[str]) -> Optional[AssetType]:
    """将 LLM 传入的类别字符串转为 AssetType（兼容中英文与常见英文名）。

    注意："etf"/"lof" 不在本映射中处理，由 QueryAssetsTool.execute() 特殊分支处理
    （ETF 实际存储为 asset_type='指数类' 即 AssetType.INDEX_CATEGORY）。
    """
    if raw is None or raw == "":
        return None
    s = str(raw).strip()
    try:
        return AssetType(s)
    except ValueError:
        pass
    m = {
        "equity": AssetType.STOCK,
        "stock": AssetType.STOCK,
        "bond": AssetType.BOND,
        "commodity": AssetType.COMMODITY,
        "fund": AssetType.FUND,
        "fx": AssetType.CURRENCY,
        "currency": AssetType.CURRENCY,
        "index": AssetType.INDEX,
        "crypto": AssetType.CRYPTO,
        # 前端分类（兼容）
        "指数类": AssetType.INDEX_CATEGORY,
        "现货类": AssetType.SPOT_CATEGORY,
        "期货类": AssetType.FUTURES_CATEGORY,
    }
    return m.get(s.lower())


class QueryAssetsTool(BaseTool):
    """查询系统中的资产列表，支持按类别和状态筛选"""

    name = "query_assets"
    description = (
        "查询系统中的资产列表。支持按关键字 keyword 搜索名称或代码（如「沪深300」「黄金」「标普」）；"
        "也可按 asset_type 筛选。"
        "返回资产代码、名称、类别等基本信息；优先用返回的 code 做后续回测。"
    )
    category = "asset"
    tags = ["资产", "查询", "列表"]

    parameters = {
        "type": "object",
        "properties": {
            "asset_type": {
                "type": "string",
                "description": (
                    "资产类别筛选：equity/bond/commodity/fund/fx/etf/index。"
                    "查询ETF请传 'etf'（系统自动映射到指数类+ETF关键字过滤）。不传则返回全部类型。"
                ),
            },
            "is_active": {
                "type": "boolean",
                "description": "是否只查询启用的资产，默认 true",
            },
            "limit": {
                "type": "integer",
                "description": "返回记录数上限，默认 100",
            },
            "keyword": {
                "type": "string",
                "description": (
                    "按名称或代码关键字模糊搜索，如「沪深300」「标普500」「黄金」「SH000300」。"
                    "与 asset_type 可同时使用。"
                ),
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> dict:
        raw_at = kwargs.get("asset_type")
        is_active: bool = kwargs.get("is_active", True)
        limit: int = min(kwargs.get("limit", 100), 500)
        kw = kwargs.get("keyword")
        if kw is None and kwargs.get("search"):
            kw = kwargs.get("search")

        # ── ETF / LOF 特殊处理 ──
        # ETF 实际存储为 asset_type='指数类'(INDEX_CATEGORY)，名称含 "ETF"
        _raw_lower = str(raw_at).strip().lower() if raw_at else ""
        _kw_lower = kw.lower() if isinstance(kw, str) else ""
        _is_etf_query = (
            _raw_lower in ("etf", "lof")
            or ("etf" in _kw_lower or "lof" in _kw_lower)
        )

        if _is_etf_query:
            at_enum = AssetType.INDEX_CATEGORY
            # 若用户未提供关键字或关键字中不含 etf/lof，补充 ETF 关键字
            if not isinstance(kw, str) or not kw.strip():
                kw = "ETF" if _raw_lower != "lof" else "LOF"
            # 若用户同时提供了 asset_type=etf + keyword=xxx，保留用户关键字
            # asset_type=INDEX_CATEGORY 已缩小到指数类范围
            limit = min(kwargs.get("limit", 200), 500)  # ETF 数量多，默认放大
        else:
            at_enum = _parse_asset_type(raw_at) if raw_at else None

        try:
            assets = await _asset_service.list_assets(
                asset_type=at_enum,
                is_active=is_active,
                limit=limit,
                keyword=kw.strip() if isinstance(kw, str) and kw.strip() else None,
            )
            items = [
                {
                    "code": a.code,
                    "name": a.name,
                    "asset_type": str(a.asset_type) if a.asset_type else "",
                }
                for a in assets
            ]
            result = ToolResult.success(
                data={"assets": items},
                summary=f"共查到 {len(items)} 个资产",
                record_count=len(items),
            )
            result["_lineage_meta"] = {
                "tables_used": ["assets"],
                "domains_involved": ["asset"],
                "fields_accessed": {"assets": ["code", "name", "asset_type", "is_active"]},
                "join_path": "",
                "records_returned": len(items),
                "total_in_collection": 0,
                "query_operation": "query_assets",
            }
            return result
        except Exception as e:
            logger.error("[QueryAssetsTool] 查询失败: {}", e)
            return ToolResult.error(f"资产查询失败: {e}")


class QueryAssetPricesTool(BaseTool):
    """查询指定资产的历史价格数据"""

    name = "query_asset_prices"
    description = (
        "查询指定资产代码的历史价格数据。"
        "支持按日期范围筛选，返回日期和收盘价序列。"
    )
    category = "asset"
    tags = ["资产", "价格", "数据", "时序"]

    parameters = {
        "type": "object",
        "properties": {
            "asset_code": {
                "type": "string",
                "description": "资产代码，如 SH000300、SPX",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期，格式 YYYY-MM-DD",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期，格式 YYYY-MM-DD",
            },
        },
        "required": ["asset_code"],
    }

    async def execute(self, **kwargs) -> dict:
        asset_code: str = kwargs.get("asset_code", "")
        if not asset_code:
            return ToolResult.error("必须提供 asset_code 参数")

        start_date_str: Optional[str] = kwargs.get("start_date")
        end_date_str: Optional[str] = kwargs.get("end_date")

        # 解析日期
        start_date: Optional[datetime] = None
        end_date: Optional[datetime] = None
        try:
            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            if end_date_str:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except ValueError as e:
            return ToolResult.error(f"日期格式错误（应为 YYYY-MM-DD）: {e}")

        try:
            prices = await _asset_service.get_asset_prices(
                asset_code=asset_code,
                start_date=start_date,
                end_date=end_date,
            )

            # ── 构建溯源标记：始终注入 traceable_assets，使前端芯片区可显示 ──
            asset_name = asset_code
            asset_valid = False
            try:
                asset_obj = await _asset_service.get_asset_by_code(asset_code)
                if asset_obj:
                    asset_valid = True
                    if getattr(asset_obj, "name", None):
                        asset_name = asset_obj.name
            except Exception as _ne:  # 反查名称失败不阻塞
                logger.warning("[QueryAssetPricesTool] 反查资产名称失败(non-blocking): {}", _ne)
            traceable_assets = [{
                "code": asset_code,
                "name": asset_name,
                "has_kline": bool(prices) and asset_valid,
                "valid": asset_valid,
                "is_representative": True,
            }]

            if not prices:
                _result = ToolResult.success(
                    data={
                        "records": [],
                        "asset_code": asset_code,
                        "traceable_assets": traceable_assets,
                    },
                    summary=f"资产 {asset_code} 在指定范围内无价格数据",
                    record_count=0,
                )
                _result["_lineage_meta"] = {
                    "tables_used": ["asset_prices"],
                    "domains_involved": ["asset"],
                    "fields_accessed": {"asset_prices": ["asset_code", "date", "close", "open", "high", "low", "volume"]},
                    "join_path": "",
                    "records_returned": 0,
                    "total_in_collection": 0,
                    "query_operation": "query_asset_prices",
                    "query_filter": {"asset_code": asset_code, "start_date": start_date_str, "end_date": end_date_str},
                }
                return _result

            # ── 构建用户友好的 records（中文字段名） ──
            records = []
            for p in prices:
                record = {"日期": str(p.date), "收盘价": p.close}
                if p.open is not None:
                    record["开盘价"] = p.open
                if p.high is not None:
                    record["最高价"] = p.high
                if p.low is not None:
                    record["最低价"] = p.low
                if p.volume is not None:
                    record["成交量"] = p.volume
                records.append(record)

            # ── 数据校验层：验证资产存在性与数据覆盖度 ──
            validation_result = None
            try:
                asset_check = await _data_validator.validate_asset_exists(asset_code)
                price_check = await _data_validator.validate_price_data(
                    asset_code,
                    start_date_str or "",
                    end_date_str or "",
                )
                validation_result = {
                    "data_source": {
                        "collection": "asset_prices",
                        "query": {
                            "asset_code": asset_code,
                            "start_date": start_date_str,
                            "end_date": end_date_str,
                        },
                        "count": len(records),
                    },
                    "asset_verified": asset_check,
                    "price_coverage": price_check,
                    "validation_status": "passed" if asset_check.get("exists") and price_check.get("has_data") else "warning",
                    "computed_by": "direct_query",
                }
            except Exception as e:
                logger.warning("[QueryAssetPricesTool] validation failed (non-blocking): {}", e)

            result = ToolResult.success(
                data={
                    "records": records,
                    "asset_code": asset_code,
                    "traceable_assets": traceable_assets,
                },
                summary=f"资产 {asset_code} 共 {len(records)} 条价格记录",
                record_count=len(records),
                validation=validation_result,
            )
            result["_lineage_meta"] = {
                "tables_used": ["asset_prices", "assets"],
                "domains_involved": ["asset"],
                "fields_accessed": {
                    "asset_prices": ["asset_code", "date", "close", "open", "high", "low", "volume"],
                    "assets": ["code", "name"],
                },
                "join_path": "asset_prices.asset_code = assets.code",
                "records_returned": len(records),
                "total_in_collection": 0,
                "query_operation": "query_asset_prices",
                "query_filter": {"asset_code": asset_code, "start_date": start_date_str, "end_date": end_date_str},
            }
            return result
        except Exception as e:
            logger.error("[QueryAssetPricesTool] 查询失败: {}", e)
            return ToolResult.error(f"价格数据查询失败: {e}")
