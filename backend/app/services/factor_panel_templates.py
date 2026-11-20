# -*- coding: utf-8 -*-
"""因子截面导入 Excel 模板生成.

与 price_templates.py 同级同惯例：本模块只负责构建字节流，
路由层仅做 StreamingResponse 包装与 Content-Disposition。

模板按 dataset 分开出：factor_panel 集合被多个数据集共用，不同数据集的因子列
不同，共用一份模板会让人把 A 数据集的因子填进 B 数据集的文件——落库不报错
（因子列本就开放），但因子键与策略参数对不上，属静默错误。dataset 取值受
field_mappings.FACTOR_DATASETS 约束，新增数据集须同时在本模块登记模板列，
否则模块导入即报错（见 _validate_template_coverage）。

模板由两个 sheet 组成：
- 「因子截面数据」：纯净数据区（1 行表头 + 示例行），解析器直接读
- 「填写说明」：字段定义与导入规则，不参与解析
"""
import io
from typing import Any, Dict, List, Tuple

import pandas as pd

from app.schemas.field_mappings import FACTOR_DATASETS

# sheet 名是导入解析与模板生成的共同口径，只在本模块定义一次
DATA_SHEET_NAME = "因子截面数据"
NOTES_SHEET_NAME = "填写说明"

# 模板列顺序即解析器识别顺序；带 * 的为必填列。
# 固定列（日期/取数日/代码/简称/分组/市值/来源）之外的所有列一律进 factors dict，
# 因此「因子示例列」可以整列增删，不需要改后端代码。
TEMPLATE_COLUMNS_BY_DATASET: Dict[str, List[str]] = {
    # A股质量成长：行业内限额按「行业*」分组，市值加权时须给总市值
    "equity_quality_growth": [
        "日期*",
        "因子取数日",
        "代码*",
        "简称",
        "行业*",
        "单季度营收同比增速",
        "单季度扣非净利润同比增速",
        "扣非PE",
        "股息率TTM",
        "总市值(元)",
    ],
    # 债券券池：等权 1/N，不需要市值列；「券池*」落到 industry 字段，
    # 「债务主体」是文本类别因子，单发行人限额按它归并
    "bond_phoenix50": [
        "日期*",
        "因子取数日",
        "代码*",
        "简称",
        "券池*",
        "债务主体",
        "债券发行规模",
        "主体发行规模",
        "修正久期",
    ],
    # 指数增强个股截面：个股不进 assets / asset_prices，价格与估值只能从截面拿，
    # 所以 PB 与月末收盘价都作为因子列（落库键 pb / close）
    "index_enhance_stock": [
        "日期*",
        "因子取数日",
        "代码*",
        "简称",
        "行业*",
        "PB",
        "月末收盘价",
    ],
}

# 示例行：同一「日期*」为一期，可继续往下追加其他期。
# 因子值取各自数据集的真实样本，不编造——示例行会被当真填模板的人整段替换，
# 但列的数量级与单位必须是真的，否则照抄就错。
# 股票示例的「日期*」是决策日（2026-06-12），源文件的 2026-06-15 是持仓生效日，
# 需先换算为前一交易日；示例与说明列保持同一口径，避免照抄示例就填错。
TEMPLATE_EXAMPLE_ROWS_BY_DATASET: Dict[str, List[List[Any]]] = {
    "equity_quality_growth": [
        ["2026-06-12", "2026-03-31", "600926.SH", "杭州银行", "城商行",
         4.2888, 10.8476, 6.4747, 3.7931, 118014000000.0],
        ["2026-06-12", "2026-03-31", "300604.SZ", "长川科技", "半导体设备",
         69.0854, 612.2694, 72.2411, 0.0574, 146836000000.0],
    ],
    "bond_phoenix50": [
        ["2026-09-30", "2026-09-30", "102681391.IB", "26浙能源MTN002", "其它信用债",
         "浙江省能源集团有限公司", 1500000000, 10000000000, 2.4691],
        ["2026-09-30", "2026-09-30", "1805103.IB", "18浙江债02", "金融债/地方债/二永债",
         "浙江省人民政府", 30300000000, 1542793960000, 1.679],
    ],
}

