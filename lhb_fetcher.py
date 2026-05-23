# -*- coding: utf-8 -*-
"""
龙虎榜/游资席位数据抓取模块。

特点：
1. 优先使用 AKShare；
2. 兼容不同 AKShare 版本，函数不存在时自动跳过；
3. 所有异常兜底，不影响主页面运行；
4. 给大模型提供“龙虎榜上下文”，不编造席位。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\n", " ").replace("\r", " ").strip()


def _norm_code(x: Any) -> str:
    s = _safe_str(x)
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits.zfill(6) if digits else ""


def _try_call(fn, kwargs: dict) -> pd.DataFrame:
    try:
        df = fn(**kwargs)
        if isinstance(df, pd.DataFrame):
            return df
    except Exception:
        pass
    return pd.DataFrame()


def _filter_by_code_or_name(df: pd.DataFrame, code: str = "", name: str = "") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    code = _norm_code(code)
    name = _safe_str(name)

    mask = pd.Series(False, index=df.index)
    for col in df.columns:
        s = df[col].astype(str)
        if code:
            mask = mask | s.str.contains(code, regex=False, na=False)
        if name:
            mask = mask | s.str.contains(name, regex=False, na=False)

    out = df[mask].copy()
    return out if not out.empty else pd.DataFrame()


def _format_table(df: pd.DataFrame, title: str, limit: int = 12) -> list[str]:
    if df is None or df.empty:
        return []

    lines = [f"【{title}】"]
    cols = list(df.columns)
    for _, row in df.head(limit).iterrows():
        parts = []
        for c in cols[:10]:
            v = _safe_str(row.get(c, ""))
            if v and v.lower() != "nan":
                parts.append(f"{c}:{v}")
        if parts:
            lines.append("- " + " | ".join(parts))
    return lines


def fetch_lhb_context(code: str = "", name: str = "", lookback_days: int = 30, limit: int = 12) -> str:
    """
    返回单股龙虎榜上下文。
    """
    code = _norm_code(code)
    name = _safe_str(name)
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    lines = [
        f"龙虎榜抓取时间: {end.strftime('%Y-%m-%d %H:%M:%S')}",
        f"查询标的: {code} {name}".strip(),
        f"回看区间: {start_s} - {end_s}",
    ]

    try:
        import akshare as ak
    except Exception as exc:
        lines.append(f"AKShare 不可用，无法读取龙虎榜：{exc}")
        return "\n".join(lines)

    got_any = False

    # 1. 东方财富龙虎榜明细，常见函数
    fn = getattr(ak, "stock_lhb_detail_em", None)
    if fn is not None:
        df = _try_call(fn, {"start_date": start_s, "end_date": end_s})
        hit = _filter_by_code_or_name(df, code, name)
        if not hit.empty:
            got_any = True
            lines.extend(_format_table(hit, "东方财富龙虎榜个股上榜明细", limit=limit))

    # 2. 新浪每日龙虎榜，逐日扫描近 N 天，尽量不要过多请求
    fn = getattr(ak, "stock_lhb_detail_daily_sina", None)
    if fn is not None and not got_any:
        daily_hits = []
        for i in range(min(lookback_days, 15)):
            d = (end - timedelta(days=i)).strftime("%Y%m%d")
            df = _try_call(fn, {"date": d})
            hit = _filter_by_code_or_name(df, code, name)
            if not hit.empty:
                hit = hit.copy()
                hit["_查询日期"] = d
                daily_hits.append(hit)
        if daily_hits:
            got_any = True
            lines.extend(_format_table(pd.concat(daily_hits, ignore_index=True), "新浪每日龙虎榜命中记录", limit=limit))

    # 3. 尝试个股统计类函数
    candidate_calls = [
        ("stock_lhb_stock_statistic_em", {"symbol": "近一月"}),
        ("stock_lhb_jgmmtj_em", {"start_date": start_s, "end_date": end_s}),
        ("stock_lhb_hyyyb_em", {"start_date": start_s, "end_date": end_s}),
    ]
    for fn_name, kwargs in candidate_calls:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = _try_call(fn, kwargs)
        hit = _filter_by_code_or_name(df, code, name)
        if not hit.empty:
            got_any = True
            lines.extend(_format_table(hit, f"AKShare {fn_name} 命中记录", limit=min(8, limit)))

    if not got_any:
        lines.append("当前未在可用 AKShare 龙虎榜接口中命中该股。")
        lines.append("这不代表没有游资参与，只表示当前免费接口/时间窗口未抓到有效龙虎榜记录。")
        lines.append("若要做实盘级游资跟踪，建议后续接入更稳定的东方财富/同花顺龙虎榜接口或本地缓存。")

    lines.append("使用原则: 龙虎榜只作为资金风格和席位偏好的辅助确认，不能单独作为买点；仍需结合情绪、板块联动、封板质量、分时承接和风控。")
    return "\n".join(lines)


def fetch_lhb_market_context(lookback_days: int = 5, limit: int = 30) -> str:
    """
    返回最近市场龙虎榜概览，适合“游资复盘”按钮。
    """
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    lines = [
        f"市场龙虎榜概览抓取时间: {end.strftime('%Y-%m-%d %H:%M:%S')}",
        f"回看区间: {start_s} - {end_s}",
    ]

    try:
        import akshare as ak
    except Exception as exc:
        lines.append(f"AKShare 不可用，无法读取龙虎榜：{exc}")
        return "\n".join(lines)

    got_any = False

    fn = getattr(ak, "stock_lhb_detail_em", None)
    if fn is not None:
        df = _try_call(fn, {"start_date": start_s, "end_date": end_s})
        if not df.empty:
            got_any = True
            lines.extend(_format_table(df, "最近龙虎榜上榜明细概览", limit=limit))

    fn = getattr(ak, "stock_lhb_yybph_em", None)
    if fn is not None:
        df = _try_call(fn, {"symbol": "近一月"})
        if not df.empty:
            got_any = True
            lines.extend(_format_table(df, "营业部活跃度/席位排行", limit=15))

    if not got_any:
        lines.append("当前未获取到市场龙虎榜概览。可能是 AKShare 版本函数差异、网络问题或接口变动。")

    lines.append("复盘原则: 重点看反复上榜的活跃席位、机构/游资分歧、同题材多股上榜、买卖净额和次日溢价反馈。")
    return "\n".join(lines)
