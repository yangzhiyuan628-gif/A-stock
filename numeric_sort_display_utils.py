# -*- coding: utf-8 -*-
"""
v5.8 数值排序/显示强修复

核心解决：
1. "10.43%"、"9.99%" 这种字符串按数值排序；
2. "5838.56万"、"33.02亿"、"327.91亿" 混合单位统一转成“亿”；
3. "14:18:06" 这类时间列按真实时间排序；
4. 同时 patch：
   - pandas.DataFrame.sort_values
   - streamlit.dataframe
   - streamlit.data_editor

注意：
- 这是显示与排序层修复，不改你的原始 CSV 文件；
- 表格里金额统一显示为“亿”；
- 百分比统一显示为 10.43 代表 10.43%。
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


PERCENT_KEYS = [
    "涨跌幅", "涨幅", "跌幅", "涨速", "5分钟涨速", "规则涨速",
    "换手率", "封板率", "炸板率", "距涨停幅度", "振幅",
    "行业涨幅", "概念涨幅", "平均涨幅", "平均5分钟涨速",
]

AMOUNT_KEYS = [
    "成交额", "成交金额", "流通市值", "总市值", "市值",
    "封板资金", "主力净流入", "净流入", "板块成交额",
    "买入金额", "卖出金额", "成交净额",
]

TIME_KEYS = [
    "首次封板时间", "最后封板时间", "封板时间", "开板时间", "时间"
]


def _name(col: Any) -> str:
    return str(col).strip()


def is_percent_col(col: Any) -> bool:
    name = _name(col)
    return any(k in name for k in PERCENT_KEYS)


def is_amount_col(col: Any) -> bool:
    name = _name(col)
    # 避免“成交量”被当成金额
    if "成交量" in name or "数量" in name:
        return False
    return any(k in name for k in AMOUNT_KEYS)


def is_time_col(col: Any) -> bool:
    name = _name(col)
    return any(k in name for k in TIME_KEYS)


def _extract_float(x: Any):
    if pd.isna(x):
        return pd.NA
    if isinstance(x, (int, float)):
        return float(x)

    s = str(x).strip()
    if not s or s in {"-", "--", "None", "nan", "NaN"}:
        return pd.NA

    s = s.replace(",", "").replace(" ", "")
    s = s.replace("－", "-").replace("—", "-")

    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return pd.NA
    try:
        return float(m.group(0))
    except Exception:
        return pd.NA


def parse_percent_series(s: pd.Series) -> pd.Series:
    """
    统一为百分点：
    "10.43%" -> 10.43
    10.43 -> 10.43
    0.1043 -> 10.43
    """
    raw = s.copy()
    out = raw.map(_extract_float).astype("Float64")

    non_na = out.dropna()
    if non_na.empty:
        return out

    # 若绝大多数绝对值 <= 1.5，则认为是比例，需要 *100
    # 例如 0.1043 -> 10.43
    q95 = non_na.abs().quantile(0.95)
    max_abs = non_na.abs().max()
    if q95 <= 1.5 and max_abs <= 3:
        out = out * 100

    return out.astype("Float64")


def parse_amount_to_yi_series(s: pd.Series) -> pd.Series:
    """
    统一为“亿”：
    "33.02亿" -> 33.02
    "5838.56万" -> 0.583856
    "348.53亿" -> 348.53
    若无单位：
      - 中位数 > 1,000,000：按元处理 /1e8
      - 否则保留原值，认为已经是亿或业务侧数值
    """
    values = []
    has_unit = False

    for x in s:
        if pd.isna(x):
            values.append(pd.NA)
            continue

        txt = str(x).strip()
        val = _extract_float(txt)
        if pd.isna(val):
            values.append(pd.NA)
            continue

        if "万" in txt:
            values.append(float(val) / 10000.0)
            has_unit = True
        elif "亿" in txt:
            values.append(float(val))
            has_unit = True
        elif "元" in txt:
            values.append(float(val) / 1e8)
            has_unit = True
        else:
            values.append(float(val))

    out = pd.Series(values, index=s.index, dtype="Float64")

    if not has_unit:
        non_na = out.dropna()
        if not non_na.empty:
            med = float(non_na.abs().median())
            # 东方财富/AKShare 原始成交额通常是元
            if med > 1_000_000:
                out = out / 1e8

    return out.astype("Float64")


def parse_time_to_seconds_series(s: pd.Series) -> pd.Series:
    """
    "14:18:06" -> 当日秒数
    92501 / "92501" -> 09:25:01
    """
    vals = []
    for x in s:
        if pd.isna(x):
            vals.append(pd.NA)
            continue
        txt = str(x).strip()
        if not txt or txt in {"-", "--", "None", "nan"}:
            vals.append(pd.NA)
            continue

        # HH:MM:SS
        m = re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", txt)
        if m:
            h = int(m.group(1)); mi = int(m.group(2)); sec = int(m.group(3) or 0)
            vals.append(h * 3600 + mi * 60 + sec)
            continue

        # 92501 -> 09:25:01, 145021 -> 14:50:21
        digits = "".join(re.findall(r"\d", txt))
        if 4 <= len(digits) <= 6:
            digits = digits.zfill(6)
            h = int(digits[:2]); mi = int(digits[2:4]); sec = int(digits[4:6])
            if 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= sec <= 59:
                vals.append(h * 3600 + mi * 60 + sec)
                continue

        vals.append(_extract_float(txt))

    return pd.Series(vals, index=s.index, dtype="Float64")


def normalize_numeric_units(df: pd.DataFrame) -> pd.DataFrame:
    """
    将常见百分比/金额/时间列转换为真正数值。
    金额统一为“亿”；百分比统一为“百分点”。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    x = df.copy()

    for col in list(x.columns):
        try:
            if is_percent_col(col):
                x[col] = parse_percent_series(x[col])
            elif is_amount_col(col):
                x[col] = parse_amount_to_yi_series(x[col])
            elif is_time_col(col):
                # 时间列不直接改显示，防止用户想看原时间；排序时用临时列。
                # 这里跳过，排序 patch 会处理。
                pass
        except Exception:
            pass

    return x