# 固定字段说明（各数据集一致）；(字段名称, 是否必填, 说明)
_FIXED_INSTRUCTIONS: List[List[str]] = [
    ["日期*", "是", "决策日（信号日）as_of_date，YYYY-MM-DD。T 日收盘用该截面计算权重，"
                    "收益自 T+1 起；系统按此列分组识别有几期，一个文件可含任意期数。"
                    "源文件若给的是持仓生效日 startdate，请先换算为生效日前一交易日再填"],
    ["因子取数日", "否", "因子值的取数日 data_date（如财报日/季末），仅留痕核对，"
                        "缺省等于「日期*」；晚于决策日会被导入器拒绝（前视）"],
    ["代码*", "是", "证券代码 code，带交易所后缀（如 600926.SH、102681391.IB），"
                    "须与「资产列表」里的资产代码完全一致，否则回测取不到行情"],
    ["简称", "否", "证券简称 name，冗余存储便于人工核对，不参与计算"],
]

# 分组列说明（落到同一个 industry 字段，但各数据集的业务口径不同）
_INDUSTRY_INSTRUCTIONS: Dict[str, List[str]] = {
    "equity_quality_growth": [
        "行业*", "是",
        "行业分组键 industry，行业内限额按此列分组；空值会导致该股无法参与行业排序",
    ],
    "bond_phoenix50": [
        "券池*", "是",
        "券池分组，落到 industry 字段。策略按此列逐组做单发行人限额与组内选取数量，"
        "取值须与策略参数 pool_caps / pool_topk 中声明的分组完全一致"
        "（如「其它信用债」「金融债/地方债/二永债」）；截面出现未声明的分组会直接报错",
    ],
    "index_enhance_stock": [
        "行业*", "是",
        "所属行业 industry（申万一级等），sig3 按行业分组做 PB 排序，"
        "空值会让该股的估值分组无法归位",
    ],
}

# 因子列说明（各数据集不同）；「落库键」即 factors dict 里的英文键，
# 策略参数里引用的是这个键，不是中文列名
_FACTOR_INSTRUCTIONS_BY_DATASET: Dict[str, List[List[str]]] = {
    "equity_quality_growth": [
        ["单季度营收同比增速", "否", "落库键 revenue_yoy_sq。百分数填原值（12.34 表示 12.34%）"],
        ["单季度扣非净利润同比增速", "否", "落库键 profit_yoy_sq_dn。百分数填原值"],
        ["扣非PE", "否", "落库键 pe_ttm_dn。倍数填原值"],
        ["股息率TTM", "否", "落库键 dividend_yield_ttm。百分数填原值"],
        ["总市值(元)", "是（市值加权时）", "total_mv，单位元。加权方式选「总市值加权」时，"
                                         "对入选的每只股票必填且须 > 0；不提供请留空，不要填 0"],
    ],
    "bond_phoenix50": [
        ["债务主体", "是", "落库键 issuer，文本类别因子。单发行人限额按此列归并同一主体的"
                          "多只券，缺失或写法不一致会让同一主体被拆开计限"],
        ["债券发行规模", "是（打分期）", "落库键 issue_size，单位元。名次打分因子，"
                                       "按当期截面名次线性打分"],
        ["主体发行规模", "是（打分期）", "落库键 issuer_size，单位元。名次打分因子"],
        ["修正久期", "是（打分期）", "落库键 modified_duration，单位年。"
                                    "按距目标值线性扣分，目标与容差见策略参数"],
    ],
    "index_enhance_stock": [
        ["PB", "是", "落库键 pb，倍数填原值（不要先乘 100）。"
                    "sig3 在行业内按 PB 分位划分低估值组，取组分位由策略参数控"],
        ["月末收盘价", "是", "落库键 close，单位元。用于算个股区间收益"
                          "（原型用 20 个交易日收益，本轮按 retwin 参数化，口径差异见策略 docstring）"],
        ["（无示例行）", "—", "本数据集不预置示例行：PB 与收盘价必须来自当期真实截面，"
                              "照搬任何编造数值都会污染 sig3；请由数据准备脚本按年导出后直接导入"],
    ],
}

# 数据集清单在说明文本里逐行列出；模块加载时渲染一次，
# 不用占位符——占位符只能填「当前下载的那个数据集」，列不出全部可选值
_DATASET_LIST_LINES: List[str] = [
    f"  · {name}——{label}" for name, label in sorted(FACTOR_DATASETS.items())
]

