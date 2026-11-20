# -*- coding: utf-8 -*-
"""factor_panel 的 dataset 维度隔离测试（全程不触真库）.

factor_panel 集合被多个数据产品共用，dataset 是它们之间唯一的隔板。
任何一层漏掉 dataset 都是**静默**故障，不会报错、只会算错：

  加载层漏 → 两个数据集同期日的行并进同一截面，名次打分分母 N 被污染；
  写入层漏 → upsert 跨数据集覆盖同 (期日, 代码) 的行，replace 按期日整片误删；
  映射层漏 → 中文列名共用一张扁平表，同名列在两个数据集里互相覆盖键；
  声明层漏 → 策略没说读哪个数据集，加载器无从过滤。

本模块逐层钉住这四个口子，另附两条与 dataset 同期落地的口径：
类别因子（文本）必须显式登记，成分快照期按「整期」定性。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pandas as pd
import pytest

from app.backtesting import data_feed
from app.schemas.field_mappings import (
    FACTOR_CATEGORICAL_KEYS_BY_DATASET,
    FACTOR_DATASETS,
    FACTOR_NAME_MAPPING,
    FACTOR_NAME_MAPPING_BY_DATASET,
    FACTOR_PANEL_COLUMN_MAPPING,
    _merge_factor_name_mappings,
    categorical_factor_keys_for,
    factor_name_mapping_for,
)
from app.schemas.import_protocol import ImportMode
from app.services.factor_panel_service import FactorPanelService
from app.services.factor_panel_templates import (
    DATA_SHEET_NAME,
    TEMPLATE_COLUMNS_BY_DATASET,
    build_factor_panel_template,
    template_spec_for,
)

BOND = "bond_phoenix50"
EQUITY = "equity_quality_growth"
INDEX_ENHANCE_STOCK = "index_enhance_stock"
PERIOD = "2026-09-30"


def _run(coro):
    """本仓未装 pytest-asyncio，协程统一用 asyncio.run 驱动."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 替身：内存 collection，记录每次调用的 query 以便断言过滤条件
# ---------------------------------------------------------------------------


