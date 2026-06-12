"""
数据导入工具

让 AI Agent 通过对话完成文件校验、解析预览和确认导入。
支持行情数据、汇率数据、资产信息等多种类型的 Excel/CSV 文件导入。
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from app.agent.services.attachment_service import AttachmentService
from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.data_import_templates import get_all_templates_summary
from app.monitor.config import ASSET_NAME_TO_CODE, ASSET_CODE_TO_NAME


# ── 列名映射 ──────────────────────────────────────────────────────────────────

PRICE_COLUMN_MAPPING = {
    "日期": "date", "日期*": "date", "Date": "date", "DATE": "date", "date": "date",
    "收盘价": "close", "收盘价*": "close", "收盘": "close", "Close": "close", "CLOSE": "close", "close": "close",
    "开盘价": "open", "开盘价*": "open", "Open": "open", "OPEN": "open", "open": "open",
    "最高价": "high", "最高价*": "high", "High": "high", "HIGH": "high", "high": "high",
    "最低价": "low", "最低价*": "low", "Low": "low", "LOW": "low", "low": "low",
    "成交量": "volume", "Volume": "volume", "VOLUME": "volume", "volume": "volume",
    "成交额": "amount", "Amount": "amount", "AMOUNT": "amount", "amount": "amount",
    "规模": "scale", "规模*": "scale", "基金规模": "scale", "Scale": "scale", "SCALE": "scale", "scale": "scale",
}

ASSET_INFO_COLUMN_MAPPING = {
    "代码": "code", "资产代码": "code", "资产代码*": "code", "Code": "code", "CODE": "code", "code": "code",
    "名称": "name", "资产名称": "name", "资产名称*": "name", "Name": "name", "NAME": "name", "name": "name",
    "类型": "asset_type", "资产类型": "asset_type", "资产类型*": "asset_type", "type": "asset_type",
    "交易所": "exchange", "Exchange": "exchange", "exchange": "exchange",
    "货币": "currency", "Currency": "currency", "currency": "currency",
    "描述": "description", "资产描述": "description", "Description": "description", "description": "description",
}

TRADE_DATES_COLUMN_MAPPING = {
    "交易日": "date", "交易日期": "date", "交易日期*": "date",
    "trade_dates": "date", "trade_date": "date", "TradeDate": "date",
    "TRADE_DATE": "date", "TRADE_DATES": "date",
    "日期": "date", "日期*": "date", "Date": "date", "DATE": "date", "date": "date",
}


def _read_file_df(file_path: Path, nrows: Optional[int] = None) -> pd.DataFrame:
    """读取 Excel 或 CSV 文件为 DataFrame，自动处理编码问题。"""
    ext = file_path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        kwargs = {"nrows": nrows} if nrows else {}
        return pd.read_excel(file_path, **kwargs)
    # CSV：尝试多种编码
    for encoding in ("utf-8", "gbk", "gb2312", "utf-8-sig"):
        try:
            kwargs = {"nrows": nrows, "encoding": encoding}
            return pd.read_csv(file_path, **kwargs)
        except UnicodeDecodeError:
            continue
    # 最后以替换错误方式读取
    kwargs = {"nrows": nrows, "encoding": "utf-8", "errors": "replace"}
    return pd.read_csv(file_path, **kwargs)


def _read_fx_df(file_path: Path) -> pd.DataFrame:
    """读取汇率格式文件（第一列为日期 index）。"""
    ext = file_path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(file_path, index_col=0, parse_dates=True)
    for encoding in ("utf-8", "gbk", "gb2312", "utf-8-sig"):
        try:
            return pd.read_csv(file_path, index_col=0, parse_dates=True, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(file_path, index_col=0, parse_dates=True, encoding="utf-8", errors="replace")


def _sanitize_value(val: Any) -> Any:
    """序列化单个值：NaN -> None, datetime -> isoformat, numpy -> python。"""
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return None
    if isinstance(val, (pd.Timestamp, datetime)):
        return val.isoformat()
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        v = float(val)
        return None if (np.isnan(v) or np.isinf(v)) else v
    if isinstance(val, np.bool_):
        return bool(val)
    return val


def _df_to_safe_records(df: pd.DataFrame, max_rows: Optional[int] = None) -> List[Dict[str, Any]]:
    """将 DataFrame 转为安全可序列化的 dict 列表。"""
    subset = df.head(max_rows) if max_rows else df
    records = []
    for _, row in subset.iterrows():
        records.append({col: _sanitize_value(row[col]) for col in df.columns})
    return records


def _map_column_to_asset_code(col_name: str) -> str:
    """将列名映射为资产代码，优先使用 ASSET_NAME_TO_CODE，否则原样返回。"""
    col_stripped = str(col_name).strip()
    if col_stripped in ASSET_NAME_TO_CODE:
        return ASSET_NAME_TO_CODE[col_stripped]
    # 如果本身就是已知代码
    if col_stripped in ASSET_CODE_TO_NAME:
        return col_stripped
    return col_stripped


def _compute_price_column_details(df: pd.DataFrame, date_index: pd.DatetimeIndex) -> List[Dict[str, Any]]:
    """
    对价格宽表的每个资产列计算详细统计。
    df: 数据列（不含日期列），index 为 DatetimeIndex。
    """
    column_details = []
    total_rows = len(df)
    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        non_null_count = len(non_null)
        null_count = total_rows - non_null_count
        if non_null_count > 0:
            non_null_idx = non_null.index
            first_date = non_null_idx.min()
            last_date = non_null_idx.max()
            first_val = float(non_null.iloc[0])
            last_val = float(non_null.iloc[-1])
            coverage_days = (last_date - first_date).days if non_null_count > 1 else 0
            column_details.append({
                "column_name": str(col),
                "asset_code": _map_column_to_asset_code(col),
                "total_rows": total_rows,
                "non_null_count": non_null_count,
                "null_count": null_count,
                "first_date": first_date.strftime("%Y-%m-%d") if hasattr(first_date, 'strftime') else str(first_date)[:10],
                "last_date": last_date.strftime("%Y-%m-%d") if hasattr(last_date, 'strftime') else str(last_date)[:10],
                "first_value": round(first_val, 6),
                "last_value": round(last_val, 6),
                "date_coverage_days": coverage_days,
            })
        else:
            column_details.append({
                "column_name": str(col),
                "asset_code": _map_column_to_asset_code(col),
                "total_rows": total_rows,
                "non_null_count": 0,
                "null_count": total_rows,
                "first_date": None,
                "last_date": None,
                "first_value": None,
                "last_value": None,
                "date_coverage_days": 0,
            })
    return column_details


def _compute_fx_column_details(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    对汇率宽表的每个货币列计算详细统计。
    df: index 为 DatetimeIndex，列为 EUR/USD/HKD/CNH 等。
    """
    column_details = []
    total_rows = len(df)
    for col in df.columns:
        series = pd.to_numeric(df[col], errors="coerce")
        non_null = series.dropna()
        non_null_count = len(non_null)
        null_count = total_rows - non_null_count
        if non_null_count > 0:
            non_null_idx = non_null.index
            first_date = non_null_idx.min()
            last_date = non_null_idx.max()
            column_details.append({
                "column_name": str(col),
                "total_rows": total_rows,
                "non_null_count": non_null_count,
                "null_count": null_count,
                "first_date": first_date.strftime("%Y-%m-%d") if hasattr(first_date, 'strftime') else str(first_date)[:10],
                "last_date": last_date.strftime("%Y-%m-%d") if hasattr(last_date, 'strftime') else str(last_date)[:10],
                "first_value": round(float(non_null.iloc[0]), 6),
                "last_value": round(float(non_null.iloc[-1]), 6),
                "min_value": round(float(non_null.min()), 6),
                "max_value": round(float(non_null.max()), 6),
                "date_coverage_days": (last_date - first_date).days if non_null_count > 1 else 0,
            })
        else:
            column_details.append({
                "column_name": str(col),
                "total_rows": total_rows,
                "non_null_count": 0,
                "null_count": total_rows,
                "first_date": None,
                "last_date": None,
                "first_value": None,
                "last_value": None,
                "min_value": None,
                "max_value": None,
                "date_coverage_days": 0,
            })
    return column_details