# (小标题, [说明行, ...])；{dataset} 会在生成时替换为当前数据集标识
NOTE_BLOCKS: List[List[Any]] = [
    ["数据集（dataset）", [
        "本模板对应数据集 {dataset}。factor_panel 集合被多个数据集共用，",
        "导入时必须在接口上指明 dataset，且只能填已登记的数据集：",
        *_DATASET_LIST_LINES,
        "一个文件只能属于一个数据集；不要在同一文件里混放两个数据集的行。",
        "同一期日下不同数据集的行互不影响（覆盖导入也只删本数据集的该期）。",
    ]],
    ["因子列可自由增删", [
        "除「日期*/因子取数日/代码*/简称/分组列/总市值/自由流通市值/数据来源」这些固定列外，",
        "其余所有列都会被当作因子收进 factors 字段，列名即因子名。",
        "换一套因子只需改 Excel 列头与策略参数，不需要改表结构、不需要改后端代码。",
        "列名可在 app/schemas/field_mappings.py 的 FACTOR_NAME_MAPPING_BY_DATASET 里",
        "按数据集登记中文→英文键；未登记的列名直接按原列名存，不会报错。",
        "注意：因子列名映射按 dataset 分组，A 数据集登记的列名不会作用于 B 数据集。",
    ]],
    ["文本因子（类别因子）", [
        "因子值默认按数值解析。需要按文本保留的因子（如债券的「债务主体」→ issuer，",
        "用于单发行人限额归并同一主体的多只券）必须在 field_mappings 的",
        "FACTOR_CATEGORICAL_KEYS_BY_DATASET 里按数据集登记；未登记的因子列出现文本时",
        "该单元格置空，并在导入结果里按列计数提示，不会静默丢弃。",
    ]],
    ["多期导入", [
        "同一个文件里放多期数据即可，系统按「日期*」列自动分组，一期一组。",
        "只导一期也照常工作；后续每期数据到了再导一次，已有期不受影响。",
    ]],
    ["整期无因子 = 成分快照期", [
        "同一期里所有行的因子列都为空时，该期按「成分快照期」写入：",
        "策略读不到打分因子列，会全截面入选并等权（历史期没有全池因子截面时的口径）。",
        "同一期里只有个别行因子为空时，这些行判为漏填、不写库，",
        "计入 skipped_reasons.factor_empty，导入结果里会给出行数。",
        "所以成分快照期请整期都不填因子列，不要只留个别行空着——那样这几行会被丢掉，",
        "当期名单就不完整，而且剩下的行有因子，整期不再被判为快照期。",
    ]],
    ["市值单位", [
        "市值列单位默认是「元」。若你的源数据是「亿元」，请把列头写成",
        "「总市值(亿元)」，系统会按 FACTOR_PANEL_MV_UNIT_BY_COLUMN 自动乘 1e8 换算，",
        "不要自己先换算又保留亿元列头，否则会放大 1e8 倍。",
        "市值需要对「全部入池标的」提供，不能只给当期新增的标的。",
    ]],
    ["导入模式", [
        "upsert（默认）：按 (数据集, 日期, 代码) 逐行覆盖，重复导入结果一致。",
        "replace：只覆盖本数据集在文件中出现的那几期——先删这些期的旧行再写入，",
        "           其他期、其他数据集都不动。",
        "incremental：只写库里还没有的 (数据集, 日期, 代码)，已有行原样保留。",
    ]],
    ["数据 sheet 必须纯净", [
        "「因子截面数据」sheet 里不要加说明文字、不要插空行分隔、不要合并单元格，",
        "否则会被当成脏数据行。所有说明都放在本 sheet。",
    ]],
]


