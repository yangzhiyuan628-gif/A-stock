# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import pandas as pd

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)

PERCENT_KEYS = ["涨跌幅", "涨幅", "跌幅", "涨速", "5分钟涨速", "规则涨速", "换手率", "封板率", "炸板率", "距涨停幅度", "振幅", "行业涨幅", "概念涨幅", "平均涨幅", "平均5分钟涨速"]
AMOUNT_KEYS = ["成交额", "成交金额", "流通市值", "总市值", "市值", "封板资金", "主力净流入", "净流入", "板块成交额", "买入金额", "卖出金额", "成交净额"]
TIME_KEYS = ["首次封板时间", "最后封板时间", "封板时间", "开板时间", "时间"]


def is_percent_col(col: Any) -> bool:
    return any(k in str(col) for k in PERCENT_KEYS)


def is_amount_col(col: Any) -> bool:
    name = str(col)
    if "成交量" in name or "数量" in name:
        return False
    return any(k in name for k in AMOUNT_KEYS)


def is_time_col(col: Any) -> bool:
    return any(k in str(col) for k in TIME_KEYS)


def _extract_float(x: Any):
    if pd.isna(x):
        return pd.NA
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s or s in {"-", "--", "None", "nan", "NaN"}:
        return pd.NA
    s = s.replace(",", "").replace("%", "").replace(" ", "").replace("－", "-").replace("—", "-")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return pd.NA
    try:
        return float(m.group(0))
    except Exception:
        return pd.NA


def parse_percent_series(s: pd.Series) -> pd.Series:
    out = s.map(_extract_float).astype("Float64")
    non = out.dropna()
    if not non.empty:
        q95 = non.abs().quantile(0.95)
        max_abs = non.abs().max()
        if q95 <= 1.5 and max_abs <= 3:
            out = out * 100
    return out.astype("Float64")


def parse_amount_to_yi_series(s: pd.Series) -> pd.Series:
    vals = []
    has_unit = False
    for x in s:
        if pd.isna(x):
            vals.append(pd.NA)
            continue
        txt = str(x).strip().replace(",", "")
        val = _extract_float(txt)
        if pd.isna(val):
            vals.append(pd.NA)
            continue
        if "万" in txt:
            vals.append(float(val) / 10000.0)
            has_unit = True
        elif "亿" in txt:
            vals.append(float(val))
            has_unit = True
        elif "元" in txt:
            vals.append(float(val) / 1e8)
            has_unit = True
        else:
            vals.append(float(val))
    out = pd.Series(vals, index=s.index, dtype="Float64")
    if not has_unit:
        non = out.dropna()
        if not non.empty and float(non.abs().median()) > 1_000_000:
            out = out / 1e8
    return out.astype("Float64")


def parse_time_to_seconds_series(s: pd.Series) -> pd.Series:
    vals = []
    for x in s:
        if pd.isna(x):
            vals.append(pd.NA)
            continue
        txt = str(x).strip()
        m = re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", txt)
        if m:
            vals.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3) or 0))
            continue
        digits = "".join(re.findall(r"\d", txt))
        if 4 <= len(digits) <= 6:
            digits = digits.zfill(6)
            h, mi, sec = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
            if 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= sec <= 59:
                vals.append(h * 3600 + mi * 60 + sec)
                continue
        vals.append(_extract_float(txt))
    return pd.Series(vals, index=s.index, dtype="Float64")