class _Cursor:
    """同时支持 to_list() 与 async for——两个调用方口径不同."""

    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    """按 query 的等值/$in 条件过滤内存文档，并把 query 原样留档."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.queries: list = []

    def _match(self, query):
        hit = []
        for doc in self.docs:
            ok = True
            for field, cond in query.items():
                if isinstance(cond, dict) and "$in" in cond:
                    ok = ok and doc.get(field) in cond["$in"]
                else:
                    ok = ok and doc.get(field) == cond
            if ok:
                hit.append(doc)
        return hit

    def find(self, query, projection=None):
        self.queries.append(("find", query))
        return _Cursor(self._match(query))

    async def delete_many(self, query):
        self.queries.append(("delete_many", query))
        hit = self._match(query)
        self.docs = [d for d in self.docs if d not in hit]
        return SimpleNamespace(deleted_count=len(hit))

    async def insert_many(self, docs, ordered=True):
        self.queries.append(("insert_many", [dict(d) for d in docs]))
        self.docs.extend(dict(d) for d in docs)
        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    async def bulk_write(self, ops, ordered=True):
        # pymongo UpdateOne 的过滤条件存在 _filter；此处只为断言其含 dataset
        self.queries.append(("bulk_write", [op._filter for op in ops]))
        return SimpleNamespace(upserted_count=len(ops), modified_count=0)

    def ops_of(self, op_name):
        return [payload for name, payload in self.queries if name == op_name]

    def filters_of(self, op_name):
        return [q for name, q in self.queries if name == op_name]


class _Db:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        return self._collection


def _service(coll) -> FactorPanelService:
    """注入假 db 的服务实例（不走 Database.get_database，故不需要 MongoDB）."""
    return FactorPanelService(db=_Db(coll))


def _doc(dataset, code, period=PERIOD, **factors):
    return {
        "dataset": dataset, "as_of_date": period, "code": code,
        "industry": "其它信用债", "factors": dict(factors),
    }


# ---------------------------------------------------------------------------
# 映射层：受控清单 + 按 dataset 分组的列名映射
# ---------------------------------------------------------------------------


class TestDatasetRegistry:
    def test_registry_holds_both_products(self):
        assert set(FACTOR_DATASETS) == {BOND, EQUITY, INDEX_ENHANCE_STOCK}

    def test_every_dataset_is_named_after_product_not_strategy(self):
        """命名口径：按数据产品/指数命名，同一份数据可被多个策略共用."""
        for name in FACTOR_DATASETS:
            assert "strategy" not in name and "策略" not in FACTOR_DATASETS[name]

    def test_unknown_dataset_rejected_with_options(self):
        with pytest.raises(ValueError, match="未知的因子数据集"):
            factor_name_mapping_for("bond_phoenix_50")  # 少个下划线也不行
        with pytest.raises(ValueError, match="未知的因子数据集"):
            categorical_factor_keys_for("")

    def test_error_message_lists_valid_options(self):
        with pytest.raises(ValueError) as exc:
            factor_name_mapping_for("nope")
        for name in FACTOR_DATASETS:
            assert name in str(exc.value)


class TestNameMappingByDataset:
    def test_bond_and_equity_map_their_own_columns(self):
        assert factor_name_mapping_for(BOND)["债务主体"] == "issuer"
        assert factor_name_mapping_for(EQUITY)["扣非PE"] == "pe_ttm_dn"

    def test_mappings_do_not_leak_across_datasets(self):
        """债券表里没有股票因子，反之亦然——共用扁平表就会串味."""
        assert "扣非PE" not in factor_name_mapping_for(BOND)
        assert "债务主体" not in factor_name_mapping_for(EQUITY)

    def test_fallback_union_covers_both_groups(self):
        for group in FACTOR_NAME_MAPPING_BY_DATASET.values():
            for column, key in group.items():
                assert FACTOR_NAME_MAPPING[column] == key

    def test_conflicting_column_across_datasets_fails_fast(self, monkeypatch):
        """同名列映射到不同键 → 兜底并集不成立，构建时即报错（不等运行期静默覆盖）."""
        monkeypatch.setitem(FACTOR_NAME_MAPPING_BY_DATASET, "ds_a", {"规模": "size_a"})
        monkeypatch.setitem(FACTOR_NAME_MAPPING_BY_DATASET, "ds_b", {"规模": "size_b"})
        with pytest.raises(ValueError, match="冲突"):
            _merge_factor_name_mappings()

    def test_registered_categorical_keys_are_reachable_columns(self):
        """登记的类别因子键必须能由该数据集的某个列名映射出来，否则永远填不进值."""
        for dataset, keys in FACTOR_CATEGORICAL_KEYS_BY_DATASET.items():
            mapped = set(factor_name_mapping_for(dataset).values())
            assert keys <= mapped, f"{dataset} 的类别因子 {keys - mapped} 无对应列名"

    def test_bond_issuer_is_categorical_and_equity_has_none(self):
        assert categorical_factor_keys_for(BOND) == frozenset({"issuer"})
        assert categorical_factor_keys_for(EQUITY) == frozenset()


# ---------------------------------------------------------------------------
# 模板层：按 dataset 出不同因子列
# ---------------------------------------------------------------------------


class TestTemplateByDataset:
    def test_registry_and_template_columns_are_in_sync(self):
        assert set(TEMPLATE_COLUMNS_BY_DATASET) == set(FACTOR_DATASETS)

    def test_two_datasets_get_different_factor_columns(self):
        bond, equity = TEMPLATE_COLUMNS_BY_DATASET[BOND], TEMPLATE_COLUMNS_BY_DATASET[EQUITY]
        assert bond != equity
        assert "债务主体" in bond and "债务主体" not in equity
        assert "扣非PE" in equity and "扣非PE" not in bond

    def test_bond_template_has_no_market_value_column(self):
        """债券等权 1/N，不需要市值列；留着会诱导填无意义的值."""
        assert not [c for c in TEMPLATE_COLUMNS_BY_DATASET[BOND] if "市值" in c]

    def test_every_template_keeps_the_three_required_columns(self):
        for dataset, columns in TEMPLATE_COLUMNS_BY_DATASET.items():
            for required in ("日期*", "代码*"):
                assert required in columns, f"{dataset} 缺必填列 {required}"
            assert any(c.endswith("*") and c not in ("日期*", "代码*") for c in columns), (
                f"{dataset} 缺分组列（industry 必填）"
            )

    def test_both_group_column_names_map_to_industry(self):
        """债券叫「券池*」、股票叫「行业*」，但落到同一个 industry 字段.

        两个模板共用一个存储字段是设计意图（分组限额逻辑不分市场），
        但列名必须都在映射表里：漏一个就会让该数据集的文件报「缺少必填列」。
        """
        assert FACTOR_PANEL_COLUMN_MAPPING["券池*"] == "industry"
        assert FACTOR_PANEL_COLUMN_MAPPING["行业*"] == "industry"

    def test_unknown_dataset_rejected(self):
        with pytest.raises(ValueError):
            template_spec_for("nope")

    def test_built_workbook_is_readable_and_named_after_dataset(self):
        blob, filename = build_factor_panel_template(BOND)
        assert filename == f"factor_panel_import_template_{BOND}.xlsx"
        book = pd.ExcelFile(blob)
        assert DATA_SHEET_NAME in book.sheet_names
        frame = pd.read_excel(book, sheet_name=DATA_SHEET_NAME)
        assert list(frame.columns) == TEMPLATE_COLUMNS_BY_DATASET[BOND]
        assert len(frame) >= 1, "模板须带示例行，否则单位与量级无从参照"


# ---------------------------------------------------------------------------
# 服务层：dataset 参数校验
# ---------------------------------------------------------------------------


class TestServiceDatasetResolve:
    @pytest.mark.parametrize("bad", [None, "", "   ", "bond_phoenix", EQUITY.upper()])
    def test_blank_or_unlisted_dataset_rejected(self, bad):
        with pytest.raises(ValueError):
            FactorPanelService._resolve_dataset(bad)

    def test_valid_dataset_passes_through(self):
        assert FactorPanelService._resolve_dataset(f" {BOND} ") == BOND

    def test_unsupported_mode_rejected_not_silently_downgraded(self):
        with pytest.raises(ValueError):
            FactorPanelService._resolve_mode("merge")
        assert FactorPanelService._resolve_mode("UPSERT") is ImportMode.UPSERT


# ---------------------------------------------------------------------------
# 加载层：按 dataset 过滤 + 缺声明即报错
# ---------------------------------------------------------------------------


def _patch_db(monkeypatch, coll):
    monkeypatch.setattr(
        "app.config.database.Database.get_database",
        staticmethod(lambda: _Db(coll)),
    )


class TestLoaderDatasetFilter:
    def test_empty_dataset_raises_instead_of_full_scan(self, monkeypatch):
        coll = _Collection([_doc(BOND, "A"), _doc(EQUITY, "B")])
        _patch_db(monkeypatch, coll)
        with pytest.raises(ValueError, match="get_panel_datasets"):
            _run(data_feed._load_factor_panel(None, ""))
        assert coll.queries == [], "报错必须在查库之前，不得退化成全表加载"

    def test_only_rows_of_the_requested_dataset_are_loaded(self, monkeypatch):
        """两个数据集同一期日各一行：加载 bond 时 equity 那行不得混进截面."""
        coll = _Collection([
            _doc(BOND, "102681391.IB", issuer="浙江省能源集团", modified_duration=2.47),
            _doc(EQUITY, "600926.SH", pe_ttm_dn=6.47),
        ])
        _patch_db(monkeypatch, coll)
        panels = _run(data_feed._load_factor_panel(None, BOND))

        assert list(panels) == [pd.Timestamp(PERIOD)]
        frame = panels[pd.Timestamp(PERIOD)]
        assert list(frame.index) == ["102681391.IB"]
        assert frame.loc["102681391.IB", "issuer"] == "浙江省能源集团"
        assert "pe_ttm_dn" not in frame.columns, "另一数据集的因子键不得出现在本截面"
        assert coll.filters_of("find") == [{"dataset": BOND}]

    def test_unknown_dataset_yields_empty_panels(self, monkeypatch):
        coll = _Collection([_doc(BOND, "A")])
        _patch_db(monkeypatch, coll)
        assert _run(data_feed._load_factor_panel(None, "equity_quality_growth")) == {}

    def test_factor_panel_is_declared_dataset_scoped(self):
        assert "factor_panel" in data_feed.DATASET_SCOPED_PANELS
        assert "factor_panel" in data_feed.PANEL_LOADERS


class TestPanelDeclaration:
    def test_missing_strategy_type_raises(self):
        """缺策略码不得静默返回空面板：那会让依赖面板的策略在引擎首日才炸."""
        with pytest.raises(ValueError, match="缺少 strategy_type"):
            _run(data_feed.load_strategy_panels(None))

    def test_unregistered_strategy_raises(self):
        """未注册的策略码同样不得静默跳过面板加载."""
        with pytest.raises(ValueError, match="未在 STRATEGY_MANIFEST 注册"):
            _run(data_feed.load_strategy_panels("not_a_registered_code"))

    def test_scoped_panel_without_dataset_declaration_raises(self, monkeypatch):
        monkeypatch.setattr(
            data_feed, "_resolve_panel_declarations", lambda st: (["factor_panel"], {})
        )
        with pytest.raises(ValueError, match="未在 get_panel_datasets"):
            _run(data_feed.load_strategy_panels("whatever"))

    def test_unregistered_panel_name_raises(self, monkeypatch):
        monkeypatch.setattr(
            data_feed, "_resolve_panel_declarations", lambda st: (["fund_flow"], {})
        )
        with pytest.raises(ValueError, match="未注册的面板"):
            _run(data_feed.load_strategy_panels("whatever"))

    def test_declared_dataset_reaches_the_loader(self, monkeypatch):
        """端到端：策略声明 → 解析 → 加载器按该 dataset 过滤（监控通道 config=None）."""
        coll = _Collection([_doc(BOND, "A"), _doc(EQUITY, "B")])
        _patch_db(monkeypatch, coll)
        monkeypatch.setattr(
            data_feed, "_resolve_panel_declarations",
            lambda st: (["factor_panel"], {"factor_panel": BOND}),
        )
        panels, panel_dates = _run(data_feed.load_strategy_panels("whatever", None))

        assert list(panels["factor_panel"][pd.Timestamp(PERIOD)].index) == ["A"]
        assert panel_dates == {"factor_panel": [pd.Timestamp(PERIOD)]}

    def test_both_strategies_declare_their_own_listed_dataset(self):
        """两个策略读同一集合的不同 dataset——这正是引入 dataset 维度的动因."""
        from app.standalone_strategies.bond_factor_score_index.strategy import (
            BondFactorScoreIndexStrategy,
        )
        from app.standalone_strategies.factor_score_index.strategy import (
            FactorScoreIndexStrategy,
        )

        declared = {}
        for cls, expected in (
            (BondFactorScoreIndexStrategy, BOND),
            (FactorScoreIndexStrategy, EQUITY),
        ):
            mapping = cls.get_panel_datasets()
            assert mapping == {"factor_panel": expected}, f"{cls.__name__} 声明不符"
            assert expected in FACTOR_DATASETS, f"{cls.__name__} 声明了未登记的 dataset"
            assert "factor_panel" in cls.get_extra_panels(), (
                f"{cls.__name__} 只声明了 dataset 却未声明面板，加载层不会读它"
            )
            declared[cls.__name__] = expected

        assert len(set(declared.values())) == 2, "两个策略不得共用一个 dataset"


# ---------------------------------------------------------------------------
# 写入层：三种模式的库操作都必须带 dataset
# ---------------------------------------------------------------------------


class TestWriteDatasetFilter:
    def test_replace_deletes_only_within_the_dataset(self):
        """replace 按期日整片删：不带 dataset 会把另一数据集的同期日行一起删掉."""
        coll = _Collection([_doc(BOND, "A"), _doc(EQUITY, "A"), _doc(BOND, "B", "2026-06-30")])
        svc = _service(coll)
        inserted, updated, skipped = _run(
            svc._write([_doc(BOND, "A")], ImportMode.REPLACE, BOND, [PERIOD])
        )

        assert (inserted, updated, skipped) == (1, 0, 0)
        assert coll.filters_of("delete_many") == [
            {"dataset": BOND, "as_of_date": {"$in": [PERIOD]}}
        ]
        left = {(d["dataset"], d["code"], d["as_of_date"]) for d in coll.docs}
        assert (EQUITY, "A", PERIOD) in left, "另一数据集的同期日行必须原样保留"
        assert (BOND, "B", "2026-06-30") in left, "本数据集的其他期也必须原样保留"

    def test_upsert_key_is_the_triple(self):
        coll = _Collection()
        svc = _service(coll)
        result = _run(
            svc._write([_doc(BOND, "A"), _doc(EQUITY, "A")], ImportMode.UPSERT, BOND, [PERIOD])
        )

        # 调用方按 (inserted, updated, skipped_existing) 三元解包：upsert 分支
        # 漏返第三位会在真实导入时抛 ValueError，预演走不到这里所以测试不到
        assert result == (2, 0, 0), "upsert 分支必须与 replace/incremental 一样返回三元组"

        filters = coll.ops_of("bulk_write")[0]
        assert filters == [
            {"dataset": BOND, "as_of_date": PERIOD, "code": "A"},
            {"dataset": EQUITY, "as_of_date": PERIOD, "code": "A"},
        ], "同 (期日, 代码) 不同 dataset 是两行，过滤条件必须是三元"

    def test_incremental_existence_check_is_scoped(self):
        """equity 已有同 (期日, 代码) 不得让 bond 的同一行被判为「已存在」而跳过."""
        coll = _Collection([_doc(EQUITY, "A"), _doc(BOND, "B")])
        svc = _service(coll)
        inserted, updated, skipped = _run(
            svc._write([_doc(BOND, "A"), _doc(BOND, "B")], ImportMode.INCREMENTAL, BOND, [PERIOD])
        )

        assert (inserted, updated, skipped) == (1, 0, 1)
        assert coll.filters_of("find") == [
            {"dataset": BOND, "as_of_date": {"$in": [PERIOD]}}
        ]
        codes = sorted(d["code"] for d in coll.docs if d["dataset"] == BOND)
        assert codes == ["A", "B"]

    def test_empty_docs_short_circuits(self):
        coll = _Collection([_doc(BOND, "A")])
        svc = _service(coll)
        assert _run(svc._write([], ImportMode.REPLACE, BOND, [PERIOD])) == (0, 0, 0)
        assert coll.queries == [], "无文档不得触发任何库操作（尤其不得触发删除）"

    def test_index_definition_is_the_triple(self):
        """主键索引名与字段顺序：dataset 打头，旧的二元唯一索引必须先删."""
        svc = _service(_Collection())
        created: list = []
        dropped: list = []

        async def fake_create_index(keys, **kwargs):
            created.append((kwargs.get("name"), keys, kwargs.get("unique")))

        async def fake_drop_index(name):
            dropped.append(name)

        # collection 是只读 property（惰性从 db 取），故注入到它的缓存位 _collection
        svc._collection = SimpleNamespace(
            create_index=fake_create_index, drop_index=fake_drop_index
        )
        FactorPanelService._indexes_ready = False
        try:
            _run(svc.ensure_indexes())
        finally:
            FactorPanelService._indexes_ready = False

        assert ("uniq_dataset_period_code",
                [("dataset", 1), ("as_of_date", 1), ("code", 1)], True) in created
        assert set(dropped) >= {"uniq_period_code", "idx_code_period", "idx_period_industry"}, (
            "旧的二元唯一索引不删，两个数据集就无法存同 (期日, 代码)"
        )
        for name, keys, _ in created:
            assert keys[0][0] == "dataset", f"索引 {name} 未以 dataset 打头"


# ---------------------------------------------------------------------------
# 与 dataset 同期落地的两条口径
# ---------------------------------------------------------------------------


class TestSnapshotPeriodQualification:
    def test_whole_period_without_factors_is_kept_as_snapshot(self):
        docs = [_doc(BOND, "A"), _doc(BOND, "B")]
        kept, skipped = FactorPanelService._split_snapshot_periods(docs)
        assert len(kept) == 2 and skipped == 0

    def test_partially_empty_period_skips_only_the_blank_rows(self):
        """同期只有个别行无因子 = 漏填（不是快照期），跳过并计数."""
        docs = [_doc(BOND, "A", modified_duration=2.4), _doc(BOND, "B")]
        kept, skipped = FactorPanelService._split_snapshot_periods(docs)
        assert [d["code"] for d in kept] == ["A"] and skipped == 1

    def test_one_factor_column_flips_the_whole_period(self):
        """只要有一行带因子，整期就不再是快照期——故快照文件绝不能带因子列."""
        snapshot = [_doc(BOND, "A"), _doc(BOND, "B")]
        assert FactorPanelService._split_snapshot_periods(snapshot)[1] == 0
        polluted = [_doc(BOND, "A"), _doc(BOND, "B", issuer="某主体")]
        kept, skipped = FactorPanelService._split_snapshot_periods(polluted)
        assert skipped == 1 and len(kept) == 1

    def test_periods_are_qualified_independently(self):
        docs = [
            _doc(BOND, "A", "2026-06-30"),                       # 快照期
            _doc(BOND, "B", "2026-06-30"),
            _doc(BOND, "A", PERIOD, modified_duration=2.4),      # 打分期
            _doc(BOND, "B", PERIOD),                             # 打分期里的漏填行
        ]
        kept, skipped = FactorPanelService._split_snapshot_periods(docs)
        assert skipped == 1
        assert {(d["as_of_date"], d["code"]) for d in kept} == {
            ("2026-06-30", "A"), ("2026-06-30", "B"), (PERIOD, "A"),
        }


class TestRowFactorParsing:
    """因子双路解析：登记的类别键按文本保留，其余按数值解析."""

    def _parse(self, row: dict, dataset: str, factor_cols: list):
        """按真实链路口径推导 fixed（字段名 → 本文件里实际用的原列名）.

        不写死 fixed：分组列在债券模板里叫「券池*」、在股票模板里叫「行业*」，
        真实导入时由 _split_columns 逐列探测 FACTOR_PANEL_COLUMN_MAPPING 得出。
        写死一个列名会让另一个数据集的用例固定报 industry 缺失。
        """
        fixed: dict = {}
        for column in row:
            field = FACTOR_PANEL_COLUMN_MAPPING.get(column)
            if field and field not in fixed:
                fixed[field] = column
        assert set(fixed) >= {"as_of_date", "code", "industry"}, (
            f"用例自身写错了：row 的列名推导不出必填字段，得到 {sorted(fixed)}"
        )
        mapping = factor_name_mapping_for(dataset)
        return FactorPanelService._row_to_doc(
            pd.Series(row), 0, fixed, factor_cols, dataset, mapping,
            categorical_factor_keys_for(dataset),
        )

    def test_registered_categorical_factor_keeps_text(self):
        doc, error, skip, bad = self._parse(
            {"日期*": PERIOD, "代码*": "102681391.IB", "券池*": "其它信用债",
             "债务主体": "浙江省能源集团有限公司", "修正久期": 2.4691},
            BOND, ["债务主体", "修正久期"],
        )
        assert error is None and skip is None and bad == {}
        assert doc["dataset"] == BOND
        assert doc["factors"]["issuer"] == "浙江省能源集团有限公司"
        assert doc["factors"]["modified_duration"] == pytest.approx(2.4691)

    def test_unregistered_text_in_numeric_factor_is_blanked_and_reported(self):
        """文本混进数值因子：置空但按列计数上报，不静默丢弃."""
        doc, error, skip, bad = self._parse(
            {"日期*": PERIOD, "代码*": "600926.SH", "行业*": "城商行",
             "扣非PE": "亏损", "股息率TTM": 3.79},
            EQUITY, ["扣非PE", "股息率TTM"],
        )
        assert error is None and skip is None
        assert "pe_ttm_dn" not in doc["factors"]
        assert doc["factors"]["dividend_yield_ttm"] == pytest.approx(3.79)
        assert bad == {"扣非PE": 1}

    def test_same_text_value_is_text_in_one_dataset_and_blank_in_another(self):
        """同一份文本，在登记了类别键的数据集里是因子，在没登记的数据集里被置空."""
        bond_doc, *_ = self._parse(
            {"日期*": PERIOD, "代码*": "X", "券池*": "其它信用债", "债务主体": "某主体"},
            BOND, ["债务主体"],
        )
        assert bond_doc["factors"]["issuer"] == "某主体"

        eq_doc, _, _, eq_bad = self._parse(
            {"日期*": PERIOD, "代码*": "X", "行业*": "城商行", "债务主体": "某主体"},
            EQUITY, ["债务主体"],
        )
        assert "债务主体" not in eq_doc["factors"] and eq_bad == {"债务主体": 1}

    def test_blank_cell_yields_no_factor_and_no_report(self):
        doc, error, skip, bad = self._parse(
            {"日期*": PERIOD, "代码*": "X", "券池*": "其它信用债", "债务主体": None},
            BOND, ["债务主体"],
        )
        assert error is None and skip is None
        assert doc["factors"] == {}, "整期都这样才会被判为成分快照期"
        assert bad == {}
