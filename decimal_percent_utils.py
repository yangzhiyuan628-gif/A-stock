# -*- coding: utf-8 -*-
"""
v5.5 百分比/涨幅十进制修复工具

统一规则：
- 程序内部所有涨跌幅/涨速/换手率/封板率等，都用“数值型百分数点”保存；
- 9.99 表示 9.99%，不是字符串 "9.99%"；
- 0.0999 会自动识别为 9.99；
- "9.99%" 会转成 9.99；
- 新股/北交所等 100% 以上涨幅，如 710.15，会保留为 710.15。
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


PERCENT_KEYWORDS = [
    "涨跌幅", "涨幅", "涨速", "5分钟涨速", "规则涨速",
    "换手率", "封板率", "炸板率", "跌幅", "距涨停幅度",
    "行业涨幅", "概念涨幅", "平均涨幅", "平均5分钟涨速",
    "涨停幅度", "振幅",
]

AMOUNT_KEYWORDS = [
    "成交额", "流通市值", "总市值", "封板资金", "主力净流入", "板块成交额"
]


def is_percent_col(col: Any) -> bool:
    name = str(col)
    return any(k in name for k in PERCENT_KEYWORDS)


def is_amount_col(col: Any) -> bool:
    name = str(col)
    return any(k in name for k in AMOUNT_KEYWORDS)


def _clean_one_value(x: Any):
    if pd.isna(x):
        return pd.NA

    if isinstance(x, (int, float)):
        return float(x)

    s = str(x).strip()
    if not s or s in {"-", "--", "None", "nan", "NaN"}:
        return pd.NA

    s = s.replace("%", "")
    s = s.replace(",", "")
    s = s.replace("亿", "")
    s = s.replace("万", "")
    s = s.replace("元", "")
    s = s.replace(" ", "")

    # 兼容中文全角负号
    s = s.replace("－", "-").replace("—", "-")

    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return pd.NA

    try:
        return float(m.group(0))
    except Exception:
        return pd.NA


def to_numeric_series(s: pd.Series) -> pd.Series:
    return s.map(_clean_one_value).astype("Float64")


def to_percent_points(s: pd.Series) -> pd.Series:
    """
    输出单位为“百分点”：
    - 9.99% -> 9.99
    - 9.99 -> 9.99
    - 0.0999 -> 9.99
    """
    out = to_numeric_series(s)
    non_na = out.dropna()
    if non_na.empty:
        return out

    # 如果绝大多数数值位于 -1~1，并且存在小数比例，则认为原始单位是 ratio，需要 *100
    # 例如 0.0999 表示 9.99%
    q95 = non_na.abs().quantile(0.95)
    max_abs = non_na.abs().max()
    if q95 <= 1.2 and max_abs <= 3:
        out = out * 100

    return out.round(4)


def normalize_percent_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    x = df.copy()
    for col in list(x.columns):
        if is_percent_col(col):
            x[col] = to_percent_points(x[col])
    return x


def normalize_common_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    x = normalize_percent_columns(df)

    for col in list(x.columns):
        name = str(col)

        # 金额列只转数值，不在这里强行除以 1e8，避免重复除。
        if is_amount_col(name):
            x[col] = to_numeric_series(x[col])

        # 常见数值列
        if name in {"最新价", "现价", "收盘", "开盘", "最高", "最低", "连板数", "最高板", "涨停数", "炸板", "跌停", "强势股数"}:
            x[col] = to_numeric_series(x[col])

    return x


def sort_by_numeric(df: pd.DataFrame, col: str, ascending: bool = False) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns:
        return df
    x = normalize_common_numeric_columns(df)
    return x.sort_values(col, ascending=ascending, na_position="last")


def install_streamlit_decimal_patch():
    """
    兜底补丁：自动修复 st.dataframe / st.data_editor 展示时的百分比列。
    即使上游数据是 "9.99%" 字符串，表格里也会变成数值 9.99。
    """
    try:
        import streamlit as st
    except Exception:
        return

    if getattr(st, "_decimal_percent_patch_installed", False):
        return

    old_dataframe = st.dataframe
    old_data_editor = getattr(st, "data_editor", None)

    def dataframe_patched(data=None, *args, **kwargs):
        if isinstance(data, pd.DataFrame):
            data = normalize_common_numeric_columns(data)
        return old_dataframe(data, *args, **kwargs)

    st.dataframe = dataframe_patched

    if old_data_editor is not None:
        def data_editor_patched(data=None, *args, **kwargs):
            if isinstance(data, pd.DataFrame):
                data = normalize_common_numeric_columns(data)
            return old_data_editor(data, *args, **kwargs)

        st.data_editor = data_editor_patched

    st._decimal_percent_patch_installed = True
