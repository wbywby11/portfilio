"""行情导入 Excel 模板生成（自 app/api/asset.py 平移，P9 治理）.

单资产纵向模板与多资产宽表模板的字节流构建；路由层仅负责
StreamingResponse 包装与 Content-Disposition。
"""
import io


def build_single_asset_price_template(kind: str):
    """下载单列资产、纵向日期行的行情 Excel 模板（与「批量导入行情」配套）。"""
    import pandas as pd

    kind = (kind or "full").strip().lower()
    allowed = {"full", "open", "high", "low", "close", "volume", "amount", "scale"}
    if kind not in allowed:
        kind = "full"

    label_cn = {
        "open": "开盘价*",
        "high": "最高价*",
        "low": "最低价*",
        "close": "收盘价*",
        "volume": "成交量*",
        "amount": "成交额*",
        "scale": "规模*",
    }
    sample_val = {
        "open": 3000.50,
        "high": 3050.80,
        "low": 2995.20,
        "close": 3020.60,
        "volume": 125000000,
        "amount": 15000000000.00,
        "scale": 1.25e11,
    }

    if kind == "full":
        columns = [
            "日期*",
            "开盘价",
            "最高价",
            "最低价",
            "收盘价*",
            "成交量",
            "成交额",
            "规模",
        ]
        example_data = [
            ["2025-01-01", 3000.50, 3050.80, 2995.20, 3020.60, 125000000, 15000000000.00, 1.2e11],
            ["2025-01-02", "", "", "", 3075.50, 130000000, 16000000000.00, ""],
        ]
        instructions = [
            ["字段名称", "是否必填", "说明"],
            ["日期*", "是", "格式：YYYY-MM-DD 或 YYYYMMDD"],
            ["开盘价", "否", "数值"],
            ["最高价", "否", "数值"],
            ["最低价", "否", "数值"],
            ["收盘价*", "新交易日建议填", "按日合并时可只更新部分列；无该日时须能推断收盘价"],
            ["成交量", "否", "整数或数值"],
            ["成交额", "否", "数值"],
            ["规模", "否", "如 AUM、份额规模等"],
        ]
        fname = "price_import_template_single_asset_full.xlsx"
    else:
        col2 = label_cn[kind]
        columns = ["日期*", col2]
        example_data = [
            ["2025-01-01", sample_val[kind]],
            ["2025-01-02", sample_val[kind]],
        ]
        instructions = [
            ["字段名称", "是否必填", "说明"],
            ["日期*", "是", "格式：YYYY-MM-DD 或 YYYYMMDD"],
            [col2.replace("*", ""), "是", "与资产库 → 资产行情 → 批量导入行情 配合；按日合并只更新本列"],
        ]
        fname = f"price_import_template_single_asset_{kind}.xlsx"

    df = pd.DataFrame(example_data, columns=columns)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="行情导入模板")
        pd.DataFrame(instructions[1:], columns=instructions[0]).to_excel(
            writer, index=False, sheet_name="说明"
        )
    output.seek(0)
    return output, fname


def build_multi_asset_price_template(metric: str):
    """
    大类资产底层数据格式：第 4 行（Excel 行号）为资产名称、第 5 行为资产代码、第 6 行起为日期与数值列。
    与「多资产Excel导入」解析规则一致；导入时在界面选择相同 metric。
    """
    import pandas as pd

    metric = (metric or "close").strip().lower()
    if metric not in ("close", "open", "high", "low", "amount", "volume", "scale"):
        metric = "close"
    metric_label = {
        "close": "收盘价",
        "open": "开盘价",
        "high": "最高价",
        "low": "最低价",
        "amount": "成交额",
        "volume": "成交量",
        "scale": "规模",
    }[metric]

    n_rows = 12
    n_cols = 5
    grid = [[None] * n_cols for _ in range(n_rows)]
    grid[3][0] = "Date"
    grid[3][1] = "沪深300"
    grid[3][2] = "中证500"
    grid[3][3] = "示例债券指数"
    grid[3][4] = "示例货币利率"
    grid[4][0] = "Date"
    grid[4][1] = "000300.SH"
    grid[4][2] = "000905.SH"
    grid[4][3] = "CBA00101.CS"
    grid[4][4] = "DR007.IB"
    sample_dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]
    for i, d in enumerate(sample_dates):
        r = 5 + i
        if r >= n_rows:
            break
        grid[r][0] = d
        grid[r][1] = 3500.12 + i
        grid[r][2] = 5200.45 + i
        grid[r][3] = 100.2 + i * 0.01
        grid[r][4] = 1.85 + i * 0.001

    df = pd.DataFrame(grid)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=False, sheet_name="Sheet1")
        instructions = [
            ["说明", "内容"],
            [
                "布局A（Wind类）",
                f"第 4 行：各列资产中文名称；第 5 行：资产代码；第 6 行起：A 列为日期，其余列为「{metric_label}」",
            ],
            [
                "布局B（基金/证券）",
                "第 1 行 A 列为「基金代码」等、B 列起为各资产代码；第 2 行 A 列为「基金名称」、B 列起为名称；"
                "第 3 行起 A 列为日期，其余列为行情数值（与图3收盘价表一致）",
            ],
            ["metric", f"导入时请选择 metric={metric}，与下载模板一致"],
            ["日期", "支持 YYYY-MM-DD；可增加行延续历史"],
            ["多 Sheet", "可在多个工作表中放置资产列，解析时会合并（同代码只保留首次出现）"],
            ["导入入口", "资产库 → 资产行情 →「多资产Excel导入」"],
        ]
        pd.DataFrame(instructions[1:], columns=instructions[0]).to_excel(
            writer, index=False, sheet_name="填写说明"
        )
    output.seek(0)
    fname = f"price_import_template_multi_asset_{metric}.xlsx"
    return output, fname
