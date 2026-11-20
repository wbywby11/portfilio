"""因子数据集登记的覆盖性单测（不连库）

校验 field_mappings 的三个 per-dataset 表与 factor_panel_templates 的模板登记
保持同步 —— 新增数据集时漏登记任意一处，都要在测试里立刻暴露，而不是等到
用户点「下载模板」或导入后因子键对不上才发现。
"""
import io

import pandas as pd
import pytest

from app.schemas.field_mappings import (
    FACTOR_CATEGORICAL_KEYS_BY_DATASET,
    FACTOR_DATASETS,
    FACTOR_NAME_MAPPING_BY_DATASET,
    FACTOR_PANEL_REQUIRED_FIELDS,
    categorical_factor_keys_for,
    factor_name_mapping_for,
)
from app.services.factor_panel_importer import FactorPanelImporterMixin
from app.services.factor_panel_templates import (
    TEMPLATE_COLUMNS_BY_DATASET,
    build_factor_panel_template,
)


def test_every_dataset_has_three_tables():
    for dataset in FACTOR_DATASETS:
        assert dataset in FACTOR_NAME_MAPPING_BY_DATASET, f"{dataset} 缺名称映射"
        assert dataset in FACTOR_CATEGORICAL_KEYS_BY_DATASET, f"{dataset} 缺类别键登记"


def test_no_orphan_registration():
    known = set(FACTOR_DATASETS)
    assert set(FACTOR_NAME_MAPPING_BY_DATASET) <= known
    assert set(FACTOR_CATEGORICAL_KEYS_BY_DATASET) <= known
    assert set(TEMPLATE_COLUMNS_BY_DATASET) <= known


def test_index_enhance_stock_registered():
    dataset = "index_enhance_stock"
    assert dataset in FACTOR_DATASETS
    mapping = factor_name_mapping_for(dataset)
    assert mapping.get("PB") == "pb"
    assert mapping.get("市净率") == "pb"
    assert mapping.get("月末收盘价") == "close"
    # 行业与简称走固定列（FACTOR_PANEL_REQUIRED_FIELDS 已含 industry），不是类别因子
    assert categorical_factor_keys_for(dataset) == frozenset()
    assert "industry" in FACTOR_PANEL_REQUIRED_FIELDS


def test_template_columns_parse_into_expected_factor_keys():
    dataset = "index_enhance_stock"
    buf, filename = build_factor_panel_template(dataset)
    assert filename == f"factor_panel_import_template_{dataset}.xlsx"
    sheets = pd.read_excel(buf, sheet_name=None)
    columns = list(sheets["因子截面数据"].columns)
    assert columns == [
        "日期*", "因子取数日", "代码*", "简称", "行业*", "PB", "月末收盘价",
    ]

    df = pd.DataFrame(
        [["2024-01-31", "2024-01-31", "600926.SH", "杭州银行", "银行", 0.72, 10.35]],
        columns=columns,
    )
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="因子截面数据")

    mixin = FactorPanelImporterMixin()
    mapping = factor_name_mapping_for(dataset)
    frame, fixed, factor_cols, unmapped = mixin._parse_frame(
        bio.getvalue(), mapping, None
    )
    assert sorted(fixed) == ["as_of_date", "code", "data_date", "industry", "name"]
    assert factor_cols == ["PB", "月末收盘价"]
    assert unmapped == []

    docs, errors = mixin._build_documents(
        frame, fixed, factor_cols, dataset, mapping
    )[:2]
    assert errors == []
    assert len(docs) == 1
    doc = docs[0]
    assert doc["dataset"] == dataset
    assert doc["industry"] == "银行"
    assert doc["name"] == "杭州银行"
    assert sorted(doc["factors"]) == ["close", "pb"]
    assert float(doc["factors"]["pb"]) == pytest.approx(0.72)
    assert float(doc["factors"]["close"]) == pytest.approx(10.35)
