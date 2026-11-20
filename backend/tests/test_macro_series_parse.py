"""macro_series 导入解析单测（纯函数，不连库）

覆盖：宽表/长表自动识别、序列代码规范化、序列说明表（类型/单位/来源、非法类型
回退）、同文件重复、空值与非数字区分、负值保留、模板结构。
"""
import pandas as pd
import pytest

from app.services.macro_series_service import MacroSeriesService


def _wide() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2024-01-02", "2024-01-03", "bad-date"],
            "H00922_PE": [17.85, 17.91, 18.0],
            "cba_10y": [2.56, None, 2.57],
            "空列": [None, None, None],
        }
    )


class TestWideFormat:
    def test_records_and_codes(self):
        records, report = MacroSeriesService.parse_dataframe(_wide())
        # 第三行日期不可解析 → H00922_PE / cba_10y 各少一条，空列全空
        assert len(records) == 3
        assert report["codes"] == ["CBA_10Y", "H00922_PE"]
        assert report["format"] == "wide"

    def test_code_uppercased(self):
        records, _ = MacroSeriesService.parse_dataframe(_wide())
        assert {r["code"] for r in records} == {"CBA_10Y", "H00922_PE"}

    def test_bad_date_counted(self):
        _, report = MacroSeriesService.parse_dataframe(_wide())
        assert report["skipped"]["bad_date"] == 1

    def test_empty_cell_not_counted_as_error(self):
        """空单元格是「该序列该日无数据」，不计入 bad_value。"""
        _, report = MacroSeriesService.parse_dataframe(_wide())
        assert report["skipped"]["bad_value"] == 0
        assert report["skipped"]["empty_cell"] == 3

    def test_first_column_without_name_used_as_date(self):
        df = pd.DataFrame({"Unnamed: 0": ["2024-01-02"], "X": [1.0]})
        records, _ = MacroSeriesService.parse_dataframe(df)
        assert records[0]["date"] == "2024-01-02"
        assert records[0]["code"] == "X"


class TestMetaSheet:
    def test_meta_applied(self):
        meta = pd.DataFrame(
            {
                "序列代码": ["h00922_pe"],
                "序列类型": ["valuation"],
                "单位": ["倍"],
                "来源": ["中证指数"],
            }
        )
        records, report = MacroSeriesService.parse_dataframe(_wide(), meta_df=meta)
        pe = next(r for r in records if r["code"] == "H00922_PE")
        assert pe["series_type"] == "valuation"
        assert pe["unit"] == "倍"
        assert pe["source"] == "中证指数"
        assert report["meta_applied"] == 2  # PE 两条日期

    def test_unlisted_series_falls_back_to_other(self):
        meta = pd.DataFrame({"序列代码": ["H00922_PE"], "序列类型": ["valuation"]})
        records, report = MacroSeriesService.parse_dataframe(_wide(), meta_df=meta)
        cba = next(r for r in records if r["code"] == "CBA_10Y")
        assert cba["series_type"] == "other"
        assert any("未在序列说明表中登记" in w for w in report["warnings"])

    def test_invalid_type_falls_back_with_warning(self):
        meta = pd.DataFrame({"序列代码": ["H00922_PE"], "序列类型": ["估值"]})
        _, report = MacroSeriesService.parse_dataframe(_wide(), meta_df=meta)
        assert any("不在受控词表内" in w for w in report["warnings"])

    def test_meta_without_code_column_warns(self):
        meta = pd.DataFrame({"类型": ["valuation"]})
        _, report = MacroSeriesService.parse_dataframe(_wide(), meta_df=meta)
        assert any("缺少「序列代码」列" in w for w in report["warnings"])


class TestLongFormat:
    def test_detected_and_parsed(self):
        df = pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-02"],
                "序列代码": ["CBA_10Y", "H00922_PE"],
                "数值": [2.56, 17.85],
                "序列类型": ["bond_yield", "valuation"],
            }
        )
        records, report = MacroSeriesService.parse_dataframe(df)
        assert report["format"] == "long"
        assert len(records) == 2
        types = {r["code"]: r["series_type"] for r in records}
        assert types == {"CBA_10Y": "bond_yield", "H00922_PE": "valuation"}

    def test_duplicate_key_keeps_last(self):
        df = pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-02"],
                "序列代码": ["CBA_10Y", "CBA_10Y"],
                "数值": [2.56, 9.99],
            }
        )
        records, report = MacroSeriesService.parse_dataframe(df)
        assert report["duplicates"] == 1
        assert len(records) == 1
        assert records[0]["value"] == 9.99

    def test_missing_date_column_raises(self):
        df = pd.DataFrame({"序列代码": ["A"], "数值": [1.0]})
        with pytest.raises(ValueError, match="长表中未找到日期列"):
            MacroSeriesService.parse_dataframe(df)


class TestValueRange:
    def test_negative_value_kept(self):
        """PB / 信用利差 / ERP 分量可以为负，不能照搬 fx 的「必须大于 0」。"""
        df = pd.DataFrame({"日期": ["2024-01-02"], "SPREAD": [-0.35]})
        records, _ = MacroSeriesService.parse_dataframe(df)
        assert records[0]["value"] == -0.35

    def test_zero_value_kept(self):
        df = pd.DataFrame({"日期": ["2024-01-02"], "X": [0.0]})
        records, _ = MacroSeriesService.parse_dataframe(df)
        assert records[0]["value"] == 0.0

    def test_non_numeric_cell_counted(self):
        df = pd.DataFrame({"日期": ["2024-01-02"], "X": ["N/A"]})
        with pytest.raises(ValueError, match="未解析出任何有效记录"):
            MacroSeriesService.parse_dataframe(df)


class TestErrors:
    def test_empty_dataframe(self):
        with pytest.raises(ValueError, match="数据表为空"):
            MacroSeriesService.parse_dataframe(pd.DataFrame())

    def test_no_series_column(self):
        with pytest.raises(ValueError, match="未找到序列列"):
            MacroSeriesService.parse_dataframe(pd.DataFrame({"日期": ["2024-01-02"]}))


class TestNormalizeCode:
    @pytest.mark.parametrize(
        "raw,expect",
        [
            (" h00922_pe ", "H00922_PE"),
            ("CBA_10Y", "CBA_10Y"),
            (None, ""),
            ("", ""),
        ],
    )
    def test_normalize(self, raw, expect):
        assert MacroSeriesService.normalize_code(raw) == expect


class TestTemplate:
    def test_two_sheets(self):
        buf, filename = MacroSeriesService.build_template()
        assert filename.endswith(".xlsx")
        sheets = pd.read_excel(buf, sheet_name=None)
        assert list(sheets) == ["数据", "序列说明"]
        assert "日期" in sheets["数据"].columns
        assert set(sheets["序列说明"].columns) == {"序列代码", "序列类型", "单位", "来源"}
