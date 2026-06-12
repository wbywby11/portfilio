"""
数据导入模板配置

定义系统预置的数据更新快捷模板，供Agent对话和前端模板面板使用。
每个模板描述了一种数据导入场景的元信息，包括：
- 导入类型标识
- UI展示信息（名称、图标、描述）
- 数据格式要求（必填/可选字段、接受的文件格式）
- Agent提示文本
"""

from __future__ import annotations

from typing import List, Dict, Any


DATA_IMPORT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "price_import",
        "name": "导入资产行情数据",
        "icon": "el-icon-data-line",
        "description": "上传Excel文件导入资产日频K线行情（开高低收量额规模）",
        "prompt_hint": "请上传行情Excel文件，需包含日期和收盘价列。我会帮您校验数据格式并导入系统。",
        "import_type": "price",
        "required_fields": ["日期/date", "收盘价/close"],
        "optional_fields": [
            "开盘价/open",
            "最高价/high",
            "最低价/low",
            "成交量/volume",
            "成交额/amount",
            "规模/scale",
        ],
        "accepted_formats": [".xlsx", ".xls", ".csv"],
        "import_modes": ["overwrite", "append", "only_missing"],
        "mode_descriptions": {
            "overwrite": "覆盖：清空该资产已有行情后全量写入",
            "append": "新增：仅插入系统中不存在的日期数据",
            "only_missing": "填补：仅补充已有日期中的缺失字段",
        },
    },
    {
        "id": "fx_import",
        "name": "导入汇率数据",
        "icon": "el-icon-money",
        "description": "上传汇率Excel更新EUR/USD/HKD/CNH对人民币汇率",
        "prompt_hint": "请上传汇率Excel文件，需包含日期列和至少一个币种汇率列（EUR/USD/HKD/CNH）。",
        "import_type": "fx",
        "required_fields": ["日期/date"],
        "optional_fields": ["EUR", "USD", "HKD", "CNH"],
        "accepted_formats": [".xlsx", ".xls", ".csv"],
        "import_modes": ["replace", "incremental"],
        "mode_descriptions": {
            "replace": "替换：清空全部汇率数据后写入文件内容",
            "incremental": "增量：仅填补缺失日期与空字段，不覆盖已有数据",
        },
    },
    {
        "id": "asset_info_import",
        "name": "导入资产基础信息",
        "icon": "el-icon-folder-add",
        "description": "批量导入资产代码、名称、类型等基础信息",
        "prompt_hint": "请上传资产信息Excel，需包含资产代码和名称列。可选列：类型、交易所、货币等。",
        "import_type": "asset_info",
        "required_fields": ["代码/code", "名称/name"],
        "optional_fields": [
            "类型/type",
            "交易所/exchange",
            "货币/currency",
            "描述/description",
        ],
        "accepted_formats": [".xlsx", ".xls", ".csv"],
        "import_modes": ["append", "overwrite"],
        "mode_descriptions": {
            "append": "新增：仅导入系统中不存在的资产",
            "overwrite": "覆盖：已存在的资产信息将被文件内容覆盖",
        },
    },
    {
        "id": "multi_asset_price",
        "name": "导入多资产宽表行情",
        "icon": "el-icon-s-grid",
        "description": "通过宽表格式（第一列日期，后续列为资产代码）批量导入多只资产行情",
        "prompt_hint": "请上传多资产宽表Excel，第一列为日期，后续列标题为资产代码，单元格为对应指标值。",
        "import_type": "multi_asset",
        "required_fields": ["日期列（第一列）", "至少一个资产代码列"],
        "optional_fields": [],
        "accepted_formats": [".xlsx", ".xls"],
        "import_modes": ["append", "overwrite"],
        "mode_descriptions": {
            "append": "新增：仅插入不存在的日期行情",
            "overwrite": "覆盖：清空相关资产已有行情后写入",
        },
        "extra_params": {
            "metric": {
                "description": "宽表数值对应的行情字段",
                "options": ["close", "open", "high", "low", "volume", "amount", "scale"],
                "default": "close",
            }
        },
    },
    {
        "id": "api_sync",
        "name": "同步API数据源",
        "icon": "el-icon-refresh",
        "description": "触发已配置的上游API数据拉取同步到本地",
        "prompt_hint": "请告诉我要同步哪个数据源，我可以列出所有可用的API数据源供您选择。",
        "import_type": "api_sync",
        "required_fields": [],
        "optional_fields": [],
        "accepted_formats": [],
        "import_modes": [],
        "mode_descriptions": {},
    },
    {
        "id": "trade_dates_import",
        "name": "导入交易日历",
        "icon": "el-icon-date",
        "description": "上传交易日历Excel更新系统交易日数据",
        "prompt_hint": "请上传交易日历Excel文件，需包含交易日期列。我会帮您校验格式并导入系统。",
        "import_type": "trade_dates",
        "required_fields": ["交易日期/trade_dates/date"],
        "optional_fields": [],
        "accepted_formats": [".xlsx", ".xls", ".csv"],
        "import_modes": ["incremental", "replace"],
        "mode_descriptions": {
            "incremental": "增量：仅新增系统中不存在的交易日",
            "replace": "替换：清空全部交易日历后写入文件内容",
        },
    },
    {
        "id": "data_clean",
        "name": "数据清洗与修复",
        "icon": "el-icon-brush",
        "description": "检查并修复指定资产或集合中的数据异常值、缺失值",
        "prompt_hint": "请告诉我要检查哪个资产或集合的数据质量，我会分析异常值和缺失情况并提供修复建议。",
        "import_type": "data_clean",
        "required_fields": [],
        "optional_fields": [],
        "accepted_formats": [],
        "import_modes": [],
        "mode_descriptions": {},
    },
]


def get_template_by_id(template_id: str) -> Dict[str, Any] | None:
    """根据ID获取模板"""
    for t in DATA_IMPORT_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


def get_templates_by_type(import_type: str) -> List[Dict[str, Any]]:
    """根据导入类型获取模板"""
    return [t for t in DATA_IMPORT_TEMPLATES if t["import_type"] == import_type]


def get_all_templates_summary() -> List[Dict[str, str]]:
    """获取所有模板的摘要信息（供前端展示）"""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "icon": t["icon"],
            "description": t["description"],
            "prompt_hint": t["prompt_hint"],
            "import_type": t["import_type"],
            "accepted_formats": t["accepted_formats"],
        }
        for t in DATA_IMPORT_TEMPLATES
    ]