def normalize_numeric_units(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    x = df.copy()
    for col in list(x.columns):
        try:
            if is_percent_col(col):
                x[col] = parse_percent_series(x[col])
            elif is_amount_col(col):
                x[col] = parse_amount_to_yi_series(x[col])
        except Exception:
            pass
    return x


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


def install_v7_6_runtime_patch():
    import pandas as _pd
    if not getattr(_pd.DataFrame, "_stock_robot_v76_sort_patch", False):
        old_sort_values = _pd.DataFrame.sort_values

        def sort_values_patched(self, by=None, *args, **kwargs):
            if by is None or kwargs.get("inplace", False):
                return old_sort_values(self, by=by, *args, **kwargs)
            by_list = list(by) if isinstance(by, (list, tuple)) else [by]
            work = self.copy()
            new_by, tmp_cols, changed = [], [], False
            for col in by_list:
                key = _make_sort_key(work, col)
                if key is not None and key.notna().sum() > 0:
                    tmp = f"__v76_sort_{str(col)}__"
                    i = 0
                    while tmp in work.columns:
                        i += 1
                        tmp = f"__v76_sort_{str(col)}_{i}__"
                    work[tmp] = key
                    tmp_cols.append(tmp)
                    new_by.append(tmp)
                    changed = True
                else:
                    new_by.append(col)
            if not changed:
                return old_sort_values(self, by=by, *args, **kwargs)
            res = old_sort_values(work, by=new_by if isinstance(by, (list, tuple)) else new_by[0], *args, **kwargs)
            return res.drop(columns=tmp_cols, errors="ignore")

        _pd.DataFrame.sort_values = sort_values_patched
        _pd.DataFrame._stock_robot_v76_sort_patch = True

    try:
        import streamlit as st
    except Exception:
        return
    if getattr(st, "_stock_robot_v76_display_patch", False):
        return
    old_dataframe = st.dataframe
    old_data_editor = getattr(st, "data_editor", None)

    def _column_config(df: pd.DataFrame):
        cfg = {}
        for col in df.columns:
            try:
                if is_percent_col(col):
                    cfg[col] = st.column_config.NumberColumn(str(col), format="%.2f%%")
                elif is_amount_col(col):
                    cfg[col] = st.column_config.NumberColumn(str(col), format="%.2f亿")
            except Exception:
                pass
        return cfg

    def dataframe_patched(data=None, *args, **kwargs):
        if isinstance(data, pd.DataFrame):
            data = normalize_numeric_units(data)
            user_cfg = kwargs.pop("column_config", None) or {}
            cfg = _column_config(data)
            cfg.update(user_cfg)
            kwargs["column_config"] = cfg
        return old_dataframe(data, *args, **kwargs)

    st.dataframe = dataframe_patched
    if old_data_editor is not None:
        def data_editor_patched(data=None, *args, **kwargs):
            if isinstance(data, pd.DataFrame):
                data = normalize_numeric_units(data)
                user_cfg = kwargs.pop("column_config", None) or {}
                cfg = _column_config(data)
                cfg.update(user_cfg)
                kwargs["column_config"] = cfg
            return old_data_editor(data, *args, **kwargs)
        st.data_editor = data_editor_patched
    st._stock_robot_v76_display_patch = True


def _is_stock_df(df: pd.DataFrame) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return False
    cols = set(map(str, df.columns))
    return (
        any(c in cols for c in ["代码", "股票代码", "证券代码", "code", "symbol"])
        and any(c in cols for c in ["名称", "股票名称", "证券简称", "name"])
        and any(c in cols for c in ["涨跌幅", "涨幅", "最新价", "现价"])
    )


def _standardize_code_name(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    if "代码" not in x.columns:
        for c in ["股票代码", "证券代码", "code", "symbol"]:
            if c in x.columns:
                x["代码"] = x[c]
                break
    if "名称" not in x.columns:
        for c in ["股票名称", "证券简称", "name"]:
            if c in x.columns:
                x["名称"] = x[c]
                break
    if "代码" in x.columns:
        x["代码"] = x["代码"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(x["代码"].astype(str)).str[-6:].str.zfill(6)
    return normalize_numeric_units(x)


def find_best_stock_df_from_globals(globs: dict) -> pd.DataFrame:
    candidates = []
    for name, obj in globs.items():
        if isinstance(obj, pd.DataFrame) and _is_stock_df(obj):
            candidates.append((len(obj), name, obj))
    if not candidates:
        return pd.DataFrame()
    candidates.sort(key=lambda x: x[0], reverse=True)
    return _standardize_code_name(candidates[0][2])


def rebuild_board_table(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns:
        return pd.DataFrame()
    tmp = df.copy()
    tmp = tmp[tmp[col].astype(str).str.len() > 0]
    if tmp.empty:
        return pd.DataFrame()
    if col == "所属概念":
        tmp[col] = tmp[col].astype(str).str.split("、")
        tmp = tmp.explode(col)
    if "成交额_亿" not in tmp.columns and "成交额" in tmp.columns:
        tmp["成交额_亿"] = parse_amount_to_yi_series(tmp["成交额"])
    agg = {"股票数": ("代码", "count")}
    if "涨跌幅" in tmp.columns:
        agg["平均涨幅"] = ("涨跌幅", "mean")
    if "成交额_亿" in tmp.columns:
        agg["板块成交额"] = ("成交额_亿", "sum")
    if "是否涨停" in tmp.columns:
        agg["涨停数"] = ("是否涨停", "sum")
    if "接近涨停" in tmp.columns:
        agg["接近涨停数"] = ("接近涨停", "sum")
    if "强势异动" in tmp.columns:
        agg["强势股数"] = ("强势异动", "sum")
    if "规则涨速" in tmp.columns:
        agg["平均5分钟涨速"] = ("规则涨速", "mean")
    g = tmp.groupby(col).agg(**agg).reset_index().rename(columns={col: "板块名称"})
    for c in ["平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速"]:
        if c not in g.columns:
            g[c] = 0
    g["板块联动分"] = (
        pd.to_numeric(g["平均涨幅"], errors="coerce").fillna(0).clip(lower=0) * 20
        + pd.to_numeric(g["涨停数"], errors="coerce").fillna(0) * 80
        + pd.to_numeric(g["接近涨停数"], errors="coerce").fillna(0) * 25
        + pd.to_numeric(g["强势股数"], errors="coerce").fillna(0) * 10
        + pd.to_numeric(g["板块成交额"], errors="coerce").fillna(0).clip(upper=300) * 0.5
        + pd.to_numeric(g["平均5分钟涨速"], errors="coerce").fillna(0).clip(lower=0) * 15
    )
    return g.sort_values("板块联动分", ascending=False).reset_index(drop=True)


def save_latest_watch_from_globals(globs: dict) -> None:
    df = find_best_stock_df_from_globals(globs)
    if df.empty:
        return
    df.to_csv(REPORT_DIR / "latest_watch_signals.csv", index=False, encoding="utf-8-sig")
    if "所属行业" in df.columns:
        industry = rebuild_board_table(df, "所属行业")
        if not industry.empty:
            industry.to_csv(REPORT_DIR / "latest_industry_board.csv", index=False, encoding="utf-8-sig")
    if "所属概念" in df.columns:
        concept = rebuild_board_table(df, "所属概念")
    elif "最强概念" in df.columns:
        concept = rebuild_board_table(df, "最强概念")
    else:
        concept = pd.DataFrame()
    if not concept.empty:
        concept.to_csv(REPORT_DIR / "latest_concept_board.csv", index=False, encoding="utf-8-sig")
