"""统一单位格式化模块。

目标：
- 原始 CSV 保留数值，便于排序和计算；
- Streamlit 与 Markdown 报告使用更适合看盘的单位：亿、万、%、09:25:01。
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

NULL_TEXT = {"", "-", "--", "nan", "None", "NaN", "null"}

MONEY_COL_KEYWORDS = [
    "成交额", "封板资金", "封单资金", "资金", "净额", "净买额", "净流入",
    "流通市值", "总市值", "市值", "金额", "当日盈亏", "总盈亏", "可用金额", "可取",
]
PRICE_COL_KEYWORDS = [
    "最新价", "现价", "收盘价", "开盘价", "最高", "最低", "今开", "昨收",
    "涨停价", "跌停价", "均价", "参考成本价", "成本", "价格", "涨跌额",
]
PERCENT_COL_KEYWORDS = [
    "涨跌幅", "涨幅", "跌幅", "换手率", "振幅", "封板率", "红盘率", "平均涨跌幅",
    "盈亏比例", "收益率",
]
TIME_COL_KEYWORDS = [
    "首次封板时间", "最后封板时间", "首次涨停时间", "最后涨停时间", "封板时间", "开板时间",
]
VOLUME_COL_KEYWORDS = [
    "成交量", "封单量", "流通股", "总股本", "可用数量", "持仓数量", "未结数量",
]
INTEGER_COL_KEYWORDS = ["连板高度", "炸板次数", "序号", "排名"]
CODE_COLS = {"代码", "证券代码", "股票代码"}
BOOL_COLS = {"是否涨停", "接近涨停", "强异动", "弱风险", "早盘前排"}

HIDDEN_INTERNAL_SUFFIXES = ("_数值",)
HIDDEN_INTERNAL_COLS = {"炸板次数_数值", "换手率_数值", "成交额_数值", "最新价_数值", "涨跌幅_数值"}


def is_nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() in NULL_TEXT


def to_float(value: Any, default: float | None = None) -> float | None:
    """宽松解析数字，兼容 3.2亿、1250万、12.3%、1,234。"""
    if is_nullish(value):
        return default
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return default
    s = str(value).strip().replace(",", "")
    multiplier = 1.0
    if "亿" in s:
        multiplier = 100_000_000.0
    elif "万" in s:
        multiplier = 10_000.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return default
    try:
        return float(m.group(0)) * multiplier
    except Exception:
        return default


def strip_trailing_zeros(text: str) -> str:
    return re.sub(r"\.0+$", "", re.sub(r"(\.\d*?)0+$", r"\1", text))


def format_amount(value: Any) -> str:
    n = to_float(value, None)
    if n is None:
        return ""
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 100_000_000:
        return f"{sign}{n / 100_000_000:.2f}亿"
    if n >= 10_000:
        return f"{sign}{n / 10_000:.2f}万"
    if n >= 1000:
        return f"{sign}{n:,.0f}"
    return strip_trailing_zeros(f"{sign}{n:.2f}")


def format_volume(value: Any, unit: str = "手") -> str:
    n = to_float(value, None)
    if n is None:
        return ""
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 100_000_000:
        return f"{sign}{n / 100_000_000:.2f}亿{unit}"
    if n >= 10_000:
        return f"{sign}{n / 10_000:.2f}万{unit}"
    return f"{sign}{n:.0f}{unit}"


def format_percent(value: Any) -> str:
    n = to_float(value, None)
    if n is None:
        return ""
    return f"{n:.2f}%"


def format_price(value: Any) -> str:
    n = to_float(value, None)
    if n is None:
        return ""
    if abs(n) >= 1000:
        return f"{n:,.2f}"
    return strip_trailing_zeros(f"{n:.3f}")


def format_integer(value: Any) -> str:
    n = to_float(value, None)
    if n is None:
        return ""
    return f"{int(round(n))}"


def format_time(value: Any) -> str:
    if is_nullish(value):
        return ""
    s = str(value).strip()
    if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", s):
        parts = s.split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
    digits = re.sub(r"\D", "", s)
    if not digits:
        return s
    # 92501 -> 09:25:01, 93033 -> 09:30:33, 130033 -> 13:00:33
    if len(digits) <= 4:
        digits = digits.zfill(4)
        return f"{digits[:2]}:{digits[2:4]}"
    digits = digits.zfill(6)[-6:]
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"


def format_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "是"}:
        return "是"
    if s in {"false", "0", "no", "否"}:
        return "否"
    return str(value)


def normalize_code(value: Any) -> str:
    s = str(value).strip()
    m = re.search(r"(\d{6})", s)
    return m.group(1) if m else s


def col_contains(col: str, keywords: list[str]) -> bool:
    return any(k in col for k in keywords)


def should_drop_internal(col: str) -> bool:
    return col in HIDDEN_INTERNAL_COLS or col.endswith(HIDDEN_INTERNAL_SUFFIXES)


def format_series_by_col(col: str, s: pd.Series) -> pd.Series:
    if col in CODE_COLS:
        return s.apply(normalize_code)
    if col in BOOL_COLS:
        return s.apply(format_bool)
    if col_contains(col, TIME_COL_KEYWORDS):
        return s.apply(format_time)
    if col_contains(col, PERCENT_COL_KEYWORDS):
        return s.apply(format_percent)
    # 市值、成交额、封板资金等优先按金额处理；注意涨跌额是价格，不是资金。
    if col_contains(col, MONEY_COL_KEYWORDS) and "涨跌额" not in col:
        return s.apply(format_amount)
    if col_contains(col, VOLUME_COL_KEYWORDS):
        unit = "股" if any(k in col for k in ["股", "股本"]) else "手"
        return s.apply(lambda x: format_volume(x, unit=unit))
    if col_contains(col, PRICE_COL_KEYWORDS):
        return s.apply(format_price)
    if col_contains(col, INTEGER_COL_KEYWORDS):
        return s.apply(format_integer)
    return s


def format_for_display(df: pd.DataFrame, drop_internal: bool = True) -> pd.DataFrame:
    """返回适合网页/报告展示的 DataFrame，不改变原始 df。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    if drop_internal:
        out = out[[c for c in out.columns if not should_drop_internal(c)]]
    for col in list(out.columns):
        out[col] = format_series_by_col(col, out[col])
    return out


def preview_unit_examples() -> pd.DataFrame:
    return pd.DataFrame({
        "字段": ["成交额", "流通市值", "总市值", "换手率", "封板资金", "首次封板时间"],
        "原始值": [351946464, 9583129311.32, 14492073156.32, 3.6726, 254270689, 92501],
        "显示值": [format_amount(351946464), format_amount(9583129311.32), format_amount(14492073156.32), format_percent(3.6726), format_amount(254270689), format_time(92501)],
    })