class DataImportTool(BaseTool):
    """数据导入工具：校验上传文件格式、预览数据内容并对比现有数据、确认后执行导入入库。"""

    name = "data_import"
    description = (
        "数据导入工具：校验上传文件格式、预览数据并与数据库现有数据对比、确认后执行导入入库。"
        "支持行情数据、汇率数据、资产信息、交易日历等多种类型的Excel/CSV文件导入。"
        "preview操作会返回文件数据与数据库的对比信息（新增/覆盖数量），"
        "你必须在preview后向用户展示对比结果并询问用户是否确认导入，"
        "用户确认后才能执行import操作。"
        "import操作会将文件数据实际写入MongoDB数据库（如fx_rates、asset_prices、trade_dates等集合），"
        "请直接调用，不要回复'不支持'或'无法导入'。"
        "对于宽表行情文件（日期为第一列，其余列为资产价格），无需指定asset_code即可一次性导入所有资产。"
        "默认使用 incremental 增量模式，仅导入数据库中不存在的新数据，速度很快。"
        "只有用户明确要求全量替换时才使用 replace 模式。"
    )
    category = "data"
    tags = ["数据导入", "Excel", "行情", "汇率", "资产", "交易日历"]
    tool_timeout: float = 600.0  # 数据导入操作超时10分钟，确保大文件导入有足够时间

    def __init__(self):
        super().__init__()
        # 强制设置实例属性，确保 getattr(tool, 'tool_timeout') 可靠命中
        self.tool_timeout = 600.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["validate", "preview", "import", "list_templates"],
                "description": "操作类型：validate=校验格式, preview=预览数据, import=将文件数据写入MongoDB数据库, list_templates=列出模板",
            },
            "attachment_id": {
                "type": "string",
                "description": "附件ID（validate/preview/import时必填）",
            },
            "import_type": {
                "type": "string",
                "enum": ["price", "fx", "asset_info", "multi_asset", "trade_dates"],
                "description": "导入类型",
            },
            "asset_code": {
                "type": "string",
                "description": "目标资产代码（行情导入时需要）",
            },
            "mode": {
                "type": "string",
                "enum": ["incremental", "replace", "append"],
                "default": "incremental",
                "description": "导入模式。incremental=仅导入数据库中不存在的新数据（默认，速度快）；replace=删除现有数据后全量替换；append=追加所有数据（可能重复）",
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        action: str = kwargs.get("action", "")
        if not action:
            logger.warning("[DataImportTool] execute 缺少 action 参数, kwargs keys={}", list(kwargs.keys()))
            return ToolResult.error("缺少必要参数: action")

        logger.info("[DataImportTool] execute action={}", action)

        try:
            if action == "list_templates":
                result = await self._handle_list_templates()
            elif action == "validate":
                result = await self._handle_validate(kwargs)
            elif action == "preview":
                result = await self._handle_preview(kwargs)
            elif action == "import":
                result = await self._handle_import(kwargs)
            else:
                logger.warning("[DataImportTool] 不支持的 action={}", action)
                return ToolResult.error(
                    f"不支持的操作: {action}，可选: validate/preview/import/list_templates"
                )
        except Exception as e:
            logger.exception("[DataImportTool] action={} 执行异常: {}", action, e)
            return ToolResult.error(f"操作失败: {e}")

        # 统一附加血缘：导入工具是写入业务表的反向操作
        if not (isinstance(result, dict) and result.get("success")):
            return result
        if "_lineage_meta" in result:
            return result
        # 根据 import_type 推断目标表
        import_type = kwargs.get("import_type", "")
        target_table_map = {
            "price": "asset_prices",
            "fx": "fx_rates",
            "asset_info": "assets",
            "multi_asset": "asset_prices",
            "trade_dates": "trade_dates",
        }
        target_table = target_table_map.get(import_type, "")
        return self.attach_lineage(
            result,
            tables=[target_table] if target_table else [],
            domains=["asset"] if target_table in ("asset_prices", "assets", "fx_rates") else ["meta"],
            fields={target_table: ["<all_imported_fields>"]} if target_table else {},
            records_returned=result.get("metadata", {}).get("record_count", 0),
            query_operation=f"data_import:{action}:{import_type}",
            attachment_id=kwargs.get("attachment_id"),
            write_mode=True,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # list_templates
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_list_templates(self) -> dict:
        templates = get_all_templates_summary()
        return ToolResult.success(
            data={"templates": templates},
            summary=f"共 {len(templates)} 个可用导入模板",
            record_count=len(templates),
            data_shape="table",
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # validate
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_validate(self, kwargs: dict) -> dict:
        attachment_id = kwargs.get("attachment_id")
        import_type = kwargs.get("import_type")
        logger.info("[DataImportTool] _handle_validate attachment_id={}, import_type={}", attachment_id, import_type)
        if not attachment_id:
            return ToolResult.error("validate 操作需要提供 attachment_id")
        if not import_type:
            return ToolResult.error("validate 操作需要提供 import_type（price/fx/asset_info/multi_asset/trade_dates）")

        file_path = AttachmentService.get_file_path(attachment_id)
        if not file_path or not file_path.exists():
            return ToolResult.error(f"附件不存在或已过期: {attachment_id}")

        if import_type == "price":
            result = await self._validate_price(file_path)
        elif import_type == "fx":
            result = await self._validate_fx(file_path)
        elif import_type == "asset_info":
            result = await self._validate_asset_info(file_path)
        elif import_type == "multi_asset":
            result = await self._validate_multi_asset(file_path)
        elif import_type == "trade_dates":
            result = await self._validate_trade_dates(file_path)
        else:
            return ToolResult.error(f"不支持的导入类型: {import_type}")

        status = "校验通过" if result["valid"] else "校验失败"
        summary = f"{status}：{len(result.get('errors', []))} 个错误, {len(result.get('warnings', []))} 个警告, {result.get('row_count', 0)} 行数据"

        return ToolResult.success(
            data=result,
            summary=summary,
            record_count=result.get("row_count", 0),
            data_shape="detail",
        )

    async def _validate_price(self, file_path: Path) -> dict:
        """校验行情数据文件。"""
        df = _read_file_df(file_path)
        df.columns = df.columns.astype(str).str.strip()
        df.rename(columns={k: v for k, v in PRICE_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

        errors: List[str] = []
        warnings: List[str] = []

        if "date" not in df.columns:
            errors.append("缺少必填列：日期/date")
        if "close" not in df.columns:
            errors.append("缺少必填列：收盘价/close")

        # 日期格式检查
        if "date" in df.columns:
            try:
                pd.to_datetime(df["date"].dropna().head(20))
            except Exception:
                errors.append("日期列格式无法解析，请确保为 YYYY-MM-DD 或 YYYYMMDD 等标准格式")

        # 数值列检查
        if "close" in df.columns:
            close_valid = pd.to_numeric(df["close"], errors="coerce").dropna()
            if close_valid.empty:
                errors.append("收盘价列全部为空或无法解析为数值")
            elif (close_valid <= 0).any():
                cnt = int((close_valid <= 0).sum())
                warnings.append(f"收盘价存在 {cnt} 个小于等于0的值")

        # 日期范围
        date_range = None
        if "date" in df.columns and not df["date"].dropna().empty:
            try:
                dates = pd.to_datetime(df["date"].dropna())
                date_range = f"{dates.min().strftime('%Y-%m-%d')} ~ {dates.max().strftime('%Y-%m-%d')}"
            except Exception:
                pass

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "detected_columns": list(df.columns),
            "row_count": len(df),
            "date_range": date_range,
        }

    async def _validate_fx(self, file_path: Path) -> dict:
        """校验汇率数据文件。"""
        errors: List[str] = []
        warnings: List[str] = []

        try:
            df = _read_fx_df(file_path)
        except Exception as e:
            return {"valid": False, "errors": [f"文件解析失败: {e}"], "warnings": [], "detected_columns": [], "row_count": 0, "date_range": None}

        if df.empty:
            errors.append("文件为空或无法解析出有效数据")
            return {"valid": False, "errors": errors, "warnings": [], "detected_columns": [], "row_count": 0, "date_range": None}

        # 标准化列名
        df.columns = df.columns.astype(str).str.strip().str.upper()
        fx_cols = ["EUR", "USD", "HKD", "CNH"]
        valid_cols = [c for c in fx_cols if c in df.columns]

        if not valid_cols:
            errors.append(f"未找到有效货币列（需要 EUR/USD/HKD/CNH 中至少一列），当前列: {list(df.columns)}")

        # 日期索引检查
        try:
            if not isinstance(df.index, pd.DatetimeIndex):
                pd.to_datetime(df.index)
        except Exception:
            errors.append("第一列（日期索引）无法解析为日期格式")

        # 数值范围检查
        for col in valid_cols:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            if not series.empty:
                if (series <= 0).any():
                    warnings.append(f"{col} 列存在小于等于0的值")
                if (series > 100).any():
                    warnings.append(f"{col} 列存在大于100的值，请确认是否为汇率数据")
                if (series < 0.01).any():
                    warnings.append(f"{col} 列存在小于0.01的值，请确认是否为汇率数据")

        date_range = None
        try:
            idx = pd.to_datetime(df.index) if not isinstance(df.index, pd.DatetimeIndex) else df.index
            date_range = f"{idx.min().strftime('%Y-%m-%d')} ~ {idx.max().strftime('%Y-%m-%d')}"
        except Exception:
            pass

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "detected_columns": valid_cols,
            "row_count": len(df),
            "date_range": date_range,
        }

    async def _validate_asset_info(self, file_path: Path) -> dict:
        """校验资产信息文件。"""
        df = _read_file_df(file_path)
        df.columns = df.columns.astype(str).str.strip()
        df.rename(columns={k: v for k, v in ASSET_INFO_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

        errors: List[str] = []
        warnings: List[str] = []

        if "code" not in df.columns:
            errors.append("缺少必填列：代码/code")
        if "name" not in df.columns:
            errors.append("缺少必填列：名称/name")

        if "code" in df.columns:
            codes = df["code"].dropna()
            if codes.empty:
                errors.append("代码列全部为空")
            else:
                dup = codes[codes.duplicated()]
                if not dup.empty:
                    warnings.append(f"代码列存在 {len(dup)} 个重复值: {list(dup.head(5).values)}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "detected_columns": list(df.columns),
            "row_count": len(df),
            "date_range": None,
        }

    async def _validate_trade_dates(self, file_path: Path) -> dict:
        """校验交易日历文件。"""
        df = _read_file_df(file_path)
        df.columns = df.columns.astype(str).str.strip()
        df.rename(columns={k: v for k, v in TRADE_DATES_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

        errors: List[str] = []
        warnings: List[str] = []

        # 如果没有 date 列，尝试检测第一列是否为日期
        if "date" not in df.columns:
            first_col = df.columns[0] if len(df.columns) > 0 else None
            if first_col:
                try:
                    pd.to_datetime(df[first_col].dropna().head(10))
                    warnings.append(f"未找到标准日期列名，将使用第一列 '{first_col}' 作为交易日期")
                    df.rename(columns={first_col: "date"}, inplace=True)
                except Exception:
                    errors.append("缺少必填列：交易日期/trade_dates/date，且第一列无法解析为日期")
            else:
                errors.append("文件为空，无法识别列")

        # 日期格式检查
        if "date" in df.columns:
            try:
                parsed = pd.to_datetime(df["date"].dropna().head(20))
                if parsed.empty:
                    errors.append("交易日期列全部为空")
            except Exception:
                errors.append("交易日期列格式无法解析，请确保为 YYYY-MM-DD 或 YYYYMMDD 等标准格式")

        # 重复值检查
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"].dropna(), errors="coerce").dropna()
            dup_count = dates.duplicated().sum()
            if dup_count > 0:
                warnings.append(f"存在 {dup_count} 个重复日期，导入时将自动去重")

        # 日期范围
        date_range = None
        if "date" in df.columns and not df["date"].dropna().empty:
            try:
                dates = pd.to_datetime(df["date"].dropna())
                date_range = f"{dates.min().strftime('%Y-%m-%d')} ~ {dates.max().strftime('%Y-%m-%d')}"
            except Exception:
                pass

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "detected_columns": list(df.columns),
            "row_count": len(df),
            "date_range": date_range,
        }

    async def _validate_multi_asset(self, file_path: Path) -> dict:
        """校验多资产宽表文件。"""
        errors: List[str] = []
        warnings: List[str] = []

        try:
            df = pd.read_excel(file_path, header=None)
        except Exception as e:
            return {"valid": False, "errors": [f"文件解析失败: {e}"], "warnings": [], "detected_columns": [], "row_count": 0, "date_range": None}

        if df.shape[0] < 5:
            errors.append("文件行数不足，多资产宽表至少需要5行（含表头行）")
        if df.shape[1] < 2:
            errors.append("文件列数不足，至少需要日期列 + 1个资产列")

        # 尝试检测资产代码行（第5行，index=4）
        asset_codes = []
        if df.shape[0] >= 5:
            row4 = df.iloc[4]
            asset_codes = [str(v).strip() for v in row4.values[1:] if pd.notna(v) and str(v).strip()]
            if not asset_codes:
                warnings.append("第5行未检测到有效资产代码")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "detected_columns": asset_codes if asset_codes else list(df.columns),
            "row_count": max(0, df.shape[0] - 5),
            "date_range": None,
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # preview (with database comparison)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _get_existing_fx_dates(self) -> set:
        """查询数据库中已有的汇率日期集合。"""
        from app.config.database import Database
        db = Database.get_database()
        if db is None:
            return set()
        collection = db["fx_rates"]
        distinct_dates = await collection.distinct("date")
        return set(str(d)[:10] for d in distinct_dates)

    async def _get_existing_trade_dates(self) -> set:
        """查询数据库中已有的交易日历日期集合。"""
        from app.config.database import Database
        db = Database.get_database()
        if db is None:
            return set()
        collection = db["trade_dates"]
        distinct_dates = await collection.distinct("date")
        return set(
            d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            for d in distinct_dates
        )

    async def _get_existing_price_dates(self, asset_code: str) -> set:
        """查询数据库中某资产已有的行情日期集合。"""
        from app.config.database import Database
        db = Database.get_database()
        if db is None:
            return set()
        collection = db["asset_prices"]
        cursor = collection.find(
            {"asset_code": asset_code}, {"date": 1, "_id": 0}
        )
        dates = set()
        async for doc in cursor:
            if "date" in doc:
                dates.add(str(doc["date"])[:10])
        return dates

    async def _get_existing_asset_codes(self) -> set:
        """查询数据库中已有的资产代码集合。"""
        from app.config.database import Database
        db = Database.get_database()
        if db is None:
            return set()
        collection = db["assets"]
        distinct_codes = await collection.distinct("code")
        return set(distinct_codes)

    async def _handle_preview(self, kwargs: dict) -> dict:
        attachment_id = kwargs.get("attachment_id")
        logger.info("[DataImportTool] _handle_preview attachment_id={}, import_type={}", attachment_id, kwargs.get("import_type"))
        if not attachment_id:
            return ToolResult.error("preview 操作需要提供 attachment_id")

        file_path = AttachmentService.get_file_path(attachment_id)
        if not file_path or not file_path.exists():
            return ToolResult.error(f"附件不存在或已过期: {attachment_id}")

        import_type = kwargs.get("import_type", "price")
        asset_code = kwargs.get("asset_code", "")

        # 汇率文件特殊处理（第一列为日期 index）
        if import_type == "fx":
            try:
                df = _read_fx_df(file_path)
                df_reset = df.reset_index()
                df_reset.columns = [str(c) for c in df_reset.columns]
                columns = list(df_reset.columns)
                sample_data = _df_to_safe_records(df_reset, max_rows=5)

                # ── 计算每个币种列的详细统计 ──
                column_details = []
                file_summary = {
                    "file_name": file_path.name,
                    "total_rows": len(df),
                    "total_columns": len(df.columns),
                    "date_range": None,
                    "format": "汇率",
                }
                try:
                    idx = pd.to_datetime(df.index) if not isinstance(df.index, pd.DatetimeIndex) else df.index
                    df_fx = df.copy()
                    df_fx.index = idx
                    if not idx.empty:
                        file_summary["date_range"] = (
                            f"{idx.min().strftime('%Y-%m-%d')} ~ {idx.max().strftime('%Y-%m-%d')}"
                        )
                    column_details = _compute_fx_column_details(df_fx)
                except Exception as e:
                    logger.warning("[DataImportTool] fx column_details计算失败: {}", e)

                # ── 对比数据库现有数据 ──
                comparison = await self._compare_fx_with_db(df)

                result_data = {
                    "file_summary": file_summary,
                    "columns": columns,
                    "row_count": len(df),
                    "sample_data": sample_data,
                    "detected_format": file_path.suffix.lstrip("."),
                }
                if column_details:
                    result_data["column_details"] = column_details
                result_data.update(comparison)

                return ToolResult.success(
                    data=result_data,
                    summary=comparison.get("confirm_message", f"预览汇率文件：{len(df)} 行"),
                    record_count=min(5, len(df)),
                    data_shape="detail",
                )
            except Exception as e:
                logger.exception("[DataImportTool] fx preview error: {}", e)
                return ToolResult.error(f"文件预览失败: {e}")

        # 交易日历文件预览
        if import_type == "trade_dates":
            try:
                df = _read_file_df(file_path)
                df.columns = df.columns.astype(str).str.strip()
                df.rename(columns={k: v for k, v in TRADE_DATES_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

                # 如果没有 date 列，使用第一列
                if "date" not in df.columns and len(df.columns) > 0:
                    df.rename(columns={df.columns[0]: "date"}, inplace=True)

                columns = list(df.columns)
                row_count = len(df)
                sample_data = _df_to_safe_records(df, max_rows=5)

                # ── 计算精确的日期统计 ──
                file_summary = {
                    "file_name": file_path.name,
                    "total_rows": row_count,
                    "total_columns": len(columns),
                    "date_range": None,
                    "format": "交易日历",
                }
                trade_dates_details = {}
                if "date" in df.columns:
                    try:
                        parsed_dates = pd.to_datetime(df["date"].dropna(), errors="coerce").dropna()
                        if not parsed_dates.empty:
                            first_date = parsed_dates.min()
                            last_date = parsed_dates.max()
                            file_summary["date_range"] = (
                                f"{first_date.strftime('%Y-%m-%d')} ~ {last_date.strftime('%Y-%m-%d')}"
                            )
                            trade_dates_details = {
                                "total_trade_dates": len(parsed_dates),
                                "unique_trade_dates": int(parsed_dates.nunique()),
                                "duplicate_count": int(parsed_dates.duplicated().sum()),
                                "first_date": first_date.strftime("%Y-%m-%d"),
                                "last_date": last_date.strftime("%Y-%m-%d"),
                                "date_span_days": (last_date - first_date).days,
                            }
                    except Exception as e:
                        logger.warning("[DataImportTool] trade_dates details计算失败: {}", e)

                # ── 对比数据库现有数据 ──
                comparison = await self._compare_trade_dates_with_db(df)

                result_data = {
                    "file_summary": file_summary,
                    "columns": columns,
                    "row_count": row_count,
                    "sample_data": sample_data,
                    "detected_format": file_path.suffix.lstrip("."),
                }
                if trade_dates_details:
                    result_data["trade_dates_details"] = trade_dates_details
                result_data.update(comparison)

                return ToolResult.success(
                    data=result_data,
                    summary=comparison.get("confirm_message", f"预览交易日历文件：{row_count} 行"),
                    record_count=min(5, row_count),
                    data_shape="detail",
                )
            except Exception as e:
                logger.exception("[DataImportTool] trade_dates preview error: {}", e)
                return ToolResult.error(f"文件预览失败: {e}")

        # 行情数据预览
        if import_type == "price":
            try:
                df = _read_file_df(file_path)
                df.columns = df.columns.astype(str).str.strip()
                df.rename(columns={k: v for k, v in PRICE_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

                columns = list(df.columns)
                row_count = len(df)
                sample_data = _df_to_safe_records(df, max_rows=5)

                # ── 检测是否为宽表格式（日期列+多资产列）──
                # 判断: 有date列 + 多列数值型 = 宽表
                date_col = None
                if "date" in df.columns:
                    date_col = "date"
                elif len(df.columns) > 0:
                    # 尝试第一列是否为日期
                    try:
                        pd.to_datetime(df[df.columns[0]].dropna().head(10))
                        date_col = df.columns[0]
                    except Exception:
                        pass

                # 计算每列详细统计
                column_details = []
                file_summary = {
                    "file_name": file_path.name,
                    "total_rows": row_count,
                    "total_columns": len(columns),
                    "date_range": None,
                    "format": "归一化累积净值" if row_count > 0 else "unknown",
                }

                if date_col and date_col in df.columns:
                    # 解析日期列为 index 用于统计
                    try:
                        date_series = pd.to_datetime(df[date_col], errors="coerce")
                        valid_dates = date_series.dropna()
                        if not valid_dates.empty:
                            file_summary["date_range"] = (
                                f"{valid_dates.min().strftime('%Y-%m-%d')} ~ "
                                f"{valid_dates.max().strftime('%Y-%m-%d')}"
                            )

                        # 构建以日期为 index 的数值 DataFrame 进行逐列统计
                        data_cols = [c for c in df.columns if c != date_col]
                        if data_cols:
                            df_stats = df[data_cols].copy()
                            df_stats.index = date_series
                            # 仅保留 index 有效日期的行
                            df_stats = df_stats[df_stats.index.notna()]
                            # 尝试转为数值
                            for c in data_cols:
                                df_stats[c] = pd.to_numeric(df_stats[c], errors="coerce")
                            column_details = _compute_price_column_details(df_stats, df_stats.index)
                    except Exception as e:
                        logger.warning("[DataImportTool] price column_details计算失败: {}", e)

                file_summary["total_columns"] = len(column_details) if column_details else len(columns)

                # ── 对比数据库现有数据 ──
                comparison = await self._compare_price_with_db(df, asset_code)

                result_data = {
                    "file_summary": file_summary,
                    "columns": columns,
                    "row_count": row_count,
                    "sample_data": sample_data,
                    "detected_format": file_path.suffix.lstrip("."),
                }
                if column_details:
                    result_data["column_details"] = column_details
                result_data.update(comparison)

                return ToolResult.success(
                    data=result_data,
                    summary=comparison.get("confirm_message", f"预览行情文件：{row_count} 行，{len(column_details)} 个资产列"),
                    record_count=min(5, row_count),
                    data_shape="detail",
                )
            except Exception as e:
                logger.exception("[DataImportTool] price preview error: {}", e)
                return ToolResult.error(f"文件预览失败: {e}")

        # asset_info 预览
        if import_type == "asset_info":
            try:
                df = _read_file_df(file_path)
                df.columns = df.columns.astype(str).str.strip()
                df.rename(columns={k: v for k, v in ASSET_INFO_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

                columns = list(df.columns)
                row_count = len(df)
                sample_data = _df_to_safe_records(df, max_rows=5)

                # ── 对比数据库现有数据 ──
                comparison = await self._compare_asset_info_with_db(df)

                return ToolResult.success(
                    data={
                        "columns": columns,
                        "row_count": row_count,
                        "sample_data": sample_data,
                        "detected_format": file_path.suffix.lstrip("."),
                        **comparison,
                    },
                    summary=comparison.get("confirm_message", f"预览资产信息文件：{row_count} 行"),
                    record_count=min(5, row_count),
                    data_shape="detail",
                )
            except Exception as e:
                logger.exception("[DataImportTool] asset_info preview error: {}", e)
                return ToolResult.error(f"文件预览失败: {e}")

        # 通用文件预览（multi_asset 等）
        try:
            df = _read_file_df(file_path)
            df.columns = df.columns.astype(str).str.strip()
            mapping = PRICE_COLUMN_MAPPING if import_type == "price" else ASSET_INFO_COLUMN_MAPPING
            df.rename(columns={k: v for k, v in mapping.items() if k in df.columns}, inplace=True)

            columns = list(df.columns)
            row_count = len(df)
            sample_data = _df_to_safe_records(df, max_rows=5)

            return ToolResult.success(
                data={
                    "columns": columns,
                    "row_count": row_count,
                    "sample_data": sample_data,
                    "detected_format": file_path.suffix.lstrip("."),
                    "confirm_required": True,
                    "confirm_message": f"文件包含 {row_count} 行数据，是否确认执行导入？",
                },
                summary=f"预览文件：{row_count} 行，{len(columns)} 列",
                record_count=min(5, row_count),
                data_shape="detail",
            )
        except Exception as e:
            return ToolResult.error(f"文件预览失败: {e}")

    # ── 对比分析辅助方法 ───────────────────────────────────────────────────────

    async def _compare_fx_with_db(self, df: pd.DataFrame) -> dict:
        """对比汇率文件数据与数据库现有数据。"""
        try:
            # 获取文件日期集合
            if isinstance(df.index, pd.DatetimeIndex):
                file_dates = set(df.index.strftime("%Y-%m-%d"))
            else:
                file_dates = set(pd.to_datetime(df.index).strftime("%Y-%m-%d"))

            # 获取数据库日期集合
            existing_dates = await self._get_existing_fx_dates()

            # 计算差异
            new_dates = sorted(file_dates - existing_dates)
            overlap_dates = sorted(file_dates & existing_dates)

            existing_count = len(existing_dates)
            existing_min = min(existing_dates) if existing_dates else None
            existing_max = max(existing_dates) if existing_dates else None

            result = {
                "file_summary": {
                    "total_rows": len(df),
                    "date_range": f"{min(file_dates)} ~ {max(file_dates)}" if file_dates else "无",
                    "currencies": [c for c in ["EUR", "USD", "HKD", "CNH"] if c in df.columns.str.upper().tolist()],
                },
                "existing_data": {
                    "total_records": existing_count,
                    "date_range": f"{existing_min} ~ {existing_max}" if existing_count > 0 else "无数据",
                },
                "comparison": {
                    "new_records": len(new_dates),
                    "overlap_records": len(overlap_dates),
                    "new_date_range": f"{new_dates[0]} ~ {new_dates[-1]}" if new_dates else "无",
                    "overlap_date_range": f"{overlap_dates[0]} ~ {overlap_dates[-1]}" if overlap_dates else "无",
                },
                "confirm_required": True,
                "confirm_message": (
                    f"汇率文件包含 {len(file_dates)} 个交易日数据（{min(file_dates)} ~ {max(file_dates)}）。"
                    f"其中新增 {len(new_dates)} 条，与数据库重叠 {len(overlap_dates)} 条。"
                    f"是否确认执行导入？"
                ) if file_dates else "文件无有效日期数据",
            }
            return result
        except Exception as e:
            logger.warning("[DataImportTool] fx compare failed: {}", e)
            return {
                "confirm_required": True,
                "confirm_message": f"文件包含 {len(df)} 行数据（对比查询失败: {e}），是否确认执行导入？",
            }

    async def _compare_price_with_db(self, df: pd.DataFrame, asset_code: str) -> dict:
        """对比行情文件数据与数据库现有数据。"""
        try:
            # 获取文件日期集合
            if "date" not in df.columns:
                return {
                    "confirm_required": True,
                    "confirm_message": f"文件包含 {len(df)} 行数据，是否确认执行导入？",
                }

            df_dates = pd.to_datetime(df["date"].dropna())
            file_dates = set(df_dates.dt.strftime("%Y-%m-%d"))

            if not asset_code:
                return {
                    "file_summary": {
                        "total_rows": len(df),
                        "date_range": f"{min(file_dates)} ~ {max(file_dates)}" if file_dates else "无",
                    },
                    "existing_data": {
                        "total_records": 0,
                        "date_range": "未指定资产代码，无法对比",
                    },
                    "comparison": {
                        "new_records": len(file_dates),
                        "overlap_records": 0,
                        "note": "请在import时指定asset_code以获取精确对比",
                    },
                    "confirm_required": True,
                    "confirm_message": f"文件包含 {len(file_dates)} 个交易日行情数据，是否确认执行导入？",
                }

            # 获取数据库日期集合
            existing_dates = await self._get_existing_price_dates(asset_code)

            # 计算差异
            new_dates = sorted(file_dates - existing_dates)
            overlap_dates = sorted(file_dates & existing_dates)

            existing_count = len(existing_dates)
            existing_min = min(existing_dates) if existing_dates else None
            existing_max = max(existing_dates) if existing_dates else None

            result = {
                "file_summary": {
                    "total_rows": len(df),
                    "date_range": f"{min(file_dates)} ~ {max(file_dates)}" if file_dates else "无",
                    "columns": list(df.columns),
                },
                "existing_data": {
                    "asset_code": asset_code,
                    "total_records": existing_count,
                    "date_range": f"{existing_min} ~ {existing_max}" if existing_count > 0 else "无数据",
                },
                "comparison": {
                    "new_records": len(new_dates),
                    "overlap_records": len(overlap_dates),
                    "new_date_range": f"{new_dates[0]} ~ {new_dates[-1]}" if new_dates else "无",
                    "overlap_date_range": f"{overlap_dates[0]} ~ {overlap_dates[-1]}" if overlap_dates else "无",
                },
                "confirm_required": True,
                "confirm_message": (
                    f"资产 {asset_code} 行情文件包含 {len(file_dates)} 个交易日（{min(file_dates)} ~ {max(file_dates)}）。"
                    f"数据库现有 {existing_count} 条记录。"
                    f"本次导入：新增 {len(new_dates)} 条，覆盖 {len(overlap_dates)} 条。"
                    f"是否确认执行？"
                ) if file_dates else "文件无有效日期数据",
            }
            return result
        except Exception as e:
            logger.warning("[DataImportTool] price compare failed: {}", e)
            return {
                "confirm_required": True,
                "confirm_message": f"文件包含 {len(df)} 行数据（对比查询失败: {e}），是否确认执行导入？",
            }

    async def _compare_asset_info_with_db(self, df: pd.DataFrame) -> dict:
        """对比资产信息文件数据与数据库现有数据。"""
        try:
            if "code" not in df.columns:
                return {
                    "confirm_required": True,
                    "confirm_message": f"文件包含 {len(df)} 行数据，是否确认执行导入？",
                }

            file_codes = set(df["code"].dropna().astype(str).str.strip())
            existing_codes = await self._get_existing_asset_codes()

            new_codes = sorted(file_codes - existing_codes)
            overlap_codes = sorted(file_codes & existing_codes)

            result = {
                "file_summary": {
                    "total_rows": len(df),
                    "asset_count": len(file_codes),
                },
                "existing_data": {
                    "total_assets": len(existing_codes),
                },
                "comparison": {
                    "new_assets": len(new_codes),
                    "overlap_assets": len(overlap_codes),
                    "new_codes_sample": new_codes[:10],
                    "overlap_codes_sample": overlap_codes[:10],
                },
                "confirm_required": True,
                "confirm_message": (
                    f"文件包含 {len(file_codes)} 个资产。"
                    f"其中新增 {len(new_codes)} 个，已存在（将更新） {len(overlap_codes)} 个。"
                    f"是否确认执行导入？"
                ),
            }
            return result
        except Exception as e:
            logger.warning("[DataImportTool] asset_info compare failed: {}", e)
            return {
                "confirm_required": True,
                "confirm_message": f"文件包含 {len(df)} 行数据（对比查询失败: {e}），是否确认执行导入？",
            }

    async def _compare_trade_dates_with_db(self, df: pd.DataFrame) -> dict:
        """对比交易日历文件数据与数据库现有数据。"""
        try:
            if "date" not in df.columns:
                return {
                    "confirm_required": True,
                    "confirm_message": f"文件包含 {len(df)} 行数据，是否确认执行导入？",
                }

            # 获取文件日期集合
            df_dates = pd.to_datetime(df["date"].dropna(), errors="coerce").dropna()
            file_dates = set(df_dates.dt.strftime("%Y-%m-%d"))

            # 获取数据库日期集合
            existing_dates = await self._get_existing_trade_dates()

            # 计算差异
            new_dates = sorted(file_dates - existing_dates)
            overlap_dates = sorted(file_dates & existing_dates)

            existing_count = len(existing_dates)
            existing_min = min(existing_dates) if existing_dates else None
            existing_max = max(existing_dates) if existing_dates else None

            result = {
                "file_summary": {
                    "total_rows": len(file_dates),
                    "date_range": f"{min(file_dates)} ~ {max(file_dates)}" if file_dates else "无",
                },
                "existing_data": {
                    "total_records": existing_count,
                    "date_range": f"{existing_min} ~ {existing_max}" if existing_count > 0 else "无数据",
                },
                "comparison": {
                    "new_records": len(new_dates),
                    "overlap_records": len(overlap_dates),
                    "new_date_range": f"{new_dates[0]} ~ {new_dates[-1]}" if new_dates else "无",
                    "overlap_date_range": f"{overlap_dates[0]} ~ {overlap_dates[-1]}" if overlap_dates else "无",
                },
                "confirm_required": True,
                "confirm_message": (
                    f"交易日历文件包含 {len(file_dates)} 个交易日（{min(file_dates)} ~ {max(file_dates)}）。"
                    f"数据库现有 {existing_count} 条记录。"
                    f"本次导入：新增 {len(new_dates)} 条，重复 {len(overlap_dates)} 条。"
                    f"是否确认执行导入？"
                ) if file_dates else "文件无有效日期数据",
            }
            return result
        except Exception as e:
            logger.warning("[DataImportTool] trade_dates compare failed: {}", e)
            return {
                "confirm_required": True,
                "confirm_message": f"文件包含 {len(df)} 行数据（对比查询失败: {e}），是否确认执行导入？",
            }

    # ═══════════════════════════════════════════════════════════════════════════
    # import
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_import(self, kwargs: dict) -> dict:
        attachment_id = kwargs.get("attachment_id")
        import_type = kwargs.get("import_type")
        mode = kwargs.get("mode") or "incremental"  # 默认增量模式，仅导入新增数据

        logger.info(
            "[DataImportTool] _handle_import 参数: attachment_id={}, import_type={}, mode={}",
            attachment_id, import_type, mode,
        )

        if not attachment_id:
            logger.warning("[DataImportTool] import 失败: 缺少 attachment_id")
            return ToolResult.error("import 操作需要提供 attachment_id")
        if not import_type:
            logger.warning("[DataImportTool] import 失败: 缺少 import_type, kwargs={}" , kwargs)
            return ToolResult.error("import 操作需要提供 import_type")

        file_path = AttachmentService.get_file_path(attachment_id)
        if not file_path or not file_path.exists():
            return ToolResult.error(f"附件不存在或已过期: {attachment_id}")

        if import_type == "price":
            result = await self._import_price(file_path, kwargs)
        elif import_type == "fx":
            result = await self._import_fx(file_path, mode)
        elif import_type == "asset_info":
            result = await self._import_asset_info(file_path, mode)
        elif import_type == "multi_asset":
            result = await self._import_multi_asset(file_path, kwargs)
        elif import_type == "trade_dates":
            result = await self._import_trade_dates(file_path, mode)
        else:
            return ToolResult.error(f"不支持的导入类型: {import_type}")

        # 导入成功后记录血缘（失败不影响导入结果）
        await self._record_lineage_after_import(
            result=result,
            import_type=import_type,
            file_name=file_path.name,
        )

        return result

    async def _record_lineage_after_import(self, result: dict, import_type: str, file_name: str):
        """导入成功后记录血缘信息（失败只记日志，不影响业务）"""
        try:
            # 只在导入成功时记录血缘
            result_data = result.get("data", {})
            if result_data.get("status") != "success":
                return

            from app.services.lineage_service import LineageService
            lineage = LineageService.get_instance()

            # 根据 import_type 确定目标集合和域
            collection_map = {
                "price": "asset_prices",
                "fx": "fx_rates",
                "asset_info": "assets",
                "multi_asset": "asset_prices",
                "trade_dates": "trade_dates",
            }
            domain_map = {
                "price": "market",
                "fx": "market",
                "asset_info": "asset",
                "multi_asset": "market",
                "trade_dates": "market",
            }

            target_collection = collection_map.get(import_type, import_type)
            domain = domain_map.get(import_type, "unknown")

            # 从结果中提取记录数
            record_count = result.get("record_count", 0) or 0

            batch_id = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            await lineage.record_import_lineage(
                source_type="SOURCE_FILE",
                source_name=file_name,
                target_collection=target_collection,
                domain=domain,
                record_count=record_count,
                batch_id=batch_id,
            )
        except Exception as e:
            logger.warning(f"血缘记录失败（不影响导入）: {e}")

    async def _import_price(self, file_path: Path, kwargs: dict) -> dict:
        """执行行情数据导入，返回详细汇总。
        支持两种格式：
        1. 单资产窄表（需提供 asset_code）：date/close/open/high/low 等列
        2. 多资产宽表（无需 asset_code）：第一列为日期 index，其余列为资产价格
        """
        asset_code = kwargs.get("asset_code")
        mode = kwargs.get("mode") or "incremental"  # 默认增量模式

        # 如果没有指定 asset_code，尝试宽表格式导入
        if not asset_code:
            try:
                df_check = _read_fx_df(file_path)
                if not df_check.empty and len(df_check.columns) >= 1:
                    # 检查是否有数值列（排除纯文本列）
                    numeric_cols = [c for c in df_check.columns
                                    if pd.to_numeric(df_check[c], errors="coerce").dropna().shape[0] > 0]
                    if numeric_cols:
                        logger.info(
                            "[DataImportTool] 检测到宽表格式（无 asset_code），{} 个数值列，使用宽表导入模式",
                            len(numeric_cols),
                        )
                        return await self._import_price_wide_table(file_path, mode)
            except Exception as e:
                logger.debug("[DataImportTool] 宽表检测失败，回退到单资产模式: {}", e)
            return ToolResult.error(
                "行情导入需要提供 asset_code（目标资产代码），"
                "或上传日期为第一列的宽表格式文件"
            )

        from app.services.asset_service import AssetService
        service = AssetService()

        # 验证资产存在
        asset = await service.get_asset_by_code(asset_code)
        if not asset:
            return ToolResult.error(f"资产不存在: {asset_code}")

        # 读取并解析文件
        try:
            df = _read_file_df(file_path)
            df.columns = df.columns.astype(str).str.strip()
            df.rename(columns={k: v for k, v in PRICE_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)
            df.columns = df.columns.str.lower()
            df.rename(columns={k: v for k, v in PRICE_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

            if "date" not in df.columns:
                return ToolResult.error("文件缺少日期列，无法导入")

            df.dropna(subset=["date"], inplace=True)
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            price_data_list = df.to_dict("records")
        except Exception as e:
            return ToolResult.error(f"文件解析失败: {e}")

        if not price_data_list:
            return ToolResult.error("文件无有效数据行")

        # ── 导入前查询现有数据日期 ──
        existing_dates_before = await self._get_existing_price_dates(asset_code)
        file_dates = set(d["date"] for d in price_data_list if d.get("date"))

        # 确定导入参数
        replace_existing = mode in ("replace", "overwrite")
        only_missing_dates = mode in ("incremental", "only_missing")

        # 覆盖模式提示
        warning_msg = ""
        if replace_existing:
            warning_msg = f"⚠️ 替换模式：已删除资产 {asset_code} 的全部历史行情后写入新数据。"

        logger.info(
            "[DataImportTool] 导入行情 asset_code={} mode={} rows={}",
            asset_code, mode, len(price_data_list),
        )

        result = await service.import_price_data(
            asset_code=asset_code,
            price_data_list=price_data_list,
            replace_existing=replace_existing,
            only_missing_dates=only_missing_dates,
        )

        # ── 导入后查询新的日期集合 ──
        existing_dates_after = await self._get_existing_price_dates(asset_code)

        # 计算新增和覆盖日期
        if replace_existing:
            newly_added_dates = sorted(file_dates)
            overwritten_dates = []
        else:
            newly_added_dates = sorted(existing_dates_after - existing_dates_before)
            overwritten_dates = sorted(file_dates & existing_dates_before)

        file_date_range = ""
        if file_dates:
            file_date_range = f"{min(file_dates)} ~ {max(file_dates)}"

        summary = (
            f"行情导入完成({asset_code})：新增 {result['inserted_count']} 条，"
            f"更新 {result['updated_count']} 条，跳过 {result.get('skipped_count', 0)} 条，"
            f"错误 {result['error_count']} 条"
        )
        if warning_msg:
            summary = warning_msg + "\n" + summary

        return ToolResult.success(
            data={
                "status": "success",
                "asset_code": asset_code,
                "mode": mode,
                "summary": {
                    "total_processed": result["total_count"],
                    "new_inserted": result["inserted_count"],
                    "updated_overwritten": result["updated_count"],
                    "skipped": result.get("skipped_count", 0),
                    "failed": result["error_count"],
                    "file_date_range": file_date_range,
                    "new_date_range": f"{newly_added_dates[0]} ~ {newly_added_dates[-1]}" if newly_added_dates else "无",
                    "overwritten_date_range": f"{overwritten_dates[0]} ~ {overwritten_dates[-1]}" if overwritten_dates else "无",
                    "target_collection": "asset_prices",
                    "db_total_after_import": len(existing_dates_after),
                },
                "errors": result.get("errors", [])[:10],
            },
            summary=summary,
            record_count=result["inserted_count"] + result["updated_count"],
            data_shape="detail",
        )

    async def _import_price_wide_table(self, file_path: Path, mode: str = "incremental") -> dict:
        """宽表格式行情导入：第一列为日期 index，其余列为资产价格。
        按资产列逐个导入，使用 bulk_write 批量操作。
        支持 incremental 模式：查询每个资产在数据库中的最新日期，只导入更新的数据。
        """
        if not mode:
            mode = "incremental"
        from app.config.database import Database
        from pymongo import UpdateOne

        db = Database.get_database()
        if db is None:
            return ToolResult.error("数据库连接不可用")

        try:
            df = _read_fx_df(file_path)
        except Exception as e:
            return ToolResult.error(f"文件解析失败: {e}")

        if df.empty:
            return ToolResult.error("文件为空或无法解析出有效数据")

        # 确保 DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception as e:
                return ToolResult.error(f"日期索引解析失败: {e}")

        total_assets = len(df.columns)
        results = []
        collection = db["asset_prices"]
        is_incremental = mode in ("incremental", "only_missing")

        for i, col in enumerate(df.columns, 1):
            col_name = str(col).strip()
            asset_code = _map_column_to_asset_code(col_name)
            series = pd.to_numeric(df[col], errors="coerce").dropna()

            if len(series) == 0:
                results.append({
                    "asset": col_name, "asset_code": asset_code,
                    "status": "skipped", "reason": "全空列",
                    "records": 0, "inserted": 0, "modified": 0,
                })
                continue

            # 增量模式：查询该资产在数据库中的最新日期，只导入更新的数据
            if is_incremental:
                latest_doc = await collection.find_one(
                    {"asset_code": asset_code},
                    sort=[("date", -1)],
                )
                if latest_doc and latest_doc.get("date"):
                    cutoff = pd.Timestamp(latest_doc["date"])
                    series = series[series.index > cutoff]
                    if len(series) == 0:
                        results.append({
                            "asset": col_name, "asset_code": asset_code,
                            "status": "skipped", "reason": "无新数据",
                            "records": 0, "inserted": 0, "modified": 0,
                        })
                        continue

            # 构建 bulk_write 操作
            operations = []
            for dt, val in series.items():
                date_str = dt.strftime("%Y-%m-%d")
                doc = {
                    "date": date_str,
                    "asset_code": asset_code,
                    "close": float(val),
                }
                operations.append(
                    UpdateOne(
                        {"date": date_str, "asset_code": asset_code},
                        {"$set": doc},
                        upsert=True,
                    )
                )

            # 分批执行（每扗1000条）
            batch_size = 1000
            inserted = 0
            modified = 0
            for j in range(0, len(operations), batch_size):
                batch = operations[j:j + batch_size]
                result = await collection.bulk_write(batch, ordered=False)
                inserted += result.upserted_count
                modified += result.modified_count

            results.append({
                "asset": col_name,
                "asset_code": asset_code,
                "status": "success",
                "records": len(series),
                "inserted": inserted,
                "modified": modified,
            })
            logger.info(
                "[DataImportTool] 宽表导入进度 {}/{} asset={} records={} inserted={} modified={}",
                i, total_assets, asset_code, len(series), inserted, modified,
            )

        completed = [r for r in results if r["status"] == "success"]
        skipped = [r for r in results if r["status"] == "skipped"]
        total_inserted = sum(r["inserted"] for r in completed)
        total_modified = sum(r["modified"] for r in completed)

        # 日期范围
        file_date_range = ""
        try:
            file_date_range = (
                f"{df.index.min().strftime('%Y-%m-%d')} ~ "
                f"{df.index.max().strftime('%Y-%m-%d')}"
            )
        except Exception:
            pass

        # 增量模式无新数据时返回友好消息
        if is_incremental and len(completed) == 0 and len(skipped) == total_assets:
            summary = f"✅ 所有数据已是最新，无需导入（共{total_assets}个资产均已存在于数据库中）"
        else:
            summary = (
                f"宽表行情导入完成：共{total_assets}个资产，"
                f"成功{len(completed)}个，跳过{len(skipped)}个，"
                f"新增{total_inserted}条，更新{total_modified}条"
            )

        return ToolResult.success(
            data={
                "status": "success",
                "mode": mode,
                "total_assets": total_assets,
                "completed_assets": len(completed),
                "skipped_assets": len(skipped),
                "total_inserted": total_inserted,
                "total_modified": total_modified,
                "file_date_range": file_date_range,
                "target_collection": "asset_prices",
                "details": results,
            },
            summary=summary,
            record_count=total_inserted + total_modified,
            data_shape="detail",
        )

    async def _import_fx(self, file_path: Path, mode: str = "incremental") -> dict:
        """执行汇率数据导入，返回详细汇总。"""
        if not mode:
            mode = "incremental"
        from app.services.fx_service import FxService
        service = FxService()

        try:
            df = _read_fx_df(file_path)
        except Exception as e:
            return ToolResult.error(f"汇率文件解析失败: {e}")

        if df.empty:
            return ToolResult.error("文件为空或无法解析出有效数据")

        # 标准化列名
        df.columns = df.columns.astype(str).str.strip().str.upper()
        valid_cols = [c for c in FxService.FX_COLUMNS if c in df.columns]
        if not valid_cols:
            return ToolResult.error(
                f"未找到有效货币列（需要 EUR/USD/HKD/CNH 中至少一列），当前列: {list(df.columns)}"
            )

        # 映射 mode
        fx_mode = "replace" if mode in ("replace", "overwrite") else "incremental"

        # ── 导入前查询现有数据日期 ──
        existing_dates_before = await self._get_existing_fx_dates()

        warning_msg = ""
        if fx_mode == "replace":
            warning_msg = "⚠️ 替换模式：已清空全部汇率数据后写入文件内容。"

        logger.info("[DataImportTool] 导入汇率 mode={} rows={} cols={}", fx_mode, len(df), valid_cols)

        stats = await service.import_from_dataframe(df, mode=fx_mode)

        # ── 导入后查询新的日期集合 ──
        existing_dates_after = await self._get_existing_fx_dates()

        # 计算文件日期范围
        file_date_range = ""
        try:
            idx = pd.to_datetime(df.index) if not isinstance(df.index, pd.DatetimeIndex) else df.index
            file_dates_set = set(idx.strftime("%Y-%m-%d"))
            file_date_range = f"{idx.min().strftime('%Y-%m-%d')} ~ {idx.max().strftime('%Y-%m-%d')}"
        except Exception:
            file_dates_set = set()

        # 计算新增和覆盖日期
        newly_added_dates = sorted(existing_dates_after - existing_dates_before) if fx_mode != "replace" else []
        overwritten_dates = sorted(file_dates_set & existing_dates_before) if fx_mode != "replace" else []

        touched = stats["inserted"] + stats["updated"]

        if fx_mode == "replace":
            summary = f"汇率全量覆盖完成，共写入 {stats['inserted']} 条"
        elif stats["inserted"] == 0 and stats["updated"] == 0:
            summary = "✅ 所有汇率数据已是最新，无需导入"
        else:
            summary = (
                f"汇率增量导入完成：新增 {stats['inserted']} 日、"
                f"补充 {stats['updated']} 日缺失字段，跳过已存在数值 {stats['skipped_cells']} 项"
            )
        if warning_msg:
            summary = warning_msg + "\n" + summary

        return ToolResult.success(
            data={
                "status": "success",
                "mode": fx_mode,
                "summary": {
                    "total_processed": len(df),
                    "new_inserted": stats["inserted"],
                    "updated_supplemented": stats["updated"],
                    "skipped_cells": stats["skipped_cells"],
                    "file_date_range": file_date_range,
                    "new_date_range": f"{newly_added_dates[0]} ~ {newly_added_dates[-1]}" if newly_added_dates else "无",
                    "overwritten_date_range": f"{overwritten_dates[0]} ~ {overwritten_dates[-1]}" if overwritten_dates else "无",
                    "target_collection": "fx_rates",
                    "currencies": valid_cols,
                    "db_total_after_import": len(existing_dates_after),
                },
            },
            summary=summary,
            record_count=touched,
            data_shape="detail",
        )

    async def _import_asset_info(self, file_path: Path, mode: str) -> dict:
        """执行资产信息导入。"""
        from app.services.asset_service import AssetService
        service = AssetService()

        try:
            df = _read_file_df(file_path)
            df.columns = df.columns.astype(str).str.strip()
            df.rename(columns={k: v for k, v in ASSET_INFO_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)
        except Exception as e:
            return ToolResult.error(f"文件解析失败: {e}")

        if "code" not in df.columns or "name" not in df.columns:
            return ToolResult.error("文件缺少必填列 code/name")

        # 清理空行
        df.dropna(subset=["code", "name"], inplace=True)
        if df.empty:
            return ToolResult.error("文件无有效数据行（code 或 name 全为空）")

        assets_data = df.to_dict("records")

        logger.info("[DataImportTool] 导入资产信息 mode={} rows={}", mode, len(assets_data))

        result = await service.import_assets_from_excel_data(assets_data)

        summary = (
            f"资产信息导入完成：新增 {result['inserted_count']} 个，"
            f"更新 {result['updated_count']} 个，错误 {result['error_count']} 个"
        )

        return ToolResult.success(
            data={
                "mode": mode,
                "total_count": result["total_count"],
                "inserted_count": result["inserted_count"],
                "updated_count": result["updated_count"],
                "error_count": result["error_count"],
                "errors": result.get("errors", [])[:10],
            },
            summary=summary,
            record_count=result["inserted_count"] + result["updated_count"],
            data_shape="detail",
        )

    async def _import_trade_dates(self, file_path: Path, mode: str = "incremental") -> dict:
        """执行交易日历数据导入，返回详细汇总。"""
        if not mode:
            mode = "incremental"
        from app.config.database import Database

        db = Database.get_database()
        if db is None:
            return ToolResult.error("数据库连接不可用")

        try:
            df = _read_file_df(file_path)
            df.columns = df.columns.astype(str).str.strip()
            df.rename(columns={k: v for k, v in TRADE_DATES_COLUMN_MAPPING.items() if k in df.columns}, inplace=True)

            # 如果没有 date 列，使用第一列
            if "date" not in df.columns and len(df.columns) > 0:
                df.rename(columns={df.columns[0]: "date"}, inplace=True)

            if "date" not in df.columns:
                return ToolResult.error("文件缺少日期列，无法导入")

            df.dropna(subset=["date"], inplace=True)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df.dropna(subset=["date"], inplace=True)

            if df.empty:
                return ToolResult.error("文件无有效日期数据")

            # 去重
            df.drop_duplicates(subset=["date"], inplace=True)
            file_dates = set(df["date"].dt.strftime("%Y-%m-%d"))
        except Exception as e:
            return ToolResult.error(f"文件解析失败: {e}")

        collection = db["trade_dates"]
        td_mode = "replace" if mode in ("replace", "overwrite") else "incremental"

        # ── 导入前查询现有数据 ──
        existing_dates_before = await self._get_existing_trade_dates()

        warning_msg = ""
        if td_mode == "replace":
            warning_msg = "⚠️ 替换模式：已清空全部交易日历数据后写入文件内容。"
            await collection.delete_many({})

        logger.info("[DataImportTool] 导入交易日历 mode={} rows={}", td_mode, len(df))

        # 构建待插入的文档
        inserted_count = 0
        skipped_count = 0
        error_count = 0

        if td_mode == "replace":
            # 全量写入
            docs = [{"date": row["date"].to_pydatetime()} for _, row in df.iterrows()]
            if docs:
                await collection.insert_many(docs)
                inserted_count = len(docs)
        else:
            # 增量模式：批量插入不存在的日期
            new_docs = []
            for _, row in df.iterrows():
                date_val = row["date"].to_pydatetime()
                date_str = row["date"].strftime("%Y-%m-%d")
                if date_str in existing_dates_before:
                    skipped_count += 1
                    continue
                new_docs.append({"date": date_val})

            if new_docs:
                batch_size = 1000
                for j in range(0, len(new_docs), batch_size):
                    batch = new_docs[j:j + batch_size]
                    try:
                        result = await collection.insert_many(batch, ordered=False)
                        inserted_count += len(result.inserted_ids)
                    except Exception as e:
                        logger.warning(
                            "[DataImportTool] trade_dates batch insert error: {}", e
                        )
                        error_count += len(batch)

        # ── 导入后查询新的日期集合 ──
        existing_dates_after = await self._get_existing_trade_dates()

        # 计算新增日期
        newly_added_dates = sorted(existing_dates_after - existing_dates_before) if td_mode != "replace" else sorted(file_dates)

        file_date_range = ""
        if file_dates:
            file_date_range = f"{min(file_dates)} ~ {max(file_dates)}"

        if td_mode != "replace" and inserted_count == 0 and error_count == 0:
            summary = f"✅ 所有交易日历数据已是最新，无需导入（{skipped_count} 条日期均已存在）"
        else:
            summary = (
                f"交易日历导入完成：新增 {inserted_count} 条，"
                f"跳过已存在 {skipped_count} 条，错误 {error_count} 条"
            )
        if warning_msg:
            summary = warning_msg + "\n" + summary

        return ToolResult.success(
            data={
                "status": "success",
                "mode": td_mode,
                "summary": {
                    "total_processed": len(df),
                    "new_inserted": inserted_count,
                    "skipped_existing": skipped_count,
                    "failed": error_count,
                    "file_date_range": file_date_range,
                    "new_date_range": f"{newly_added_dates[0]} ~ {newly_added_dates[-1]}" if newly_added_dates else "无",
                    "target_collection": "trade_dates",
                    "db_total_after_import": len(existing_dates_after),
                },
            },
            summary=summary,
            record_count=inserted_count,
            data_shape="detail",
        )

    async def _import_multi_asset(self, file_path: Path, kwargs: dict) -> dict:
        """执行多资产宽表导入。"""
        from app.services.asset_service import AssetService
        service = AssetService()

        mode = kwargs.get("mode") or "incremental"  # 默认增量模式
        replace_existing = mode in ("replace", "overwrite")
        only_missing_dates = mode in ("incremental", "only_missing")

        warning_msg = ""
        if replace_existing:
            warning_msg = "⚠️ 替换模式：将清空相关资产已有行情后写入新数据。"

        try:
            contents = file_path.read_bytes()
        except Exception as e:
            return ToolResult.error(f"读取文件失败: {e}")

        logger.info("[DataImportTool] 导入多资产宽表 mode={}", mode)

        try:
            result = await service.import_multi_asset_from_excel(
                contents=contents,
                overwrite_name=False,
                replace_existing=replace_existing,
                only_missing_dates=only_missing_dates,
                metric="close",
            )
        except Exception as e:
            return ToolResult.error(f"多资产导入失败: {e}")

        summary = (
            f"多资产导入完成：新增资产 {result['assets_created']} 个，"
            f"更新 {result['assets_updated']} 个，行情 {result['prices_imported']} 条"
        )
        if warning_msg:
            summary = warning_msg + "\n" + summary

        return ToolResult.success(
            data=result,
            summary=summary,
            record_count=result.get("prices_imported", 0),
            data_shape="detail",
        )
