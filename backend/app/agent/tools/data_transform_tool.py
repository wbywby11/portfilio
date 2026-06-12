"""
数据加工工具 — 原子能力层

提供 DataTransformTool (data_transform)：
数据关联、过滤、重采样、透视、标准化
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult


class DataTransformTool(BaseTool):
    """数据加工工具"""

    name = "data_transform"
    description = (
        "数据加工工具。对查询结果进行二次处理："
        "merge(简单单键关联), filter(条件过滤), "
        "resample(时间序列重采样), pivot(透视聚合), "
        "normalize(列名映射/格式转换/缺失填充), "
        "join(专业多表连接:多关联键/唯一性校验/左右全连接), "
        "union(纵向并集:多表堆叠/UNION ALL/UNION DISTINCT), "
        "map_dimension(维度映射:编码字段替换为业务名称/命中率统计)"
    )
    category = "data"
    tags = ["加工", "清洗", "关联", "转换", "透视", "连接", "并集", "维度映射"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["merge", "filter", "resample", "pivot", "normalize",
                         "join", "union", "map_dimension"],
                "description": "加工类型",
            },
            "source_data": {
                "type": "object",
                "description": "源数据（来自前序工具的输出结果或直接提供的数据）。join/union 操作使用专属参数，可不传。",
            },
            "source_ref": {
                "type": "string",
                "description": "引用会话中前序步骤的数据集，如 'step_1'。指定后直接使用该数据作为 source_data，无需重新传入。",
            },
            "left_ref": {
                "type": "string",
                "description": "[join 专用] 左表前序数据引用，如 'step_1'。与 source_ref 二选一作为左表。",
            },
            "right_ref": {
                "type": "string",
                "description": "[join 专用] 右表前序数据引用，如 'step_2'。与 config.right_data 二选一作为右表。",
            },
            "sources": {
                "type": "array",
                "items": {},
                "description": (
                    "[union 专用] 要堆叠的数据源列表。"
                    "每项可以是: (1) 字符串 source_ref 引用，如 'step_1'；"
                    "(2) 内联 list/dict 数据。至少需要 2 个数据源。"
                ),
            },
            "config": {
                "type": "object",
                "description": (
                    "加工配置（各 action 专属字段）:\n"
                    "merge: {right_data, join_key(str), join_type(left/inner/outer)}\n"
                    "filter: {conditions: [{field, op, value}]}\n"
                    "resample: {date_column, frequency(W/M/Q/Y), agg_method(mean/sum/last/first)}\n"
                    "pivot: {index, columns, values, aggfunc}\n"
                    "normalize: {mapping(列名映射dict), fill_value, date_format}\n"
                    "join: {join_keys(str或str数组), join_type(left/right/inner/outer, 默认left), "
                    "validate(many_to_many/one_to_one/one_to_many/many_to_one, 默认many_to_many), "
                    "suffixes([left_suffix, right_suffix], 默认['_left','_right']), right_data(右表内联数据)}\n"
                    "union: {mode(all/distinct, 默认all), fill_missing(bool, 默认true)}\n"
                    "map_dimension: {key_field(主表编码字段), map_source(映射表内联数据), "
                    "map_source_ref(映射表前序引用), map_key_field(映射表键字段), "
                    "map_value_field(映射表值字段), output_field(输出字段名,默认覆盖key_field), "
                    "keep_unmapped(未命中时保留原值, 默认true)}"
                ),
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        action: str = kwargs.get("action", "")
        config = kwargs.get("config", {})
        conversation_id: str | None = kwargs.get("conversation_id")

        # 修复：处理 config 可能是字符串的情况（Qwen3 嵌套编码）
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, ValueError):
                config = {}
        if not isinstance(config, dict):
            config = {}
        config = config or {}

        # 修复：处理 source_data 可能是字符串的情况
        source_data_raw = kwargs.get("source_data")
        if isinstance(source_data_raw, str):
            try:
                kwargs["source_data"] = json.loads(source_data_raw)
            except (json.JSONDecodeError, ValueError):
                pass  # 保持原值，后续通过正常流程报错

        # ── join / union / map_dimension 使用各自的专属入口 ──
        if action == "join":
            return await self._execute_join(kwargs, config, conversation_id)
        if action == "union":
            return await self._execute_union(kwargs, config, conversation_id)
        if action == "map_dimension":
            return await self._execute_map_dimension(kwargs, config, conversation_id)

        # ── 通用 source_ref 引用机制：从 DataContext 获取前序数据注入 source_data ──
        source_ref: str | None = kwargs.get("source_ref")
        if source_ref:
            if not conversation_id:
                return ToolResult.error("source_ref 需要会话上下文，缺少 conversation_id")
            from app.agent.services.data_context import DataContext
            ctx = DataContext.get_instance(conversation_id)
            ref_data = ctx.get(source_ref)
            if ref_data is None:
                available = ctx.list_datasets()
                return ToolResult.error(
                    f"数据引用 '{source_ref}' 不存在。可用：{[d['key'] for d in available]}"
                )
            kwargs["source_data"] = ref_data

        source_data: dict | list | None = kwargs.get("source_data")

        if source_data is None:
            return ToolResult.error("source_data 不能为空")

        handler = {
            "merge": self._merge,
            "filter": self._filter,
            "resample": self._resample,
            "pivot": self._pivot,
            "normalize": self._normalize,
        }.get(action)

        if handler is None:
            return ToolResult.error(
                f"不支持的加工类型: {action}，"
                "可选: merge/filter/resample/pivot/normalize/join/union/map_dimension"
            )

        try:
            result = handler(source_data, config)
        except ValueError as e:
            logger.error("[DataTransform] 参数错误: {}", e)
            return ToolResult.error(f"参数错误: {e}")
        except Exception as e:
            logger.error("[DataTransform] 执行失败: {}", e)
            return ToolResult.error(f"加工失败: {e}")

        # ── 附加血缘：本工具仅加工上游数据，纯透传上游 lineage ──
        if not (isinstance(result, dict) and result.get("success")):
            return result
        if "_lineage_meta" in result:
            return result
        upstream_lineage = None
        if source_ref:
            upstream_lineage = {"query_operation": f"source_ref:{source_ref}"}
        rec_count = result.get("metadata", {}).get("record_count", 0)
        return self.attach_lineage(
            result,
            tables=[],
            domains=[],
            fields={},
            records_returned=rec_count,
            query_operation=f"data_transform:{action}",
            upstream_lineage=upstream_lineage,
        )

    # ──────────────────────────────────────────────────────────────
    #  辅助：从 DataContext 获取前序引用数据
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _resolve_ref(
        ref_key: str, conversation_id: str | None
    ) -> tuple[Any | None, str | None]:
        """从 DataContext 获取前序数据引用。返回 (data, error_msg)。"""
        if not conversation_id:
            return None, "引用前序数据需要会话上下文，缺少 conversation_id"
        from app.agent.services.data_context import DataContext
        ctx = DataContext.get_instance(conversation_id)
        data = ctx.get(ref_key)
        if data is None:
            available = [d["key"] for d in ctx.list_datasets()]
            return None, f"数据引用 '{ref_key}' 不存在。可用数据集：{available}"
        return data, None

    @staticmethod
    def _to_df(data: Any) -> pd.DataFrame:
        """将多种输入格式转为 DataFrame"""
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, list):
            return pd.DataFrame(data)
        if isinstance(data, dict):
            if "records" in data:
                return pd.DataFrame(data["records"])
            return pd.DataFrame(data)
        return pd.DataFrame()

    # ──────────────────────────────────────────────────────────────
    #  join — 专业多表连接
    # ──────────────────────────────────────────────────────────────
    async def _execute_join(
        self, kwargs: dict, config: dict, conversation_id: str | None
    ) -> dict:
        """专业多表连接：支持多关联键、双 ref 引用、唯一性校验。"""
        # 解析左表
        left_ref: str | None = kwargs.get("left_ref") or kwargs.get("source_ref")
        if left_ref:
            left_data, err = self._resolve_ref(left_ref, conversation_id)
            if err:
                return ToolResult.error(err)
        else:
            left_data = kwargs.get("source_data")
            if left_data is None:
                return ToolResult.error(
                    "join 需要左表数据，请通过 left_ref 或 source_ref 或 source_data 提供"
                )

        # 解析右表
        right_ref: str | None = kwargs.get("right_ref")
        if right_ref:
            right_data, err = self._resolve_ref(right_ref, conversation_id)
            if err:
                return ToolResult.error(err)
        else:
            right_data = config.get("right_data")
            if right_data is None:
                return ToolResult.error(
                    "join 需要右表数据，请通过 right_ref 参数或 config.right_data 提供"
                )

        # 关联键
        raw_keys = config.get("join_keys")
        if not raw_keys:
            return ToolResult.error("join 需要 config.join_keys 指定关联键")
        join_keys: list[str] = [raw_keys] if isinstance(raw_keys, str) else list(raw_keys)

        join_type: str = config.get("join_type", "left")
        if join_type not in ("left", "right", "inner", "outer"):
            return ToolResult.error(
                f"不支持的 join_type: {join_type}，可选: left/right/inner/outer"
            )

        validate_mode: str = config.get("validate", "many_to_many")
        suffixes: list = config.get("suffixes", ["_left", "_right"])
        if not isinstance(suffixes, (list, tuple)) or len(suffixes) != 2:
            suffixes = ["_left", "_right"]

        try:
            left_df = self._to_df(left_data)
            right_df = self._to_df(right_data)

            # 唯一性预校验（仅在 validate_mode != many_to_many 时执行，给出友好提示）
            if validate_mode != "many_to_many":
                if validate_mode in ("one_to_one", "many_to_one"):
                    dups = right_df[right_df.duplicated(subset=join_keys, keep=False)]
                    if not dups.empty:
                        dup_vals = dups[join_keys[0]].unique().tolist()[:5]
                        return ToolResult.error(
                            f"唯一性校验失败（{validate_mode}）：右表关联键 {join_keys} "
                            f"存在重复值（示例: {dup_vals}），请先去重后再关联"
                        )
                if validate_mode in ("one_to_one", "one_to_many"):
                    dups = left_df[left_df.duplicated(subset=join_keys, keep=False)]
                    if not dups.empty:
                        dup_vals = dups[join_keys[0]].unique().tolist()[:5]
                        return ToolResult.error(
                            f"唯一性校验失败（{validate_mode}）：左表关联键 {join_keys} "
                            f"存在重复值（示例: {dup_vals}），请先去重后再关联"
                        )

            left_count = len(left_df)
            right_count = len(right_df)

            merged = pd.merge(
                left_df, right_df,
                on=join_keys,
                how=join_type,
                suffixes=tuple(suffixes),
            )

            records = self._df_to_records(merged)
            result_count = len(records)

            # 构建详细摘要
            lost = left_count - result_count if join_type == "inner" else 0
            summary = (
                f"{join_type.upper()} JOIN 完成 | "
                f"关联键: {join_keys} | "
                f"左表 {left_count} 条 × 右表 {right_count} 条 → 结果 {result_count} 条"
            )
            if join_type == "inner" and lost > 0:
                summary += f" | 因无匹配丢失 {lost} 条（左表）"

            return ToolResult.success(
                data={"records": records},
                summary=summary,
                data_shape="table",
                record_count=result_count,
            )
        except ValueError as e:
            logger.error("[DataTransform.join] 参数错误: {}", e)
            return ToolResult.error(f"join 参数错误: {e}")
        except Exception as e:
            logger.error("[DataTransform.join] 执行失败: {}", e)
            return ToolResult.error(f"join 失败: {e}")

    # ──────────────────────────────────────────────────────────────
    #  union — 纵向并集运算
    # ──────────────────────────────────────────────────────────────
    async def _execute_union(
        self, kwargs: dict, config: dict, conversation_id: str | None
    ) -> dict:
        """纵向并集运算：堆叠多张结构相同或相似的表。"""
        sources_raw: list | None = kwargs.get("sources")
        if not sources_raw or len(sources_raw) < 2:
            return ToolResult.error(
                "union 需要 sources 参数，且至少包含 2 个数据源（字符串 ref 或内联数据）"
            )

        mode: str = config.get("mode", "all")
        if mode not in ("all", "distinct"):
            return ToolResult.error(f"不支持的 mode: {mode}，可选: all/distinct")
        fill_missing: bool = config.get("fill_missing", True)

        try:
            dfs: list[pd.DataFrame] = []
            for idx, src in enumerate(sources_raw):
                if isinstance(src, str):
                    # 字符串视为 source_ref
                    data, err = self._resolve_ref(src, conversation_id)
                    if err:
                        return ToolResult.error(f"sources[{idx}] 引用失败: {err}")
                    dfs.append(self._to_df(data))
                else:
                    dfs.append(self._to_df(src))

            # 非 fill_missing 时，仅保留公共列
            if not fill_missing:
                common_cols = list(
                    set.intersection(*[set(df.columns) for df in dfs])
                )
                if not common_cols:
                    return ToolResult.error(
                        "union fill_missing=false 模式下各表无公共列，无法堆叠"
                    )
                dfs = [df[common_cols] for df in dfs]

            combined = pd.concat(dfs, axis=0, ignore_index=True)

            if mode == "distinct":
                before = len(combined)
                combined = combined.drop_duplicates()
                dedup_count = before - len(combined)
            else:
                dedup_count = 0

            records = self._df_to_records(combined)
            result_count = len(records)
            col_count = len(combined.columns)

            summary = (
                f"UNION {mode.upper()} 完成 | "
                f"合并 {len(dfs)} 张表 | "
                f"共 {col_count} 列 | "
                f"结果 {result_count} 条"
            )
            if mode == "distinct" and dedup_count > 0:
                summary += f" | 去重删除 {dedup_count} 条"

            return ToolResult.success(
                data={"records": records},
                summary=summary,
                data_shape="table",
                record_count=result_count,
            )
        except Exception as e:
            logger.error("[DataTransform.union] 执行失败: {}", e)
            return ToolResult.error(f"union 失败: {e}")

    # ──────────────────────────────────────────────────────────────
    #  map_dimension — 维度映射（编码 → 业务名称）
    # ──────────────────────────────────────────────────────────────
    async def _execute_map_dimension(
        self, kwargs: dict, config: dict, conversation_id: str | None
    ) -> dict:
        """维度映射：将主表中的编码字段通过映射表替换为业务含义描述。"""
        # 解析主表（支持 source_ref / source_data）
        source_ref: str | None = kwargs.get("source_ref")
        if source_ref:
            main_data, err = self._resolve_ref(source_ref, conversation_id)
            if err:
                return ToolResult.error(err)
        else:
            main_data = kwargs.get("source_data")
            if main_data is None:
                return ToolResult.error(
                    "map_dimension 需要主表数据，请通过 source_ref 或 source_data 提供"
                )

        # 解析映射表
        map_source_ref: str | None = config.get("map_source_ref")
        if map_source_ref:
            map_data, err = self._resolve_ref(map_source_ref, conversation_id)
            if err:
                return ToolResult.error(f"映射表引用失败: {err}")
        else:
            map_data = config.get("map_source")
            if map_data is None:
                return ToolResult.error(
                    "map_dimension 需要映射表数据，"
                    "请通过 config.map_source_ref 或 config.map_source 提供"
                )

        # 必填配置项
        key_field: str = config.get("key_field", "")
        map_key_field: str = config.get("map_key_field", "")
        map_value_field: str = config.get("map_value_field", "")
        if not key_field or not map_key_field or not map_value_field:
            return ToolResult.error(
                "map_dimension 需要 config 中指定: key_field, map_key_field, map_value_field"
            )

        output_field: str = config.get("output_field", key_field)
        keep_unmapped: bool = config.get("keep_unmapped", True)

        try:
            main_df = self._to_df(main_data)
            map_df = self._to_df(map_data)

            if key_field not in main_df.columns:
                return ToolResult.error(
                    f"主表中不存在字段 '{key_field}'，"
                    f"可用字段: {list(main_df.columns)}"
                )
            if map_key_field not in map_df.columns:
                return ToolResult.error(
                    f"映射表中不存在键字段 '{map_key_field}'，"
                    f"可用字段: {list(map_df.columns)}"
                )
            if map_value_field not in map_df.columns:
                return ToolResult.error(
                    f"映射表中不存在值字段 '{map_value_field}'，"
                    f"可用字段: {list(map_df.columns)}"
                )

            # 去重构建映射字典（取第一条）
            mapping_dict: dict = (
                map_df.drop_duplicates(subset=[map_key_field])
                .set_index(map_key_field)[map_value_field]
                .to_dict()
            )

            mapped_series = main_df[key_field].map(mapping_dict)
            hit_count = mapped_series.notna().sum()
            total_count = len(main_df)
            hit_rate = round(hit_count / total_count * 100, 1) if total_count else 0

            # 未命中处理
            if keep_unmapped:
                main_df[output_field] = mapped_series.fillna(main_df[key_field])
            else:
                main_df[output_field] = mapped_series

            records = self._df_to_records(main_df)

            summary = (
                f"维度映射完成 | "
                f"{key_field} → {output_field} | "
                f"命中率 {hit_rate}%（{hit_count}/{total_count} 条）"
            )
            if hit_rate < 100:
                missed = total_count - hit_count
                action_desc = "保留原值" if keep_unmapped else "置为空"
                summary += f" | 未命中 {missed} 条（{action_desc}）"

            return ToolResult.success(
                data={"records": records},
                summary=summary,
                data_shape="table",
                record_count=len(records),
            )
        except Exception as e:
            logger.error("[DataTransform.map_dimension] 执行失败: {}", e)
            return ToolResult.error(f"map_dimension 失败: {e}")

    @staticmethod
    def _df_to_records(df: pd.DataFrame) -> list[dict]:
        """将 DataFrame 转为可序列化的 records"""
        records = df.reset_index(drop=True).to_dict(orient="records")
        for rec in records:
            for k, v in rec.items():
                if isinstance(v, (pd.Timestamp, datetime)):
                    rec[k] = v.strftime("%Y-%m-%d")
                elif isinstance(v, (np.floating, np.integer)):
                    rec[k] = float(v)
                elif isinstance(v, np.bool_):
                    rec[k] = bool(v)
        return records

    def _merge(self, source_data: Any, config: dict) -> dict:
        right_data = config.get("right_data")
        if not right_data:
            return ToolResult.error("merge 需要 config.right_data")

        join_key: str = config.get("join_key", "")
        join_type: str = config.get("join_type", "left")

        if not join_key:
            return ToolResult.error("merge 需要 config.join_key")

        left_df = self._to_df(source_data)
        right_df = self._to_df(right_data)

        merged = left_df.merge(right_df, on=join_key, how=join_type)
        records = self._df_to_records(merged)

        return ToolResult.success(
            data={"records": records},
            summary=f"关联完成({join_type})，join_key={join_key}，结果 {len(records)} 条",
            data_shape="records",
            record_count=len(records),
        )

    def _filter(self, source_data: Any, config: dict) -> dict:
        conditions: list[dict] = config.get("conditions", [])
        df = self._to_df(source_data)

        if not conditions:
            return ToolResult.error("filter 需要 config.conditions")

        _OP_MAP = {
            "eq": lambda s, v: s == v,
            "ne": lambda s, v: s != v,
            "gt": lambda s, v: s > v,
            "gte": lambda s, v: s >= v,
            "lt": lambda s, v: s < v,
            "lte": lambda s, v: s <= v,
            "in": lambda s, v: s.isin(v),
            "not_in": lambda s, v: ~s.isin(v),
            "contains": lambda s, v: s.astype(str).str.contains(str(v), na=False),
        }

        for cond in conditions:
            field: str = cond.get("field", "")
            op: str = cond.get("op", "eq")
            value = cond.get("value")

            if field not in df.columns:
                continue

            op_func = _OP_MAP.get(op)
            if op_func is None:
                continue
            mask = op_func(df[field], value)
            df = df[mask]

        records = self._df_to_records(df)
        return ToolResult.success(
            data={"records": records},
            summary=f"过滤完成，{len(conditions)} 个条件，结果 {len(records)} 条",
            data_shape="records",
            record_count=len(records),
        )

    def _resample(self, source_data: Any, config: dict) -> dict:
        date_column: str = config.get("date_column", "date")
        frequency: str = config.get("frequency", "M")
        agg_method: str = config.get("agg_method", "mean")

        freq_map = {"W": "W", "M": "ME", "Q": "QE", "Y": "YE"}
        rule = freq_map.get(frequency.upper(), frequency)

        df = self._to_df(source_data)
        if date_column not in df.columns:
            return ToolResult.error(f"日期列 '{date_column}' 不存在")

        df[date_column] = pd.to_datetime(df[date_column])
        df = df.set_index(date_column).sort_index()

        numeric_df = df.select_dtypes(include=[np.number])
        agg_map = {"mean": "mean", "sum": "sum", "last": "last", "first": "first"}
        agg_func = agg_map.get(agg_method, "mean")

        resampled = numeric_df.resample(rule).agg(agg_func)
        resampled = resampled.dropna(how="all")

        records = self._df_to_records(resampled.reset_index())
        return ToolResult.success(
            data={"records": records},
            summary=f"重采样完成: {frequency}频率, {agg_method}聚合, {len(records)} 条",
            data_shape="records",
            record_count=len(records),
        )

    def _pivot(self, source_data: Any, config: dict) -> dict:
        index_col: str | list = config.get("index", "")
        columns_col: str = config.get("columns", "")
        values_col: str | list = config.get("values", "")
        aggfunc: str = config.get("aggfunc", "mean")

        if not index_col or not values_col:
            return ToolResult.error("pivot 需要 config.index 和 config.values")

        df = self._to_df(source_data)
        pivot_df = pd.pivot_table(
            df,
            index=index_col,
            columns=columns_col if columns_col else None,
            values=values_col,
            aggfunc=aggfunc,
        )

        # 展平多层列名
        if isinstance(pivot_df.columns, pd.MultiIndex):
            pivot_df.columns = ["_".join(str(c) for c in col).strip("_")
                                for col in pivot_df.columns]

        records = self._df_to_records(pivot_df.reset_index())
        return ToolResult.success(
            data={"records": records},
            summary=f"透视完成: index={index_col}, aggfunc={aggfunc}, {len(records)} 条",
            data_shape="records",
            record_count=len(records),
        )

    def _normalize(self, source_data: Any, config: dict) -> dict:
        mapping: dict = config.get("mapping", {})
        fill_value = config.get("fill_value")
        date_format: str = config.get("date_format", "")

        df = self._to_df(source_data)

        # 列重命名
        if mapping:
            df = df.rename(columns=mapping)

        # 缺失值填充
        if fill_value is not None:
            df = df.fillna(fill_value)

        # 日期格式转换
        if date_format:
            for col in df.columns:
                try:
                    parsed = pd.to_datetime(df[col], errors="coerce")
                    if parsed.notna().sum() > len(df) * 0.5:
                        df[col] = parsed.dt.strftime(date_format)
                except (TypeError, ValueError):
                    continue

        records = self._df_to_records(df)
        return ToolResult.success(
            data={"records": records},
            summary=f"标准化完成: 映射{len(mapping)}列, 填充={fill_value is not None}, {len(records)} 条",
            data_shape="records",
            record_count=len(records),
        )
