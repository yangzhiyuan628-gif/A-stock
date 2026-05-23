# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
from typing import Any
import pandas as pd

def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\n", " ").replace("\r", " ").strip()

def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _format_news_df(df: pd.DataFrame, limit: int = 8) -> list[str]:
    if df is None or df.empty:
        return []
    title_col = _pick_col(df, ["标题", "新闻标题", "title", "公告标题", "内容", "summary"])
    time_col = _pick_col(df, ["发布时间", "时间", "日期", "公告日期", "datetime", "date", "time"])
    source_col = _pick_col(df, ["文章来源", "来源", "source", "媒体"])
    lines = []
    for _, row in df.head(limit).iterrows():
        title = _safe_str(row.get(title_col, "")) if title_col else _safe_str(row.iloc[0])
        t = _safe_str(row.get(time_col, "")) if time_col else ""
        src = _safe_str(row.get(source_col, "")) if source_col else ""
        if title:
            lines.append(f"- {t} {src}：{title}".strip() if (t or src) else f"- {title}")
    return lines

def try_akshare_stock_news(code: str, name: str, limit: int = 8) -> list[str]:
    lines = []
    try:
        import akshare as ak
    except Exception as exc:
        return [f"AKShare 未安装或不可用：{exc}"]

    candidates = [
        ("stock_news_em", {"symbol": code}),
        ("stock_news_em", {"symbol": name}),
        ("stock_individual_info_em", {"symbol": code}),
    ]
    for fn_name, kwargs in candidates:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        try:
            df = fn(**kwargs)
            if isinstance(df, pd.DataFrame) and not df.empty:
                got = _format_news_df(df, limit=limit)
                if got:
                    return [f"AKShare {fn_name}："] + got[:limit]
        except Exception:
            continue
    return []

def try_akshare_announcements(code: str, limit: int = 8) -> list[str]:
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
        try:
            df = fn(**kwargs)
            if isinstance(df, pd.DataFrame) and not df.empty:
                got = _format_news_df(df, limit=limit)
                if got:
                    return [f"AKShare {fn_name}："] + got[:limit]
        except Exception:
            continue
    return []

def keyword_catalyst_hint(name: str, industry: str, concept: str, question: str = "") -> list[str]:
    text = f"{name} {industry} {concept} {question}"
    theme_words = [
        "机器人", "算力", "AI", "人工智能", "芯片", "半导体", "PCB", "低空", "商业航天",
        "电力", "核电", "储能", "固态电池", "锂电", "光伏", "军工", "并购", "重组",
        "国企改革", "华为", "数据中心", "液冷", "CPO", "铜缆", "汽车", "无人驾驶"
    ]
    keys = [w for w in theme_words if w.lower() in text.lower()]
    if not keys:
        return ["当前未从名称/行业/概念中识别到明确热门题材关键词，需要外部新闻或公告确认。"]
    return [f"识别到可能相关题材关键词：{'、'.join(sorted(set(keys)))}；必须用新闻/公告/盘中板块发酵进一步确认，不能仅凭关键词出手。"]

def fetch_stock_news_context(code: str, name: str, industry: str = "", concept: str = "", question: str = "", limit: int = 8) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"新闻/公告抓取时间: {now}"]

    news = try_akshare_stock_news(code, name, limit=limit)
    ann = try_akshare_announcements(code, limit=limit)
    hints = keyword_catalyst_hint(name, industry, concept, question)

    lines.append("【个股新闻】")
    lines.extend(news[:limit] if news else ["当前未获取到有效个股新闻；新闻分析师不得编造新闻。"])

    lines.append("【公告/披露】")
    lines.extend(ann[:limit] if ann else ["当前未获取到有效公告；如涉及重组、业绩、减持、监管等，需要人工外部确认。"])

    lines.append("【题材核验提示】")
    lines.extend(hints)

    lines.append("【短线使用原则】新闻/公告只作为催化确认，不等于买点；仍需结合市场情绪、板块联动、个股地位、成交额、涨速和风险规则。")
    return "\n".join(lines)