def _validate_template_coverage() -> None:
    """校验模板登记与 dataset 受控清单一致（模块导入时执行）。

    新增数据集只登记了 FACTOR_DATASETS 却忘了登记模板列，等到用户点「下载模板」
    才报错太晚；反向（登记了模板但清单里没有）说明清单被删过而模板忘了同步。
    两种情况都在这里立刻暴露，不留到运行期。
    """
    missing = sorted(set(FACTOR_DATASETS) - set(TEMPLATE_COLUMNS_BY_DATASET))
    extra = sorted(set(TEMPLATE_COLUMNS_BY_DATASET) - set(FACTOR_DATASETS))
    if missing or extra:
        raise ValueError(
            "因子截面模板登记与 FACTOR_DATASETS 不一致："
            f"缺模板列登记 {missing or '无'}；模板多余 {extra or '无'}。"
            "新增数据集须同时在 field_mappings.FACTOR_DATASETS 与本模块的 "
            "TEMPLATE_COLUMNS_BY_DATASET / TEMPLATE_EXAMPLE_ROWS_BY_DATASET / "
            "_FACTOR_INSTRUCTIONS_BY_DATASET / _INDUSTRY_INSTRUCTIONS 登记"
        )
    for dataset, rows in TEMPLATE_EXAMPLE_ROWS_BY_DATASET.items():
        columns = TEMPLATE_COLUMNS_BY_DATASET[dataset]
        bad = [i for i, row in enumerate(rows) if len(row) != len(columns)]
        if bad:
            raise ValueError(
                f"数据集 {dataset} 的示例行 {bad} 列数与模板列数 {len(columns)} 不一致"
            )


def template_spec_for(dataset: str) -> Tuple[List[str], List[List[Any]], List[List[str]]]:
    """取指定数据集的模板规格。

    Args:
        dataset: 数据集标识，必须在 FACTOR_DATASETS 受控清单内且已登记模板列

    Returns:
        (模板列名, 示例行, 字段说明表首行为表头)

    Raises:
        ValueError: dataset 为空、不在受控清单内，或未登记模板列/说明
    """
    available = "、".join(sorted(FACTOR_DATASETS))
    name = str(dataset or "").strip()
    if not name:
        raise ValueError(f"dataset 不能为空：因子截面模板按数据集出，可选 {available}")
    if name not in FACTOR_DATASETS:
        raise ValueError(f"未知的因子数据集 dataset={name!r}，可选 {available}")
    if name not in TEMPLATE_COLUMNS_BY_DATASET:
        raise ValueError(f"数据集 {name} 尚未登记导入模板列，无法生成模板")

    industry = _INDUSTRY_INSTRUCTIONS.get(name)
    if industry is None:
        raise ValueError(f"数据集 {name} 尚未登记分组列说明，无法生成模板")
    instructions = (
        _FIXED_INSTRUCTIONS + [industry] + _FACTOR_INSTRUCTIONS_BY_DATASET.get(name, [])
    )
    return (
        TEMPLATE_COLUMNS_BY_DATASET[name],
        TEMPLATE_EXAMPLE_ROWS_BY_DATASET.get(name, []),
        [["字段名称", "是否必填", "说明"]] + instructions,
    )


def build_factor_panel_template(dataset: str) -> Tuple[io.BytesIO, str]:
    """构建指定数据集的因子截面导入模板。

    Args:
        dataset: 数据集标识，见 template_spec_for

    Returns:
        (BytesIO 字节流, 文件名)

    Raises:
        ValueError: dataset 为空、不在受控清单内，或未登记模板
    """
    columns, examples, instructions = template_spec_for(dataset)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(examples, columns=columns).to_excel(
            writer, index=False, sheet_name=DATA_SHEET_NAME
        )
        pd.DataFrame(instructions[1:], columns=instructions[0]).to_excel(
            writer, index=False, sheet_name=NOTES_SHEET_NAME
        )
        _write_note_blocks(writer, instructions, dataset)
    output.seek(0)
    return output, f"factor_panel_import_template_{dataset}.xlsx"


def _write_note_blocks(writer, instructions: List[List[str]], dataset: str) -> None:
    """把说明段落追加到「填写说明」sheet 的字段表下方（空两行起）。"""
    rows: List[List[str]] = []
    for title, lines in NOTE_BLOCKS:
        rows.append([_fill(title, dataset)])
        rows.extend([[f"  {_fill(line, dataset)}"] for line in lines])
        rows.append([""])
    # 表头 1 行 + 字段 len(instructions)-1 行 + 空 2 行
    start_row = len(instructions) + 3
    pd.DataFrame(rows, columns=["导入规则说明"]).to_excel(
        writer, index=False, sheet_name=NOTES_SHEET_NAME, startrow=start_row
    )


def _fill(text: str, dataset: str) -> str:
    """把说明文本里的 {dataset} 占位符替换为当前数据集标识。

    用 str.replace 而非 str.format：说明文本里有「{ }」以外的中文括号与
    逗号，format 会把非占位符的大括号当格式符报错。
    """
    return text.replace("{dataset}", dataset)


_validate_template_coverage()