def column_config_for(df: pd.DataFrame):
    """
    给 Streamlit dataframe 的 column_config。
    """
    try:
        import streamlit as st
    except Exception:
        return {}

    cfg = {}
    if df is None or not isinstance(df, pd.DataFrame):
        return cfg

    for col in df.columns:
        if is_percent_col(col):
            cfg[col] = st.column_config.NumberColumn(str(col), format="%.2f%%")
        elif is_amount_col(col):
            cfg[col] = st.column_config.NumberColumn(str(col), format="%.2f亿")
    return cfg


def _make_sort_key(df: pd.DataFrame, col: Any):
    if col not in df.columns:
        return None

    try:
        if is_percent_col(col):
            return parse_percent_series(df[col])
        if is_amount_col(col):
            return parse_amount_to_yi_series(df[col])
        if is_time_col(col):
            return parse_time_to_seconds_series(df[col])
    except Exception:
        return None

    return None


def install_numeric_sort_display_patch():
    """
    安装全局补丁。
    """
    import pandas as _pd

    if getattr(_pd.DataFrame, "_stock_robot_numeric_sort_patched", False):
        return

    old_sort_values = _pd.DataFrame.sort_values

    def sort_values_patched(self, by=None, *args, **kwargs):
        if by is None:
            return old_sort_values(self, by=by, *args, **kwargs)

        # inplace=True 情况不强改，避免副作用
        if kwargs.get("inplace", False):
            return old_sort_values(self, by=by, *args, **kwargs)

        by_list = list(by) if isinstance(by, (list, tuple)) else [by]
        new_by = []
        temp_cols = []
        work = self.copy()
        changed = False

        for col in by_list:
            key = _make_sort_key(work, col)
            if key is not None and key.notna().sum() > 0:
                tmp = f"__sort_key_{str(col)}__"
                i = 0
                while tmp in work.columns:
                    i += 1
                    tmp = f"__sort_key_{str(col)}_{i}__"
                work[tmp] = key
                temp_cols.append(tmp)
                new_by.append(tmp)
                changed = True
            else:
                new_by.append(col)

        if not changed:
            return old_sort_values(self, by=by, *args, **kwargs)

        result = old_sort_values(work, by=new_by if isinstance(by, (list, tuple)) else new_by[0], *args, **kwargs)
        return result.drop(columns=temp_cols, errors="ignore")

    _pd.DataFrame.sort_values = sort_values_patched
    _pd.DataFrame._stock_robot_numeric_sort_patched = True

    try:
        import streamlit as st
    except Exception:
        return

    if getattr(st, "_stock_robot_numeric_display_patched", False):
        return

    old_dataframe = st.dataframe
    old_data_editor = getattr(st, "data_editor", None)

    def dataframe_patched(data=None, *args, **kwargs):
        if isinstance(data, pd.DataFrame):
            data = normalize_numeric_units(data)
            user_cfg = kwargs.pop("column_config", None) or {}
            cfg = column_config_for(data)
            cfg.update(user_cfg)
            kwargs["column_config"] = cfg
        return old_dataframe(data, *args, **kwargs)

    st.dataframe = dataframe_patched

    if old_data_editor is not None:
        def data_editor_patched(data=None, *args, **kwargs):
            if isinstance(data, pd.DataFrame):
                data = normalize_numeric_units(data)
                user_cfg = kwargs.pop("column_config", None) or {}
                cfg = column_config_for(data)
                cfg.update(user_cfg)
                kwargs["column_config"] = cfg
            return old_data_editor(data, *args, **kwargs)

        st.data_editor = data_editor_patched

    st._stock_robot_numeric_display_patched = True
