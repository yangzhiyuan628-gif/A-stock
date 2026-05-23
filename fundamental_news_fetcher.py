# -*- coding: utf-8 -*-
"""
公司基本面 + 新闻/公告上下文抓取模块。

替代龙虎榜逻辑：
- 不再读取龙虎榜；
- 优先补充公司主营业务、题材方向、新闻、公告、财务摘要；
- 若接口不可用，不崩溃，只提示“数据不足，不得编造”。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

try:
    from company_kb import search_company, company_context
except Exception:
    search_company = None
    company_context = None

def _safe(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\n", " ").replace("\r", " ").strip()

def _norm_code(x: Any) -> str:
    s = _safe(x)
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits.zfill(6) if digits else ""

def _pick_col(df: pd.DataFrame, keys: list[str]):
    for k in keys:
        if k in df.columns:
            return k
    for c in df.columns:
        cs = str(c).lower()
        for k in keys:
            if k.lower() in cs:
                return c
    return None

def _format_df(df: pd.DataFrame, title: str, limit: int = 8) -> list[str]:
    if df is None or df.empty:
        return []
    lines = [f"【{title}】"]
    for _, row in df.head(limit).iterrows():
        parts = []
        for c in list(df.columns)[:10]:
            v = _safe(row.get(c, ""))
            if v and v.lower() != "nan":
                parts.append(f"{c}:{v}")
        if parts:
            lines.append("- " + " | ".join(parts))
    return lines

def _try(fn, kwargs: dict) -> pd.DataFrame:
    try:
        df = fn(**kwargs)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def fetch_company_info_ak(code: str, name: str = "") -> list[str]:
    lines = []
    try:
        import akshare as ak
    except Exception as exc:
        return [f"AKShare不可用，无法读取公司资料：{exc}"]

    # 东方财富个股资料
    fn = getattr(ak, "stock_individual_info_em", None)
    if fn is not None:
        df = _try(fn, {"symbol": code})
        if not df.empty:
            lines.extend(_format_df(df, "东方财富个股资料", limit=12))

    # 同花顺主营介绍/公司概况，函数名随版本变动，做候选
    candidates = [
        ("stock_profile_cninfo", {"symbol": code}),
        ("stock_individual_basic_info_xq", {"symbol": code}),
        ("stock_zyjs_ths", {"symbol": code}),
    ]
    for fn_name, kwargs in candidates:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = _try(fn, kwargs)
        if not df.empty:
            lines.extend(_format_df(df, f"AKShare {fn_name}", limit=8))
            break

    return lines or ["当前未从AKShare获取到公司基本资料。"]

def fetch_stock_news_ak(code: str, name: str = "", limit: int = 8) -> list[str]:
    try:
        import akshare as ak
    except Exception as exc:
        return [f"AKShare不可用，无法读取新闻：{exc}"]

    lines = []
    candidates = [
        ("stock_news_em", {"symbol": code}),
        ("stock_news_em", {"symbol": name}),
    ]
    for fn_name, kwargs in candidates:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = _try(fn, kwargs)
        if not df.empty:
            title_col = _pick_col(df, ["标题", "新闻标题", "title", "内容"])
            time_col = _pick_col(df, ["发布时间", "时间", "日期", "datetime", "date"])
            source_col = _pick_col(df, ["文章来源", "来源", "source", "媒体"])
            lines.append(f"【个股新闻：{fn_name}】")
            for _, r in df.head(limit).iterrows():
                title = _safe(r.get(title_col, "")) if title_col else _safe(r.iloc[0])
                t = _safe(r.get(time_col, "")) if time_col else ""
                src = _safe(r.get(source_col, "")) if source_col else ""
                if title:
                    lines.append(f"- {t} {src}：{title}".strip())
            if len(lines) > 1:
                return lines
    return ["当前未获取到有效个股新闻；模型不得编造新闻。"]

def fetch_announcements_ak(code: str, limit: int = 8) -> list[str]:
    try:
        import akshare as ak
    except Exception:
        return []

    candidates = [
        ("stock_notice_report", {"symbol": code}),
        ("stock_zh_a_disclosure_report_cninfo", {"symbol": code}),
        ("stock_zh_a_disclosure_relation_cninfo", {"symbol": code}),
    ]
    for fn_name, kwargs in candidates:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = _try(fn, kwargs)
        if not df.empty:
            return _format_df(df, f"公告/披露：{fn_name}", limit=limit)
    return ["当前未获取到有效公告；涉及业务转型、合同、业绩、减持、监管等需人工核验。"]

def fetch_financial_ak(code: str, limit: int = 10) -> list[str]:
    try:
        import akshare as ak
    except Exception:
        return []

    lines = []
    candidates = [
        ("stock_financial_abstract", {"symbol": code}),
        ("stock_financial_abstract_ths", {"symbol": code}),
        ("stock_financial_analysis_indicator", {"symbol": code}),
    ]
    for fn_name, kwargs in candidates:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = _try(fn, kwargs)
        if not df.empty:
            lines.extend(_format_df(df, f"财务摘要：{fn_name}", limit=limit))
            return lines
    return ["当前未获取到有效财务摘要；基本面分析只能基于已知公司资料和公开新闻。"]

def fetch_fundamental_news_context(code: str = "", name: str = "", question: str = "", limit: int = 8) -> str:
    code = _norm_code(code)
    name = _safe(name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"基本面/新闻抓取时间: {now}",
        f"查询标的: {code} {name}".strip(),
    ]

    # 本地公司知识库，优先修正模型认知
    if search_company is not None and company_context is not None:
        rows = search_company(query=question, code=code, name=name, limit=5)
        lines.append("【本地公司知识库】")
        lines.append(company_context(rows))
    else:
        lines.append("【本地公司知识库】未加载 company_kb.py。")

    lines.extend(fetch_company_info_ak(code, name))
    lines.extend(fetch_stock_news_ak(code, name, limit=limit))
    lines.extend(fetch_announcements_ak(code, limit=limit))
    lines.extend(fetch_financial_ak(code, limit=6))

    lines.append("【短线使用原则】基本面/新闻用于识别题材、催化和风险，不等于买点；仍需结合情绪、板块联动、涨速、量能和风控。")
    return "\n".join(lines)

def fetch_market_news_context(limit: int = 12) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"市场新闻抓取时间: {now}"]
    try:
        import akshare as ak
    except Exception as exc:
        return f"AKShare不可用，无法读取市场新闻：{exc}"

    candidates = [
        ("stock_info_global_cls", {}),
        ("stock_info_global_futu", {}),
        ("stock_info_global_sina", {}),
    ]
    got = False
    for fn_name, kwargs in candidates:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = _try(fn, kwargs)
        if not df.empty:
            got = True
            lines.extend(_format_df(df, f"市场新闻：{fn_name}", limit=limit))
            break
    if not got:
        lines.append("当前未获取到市场新闻；模型不得编造新闻。")
    return "\n".join(lines)
