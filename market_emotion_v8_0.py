# -*- coding: utf-8 -*-
"""
market_emotion_v8_0.py

8502 / v8.0 市场情绪温度计

目标：
1. 从 8502 当前股票池、v7.9 信号状态机、行业/概念联动表中读取数据；
2. 计算短线市场情绪分；
3. 给出情绪阶段：冰点 / 退潮 / 弱修复 / 混沌偏强 / 强修复 / 主升高热；
4. 输出可供 8501 盘后复盘读取的文件。

输出：
- reports/market_emotion_v8_0.csv
- reports/market_emotion_v8_0.json
- reports/market_emotion_history_v8_0.csv
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
CONFIG_DIR = ROOT / "config"

REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

EMOTION_NOW_CSV = REPORT_DIR / "market_emotion_v8_0.csv"
EMOTION_NOW_JSON = REPORT_DIR / "market_emotion_v8_0.json"
EMOTION_HISTORY_CSV = REPORT_DIR / "market_emotion_history_v8_0.csv"
CONFIG_PATH = CONFIG_DIR / "market_emotion_v8_0.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "history_max_rows": 50000,
    "limit_pct": 9.85,
    "near_limit_pct": 8.0,
    "strong_pct": 7.0,
    "active_pct": 3.0,
    "risk_pct": -5.0,
    "emotion_high": 80,
    "emotion_strong": 65,
    "emotion_mid": 50,
    "emotion_weak": 35,
    "emotion_cold": 20,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\n", " ").replace("\r", " ").strip()


def _to_float(x: Any, default: float = 0.0) -> float:
    if pd.isna(x):
        return default
    if isinstance(x, (int, float)):
        return float(x)

    s = str(x).strip().replace(",", "").replace("%", "")
    s = s.replace("－", "-").replace("—", "-")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return default
    try:
        val = float(m.group(0))
    except Exception:
        return default

    if "万" in s:
        return val / 10000.0
    if "亿" in s:
        return val
    if "元" in s:
        return val / 1e8
    return val


def _norm_code(x: Any) -> str:
    d = "".join(re.findall(r"\d", str(x)))
    return d[-6:].zfill(6) if d else ""


def _is_stock_df(df: pd.DataFrame) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return False
    cols = set(map(str, df.columns))
    has_code = any(c in cols for c in ["代码", "股票代码", "证券代码", "code", "symbol"])
    has_name = any(c in cols for c in ["名称", "股票名称", "证券简称", "name"])
    has_market = any(c in cols for c in ["涨跌幅", "涨幅", "最新价", "现价", "标准状态"])
    return has_code and has_name and has_market


def standardize_stock_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()

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
        x["代码"] = x["代码"].map(_norm_code)

    if "名称" not in x.columns:
        x["名称"] = x.get("代码", "")

    if "涨幅" in x.columns and "涨跌幅" not in x.columns:
        x["涨跌幅"] = x["涨幅"]

    if "现价" in x.columns and "最新价" not in x.columns:
        x["最新价"] = x["现价"]

    if "成交额_亿" not in x.columns and "成交额" in x.columns:
        x["成交额_亿"] = x["成交额"].map(_to_float)

    for c in [
        "最新价", "涨跌幅", "涨速", "5分钟涨速", "规则涨速", "成交额_亿",
        "换手率", "行业涨幅", "概念涨幅", "个股板块联动分", "状态等级",
    ]:
        if c in x.columns:
            x[c] = x[c].map(_to_float)

    if "代码" in x.columns:
        x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()

    return x


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030"]:
        try:
            return pd.read_csv(path, dtype={"代码": str}, encoding=enc)
        except Exception:
            pass
    try:
        return pd.read_csv(path, dtype={"代码": str})
    except Exception:
        return pd.DataFrame()


def find_watch_df(globs: dict | None = None) -> pd.DataFrame:
    globs = globs or {}
    preferred = [
        "signal_df",
        "watch_df",
        "df",
        "main",
        "main_df",
        "data",
        "rank_df",
        "pool",
    ]

    candidates = []

    for name in preferred:
        obj = globs.get(name)
        if isinstance(obj, pd.DataFrame) and _is_stock_df(obj):
            candidates.append((1000000 + len(obj), name, obj))

    for name, obj in globs.items():
        if isinstance(obj, pd.DataFrame) and _is_stock_df(obj):
            candidates.append((len(obj), name, obj))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return standardize_stock_df(candidates[0][2])

    # 优先读取 v7.9 当前状态，因为这里包含标准状态
    for p in [
        REPORT_DIR / "latest_watch_states_v7_9.csv",
        REPORT_DIR / "latest_watch_signals.csv",
        REPORT_DIR / "realtime_last_snapshot.csv",
        REPORT_DIR / "watch_fallback_cache.csv",
    ]:
        df = read_csv_safe(p)
        if not df.empty and _is_stock_df(df):
            return standardize_stock_df(df)

    return pd.DataFrame()


def read_board_df(name: str) -> pd.DataFrame:
    candidates = []
    if name == "industry":
        candidates = [REPORT_DIR / "latest_industry_board.csv"]
    elif name == "concept":
        candidates = [REPORT_DIR / "latest_concept_board.csv"]

    for p in candidates:
        df = read_csv_safe(p)
        if not df.empty:
            for c in ["平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速", "板块联动分"]:
                if c in df.columns:
                    df[c] = df[c].map(_to_float)
            return df
    return pd.DataFrame()


def read_event_log() -> pd.DataFrame:
    p = REPORT_DIR / "watch_signal_events.csv"
    df = read_csv_safe(p)
    if df.empty:
        return df
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for c in ["涨跌幅", "规则涨速", "成交额_亿", "状态等级"]:
        if c in df.columns:
            df[c] = df[c].map(_to_float)
    return df


def top_board_summary(board: pd.DataFrame, top_n: int = 5) -> tuple[float, str]:
    if board is None or board.empty:
        return 0.0, "暂无板块联动数据"

    x = board.copy()
    if "板块联动分" in x.columns:
        x = x.sort_values("板块联动分", ascending=False, na_position="last")
        top_score = float(pd.to_numeric(x["板块联动分"], errors="coerce").fillna(0).head(1).max())
    elif "平均涨幅" in x.columns:
        x = x.sort_values("平均涨幅", ascending=False, na_position="last")
        top_score = float(pd.to_numeric(x["平均涨幅"], errors="coerce").fillna(0).head(1).max()) * 20
    else:
        top_score = 0.0

    lines = []
    for _, r in x.head(top_n).iterrows():
        name = _safe_str(r.get("板块名称", r.get("所属行业", r.get("最强概念", ""))))
        avg = _to_float(r.get("平均涨幅", 0))
        zt = _to_float(r.get("涨停数", 0))
        strong = _to_float(r.get("强势股数", 0))
        link = _to_float(r.get("板块联动分", 0))
        lines.append(f"{name}: 平均涨幅{avg:.2f}%, 涨停{int(zt)}, 强势{int(strong)}, 联动分{link:.1f}")

    return top_score, "\n".join(lines) if lines else "暂无板块联动数据"


def classify_phase(score: float, cfg: dict) -> tuple[str, str]:
    if score >= float(cfg["emotion_high"]):
        return "主升高热", "市场处于高热或主升阶段，强势方向更容易获得溢价，但追高和炸板风险也上升。"
    if score >= float(cfg["emotion_strong"]):
        return "强修复", "短线情绪较强，适合重点关注主线、首板扩散和换手回封。"
    if score >= float(cfg["emotion_mid"]):
        return "混沌偏强", "市场存在局部机会，但题材轮动可能较快，需要重视板块联动和成交额。"
    if score >= float(cfg["emotion_weak"]):
        return "弱修复", "市场弱修复或轮动阶段，适合轻仓试错，优先低位异动和确定性更强的回封。"
    if score >= float(cfg["emotion_cold"]):
        return "退潮", "短线情绪偏弱，追高性价比下降，重点防守和等待新主线。"
    return "冰点", "市场接近冰点，风险偏高，但后续可能孕育修复点；适合观察，不宜激进。"


def compute_market_emotion(globs: dict | None = None) -> dict:
    cfg = load_config()
    df = find_watch_df(globs or {})
    industry = read_board_df("industry")
    concept = read_board_df("concept")
    events = read_event_log()

    now = datetime.now()
    today_s = now.strftime("%Y-%m-%d")

    if df.empty:
        result = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "emotion_score": 0.0,
            "emotion_phase": "无数据",
            "emotion_comment": "未读取到盯盘股票池。",
            "stock_count": 0,
        }
        save_emotion_result(result)
        return result

    pct = pd.to_numeric(df.get("涨跌幅", pd.Series(0, index=df.index)), errors="coerce").fillna(0)
    speed = pd.to_numeric(df.get("规则涨速", df.get("涨速", pd.Series(0, index=df.index))), errors="coerce").fillna(0)
    amount = pd.to_numeric(df.get("成交额_亿", pd.Series(0, index=df.index)), errors="coerce").fillna(0)

    stock_count = int(len(df))
    avg_pct = float(pct.mean()) if stock_count else 0.0
    median_pct = float(pct.median()) if stock_count else 0.0
    up_count = int((pct > 0).sum())
    down_count = int((pct < 0).sum())
    active_count = int((pct >= float(cfg["active_pct"])).sum())
    strong_count = int((pct >= float(cfg["strong_pct"])).sum())
    limit_count = int((pct >= float(cfg["limit_pct"])).sum())
    near_limit_count = int((pct >= float(cfg["near_limit_pct"])).sum())
    risk_count = int((pct <= float(cfg["risk_pct"])).sum())
    speed_strong_count = int((speed >= 0.8).sum())
    amount_sum = float(amount.sum())

    buy_state_count = 0
    risk_state_count = 0
    valid_state_count = 0

    if "标准状态" in df.columns:
        state = df["标准状态"].astype(str)
        buy_state_count = int(state.isin(["半路触发", "接近涨停", "封板观察", "回封确认"]).sum())
        risk_state_count = int(state.isin(["炸板风险", "风险回避", "失效"]).sum())
        valid_state_count = int((state != "无信号").sum())
    elif "买卖状态" in df.columns:
        s = df["买卖状态"].astype(str)
        buy_state_count = int(s.str.contains("半路|买点|打板|排板|回封|接近涨停", regex=True, na=False).sum())
        risk_state_count = int(s.str.contains("风险|回避|卖出|炸板", regex=True, na=False).sum())
        valid_state_count = int((s != "观察").sum())

    today_events = pd.DataFrame()
    if not events.empty and "timestamp" in events.columns:
        today_events = events[events["timestamp"].astype(str).str.startswith(today_s)].copy()

    event_count_today = int(len(today_events))
    buy_event_today = 0
    risk_event_today = 0
    fail_event_today = 0

    if not today_events.empty and "to_state" in today_events.columns:
        to_state = today_events["to_state"].astype(str)
        buy_event_today = int(to_state.isin(["半路触发", "接近涨停", "封板观察", "回封确认"]).sum())
        risk_event_today = int(to_state.isin(["炸板风险", "风险回避"]).sum())
        fail_event_today = int(to_state.isin(["失效"]).sum())

    industry_score, industry_text = top_board_summary(industry, top_n=5)
    concept_score, concept_text = top_board_summary(concept, top_n=5)
    board_score = max(industry_score, concept_score)

    # 情绪分：0-100，偏短线视角
    score = 50.0

    # 个股强度
    score += min(18.0, limit_count * 2.2)
    score += min(12.0, near_limit_count * 0.8)
    score += min(12.0, strong_count / max(stock_count, 1) * 100 * 0.8)
    score += min(8.0, active_count / max(stock_count, 1) * 100 * 0.25)
    score += max(-10.0, min(10.0, avg_pct * 6.0))
    score += min(8.0, speed_strong_count / max(stock_count, 1) * 100 * 0.35)

    # 状态机与买点
    score += min(10.0, buy_state_count * 1.2)
    score += min(6.0, buy_event_today * 0.8)
    score += min(8.0, valid_state_count / max(stock_count, 1) * 100 * 0.25)

    # 板块联动
    score += min(12.0, board_score / 60.0)

    # 风险惩罚
    score -= min(15.0, risk_count * 1.8)
    score -= min(12.0, risk_state_count * 1.3)
    score -= min(8.0, risk_event_today * 1.0)
    score -= min(6.0, fail_event_today * 0.8)
    score -= min(8.0, down_count / max(stock_count, 1) * 100 * 0.08)

    score = max(0.0, min(100.0, round(score, 2)))
    phase, comment = classify_phase(score, cfg)

    # 主线判断
    if board_score >= 300:
        mainline = "主线强"
    elif board_score >= 180:
        mainline = "主线初现"
    elif board_score >= 100:
        mainline = "轮动偏强"
    else:
        mainline = "主线不清晰"

    result = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "emotion_score": score,
        "emotion_phase": phase,
        "emotion_comment": comment,
        "mainline_status": mainline,
        "stock_count": stock_count,
        "avg_pct": round(avg_pct, 4),
        "median_pct": round(median_pct, 4),
        "up_count": up_count,
        "down_count": down_count,
        "active_count": active_count,
        "strong_count": strong_count,
        "limit_count": limit_count,
        "near_limit_count": near_limit_count,
        "risk_count": risk_count,
        "speed_strong_count": speed_strong_count,
        "amount_sum_yi": round(amount_sum, 4),
        "valid_state_count": valid_state_count,
        "buy_state_count": buy_state_count,
        "risk_state_count": risk_state_count,
        "event_count_today": event_count_today,
        "buy_event_today": buy_event_today,
        "risk_event_today": risk_event_today,
        "fail_event_today": fail_event_today,
        "top_industry_summary": industry_text,
        "top_concept_summary": concept_text,
        "board_score": round(board_score, 4),
    }

    save_emotion_result(result, max_rows=int(cfg.get("history_max_rows", 50000)))
    return result


def save_emotion_result(result: dict, max_rows: int = 50000) -> None:
    EMOTION_NOW_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([result]).to_csv(EMOTION_NOW_CSV, index=False, encoding="utf-8-sig")

    new = pd.DataFrame([result])
    if EMOTION_HISTORY_CSV.exists():
        try:
            old = pd.read_csv(EMOTION_HISTORY_CSV)
            out = pd.concat([old, new], ignore_index=True).tail(max_rows)
        except Exception:
            out = new
    else:
        out = new
    out.to_csv(EMOTION_HISTORY_CSV, index=False, encoding="utf-8-sig")


def load_emotion_history(tail: int = 500) -> pd.DataFrame:
    if not EMOTION_HISTORY_CSV.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(EMOTION_HISTORY_CSV).tail(tail)
    except Exception:
        return pd.DataFrame()


def render_market_emotion_panel_v8_0(globs: dict | None = None) -> None:
    import streamlit as st

    cfg = load_config()

    with st.expander("v8.0 市场情绪温度计", expanded=True):
        st.caption("短线情绪分基于涨停/接近涨停/强势股/涨速/买点状态/事件日志/板块联动综合计算。")

        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            cfg["enabled"] = st.checkbox("启用情绪温度计", value=bool(cfg.get("enabled", True)), key="v80_enabled")
        with c2:
            cfg["strong_pct"] = st.number_input("强势涨幅阈值 %", 0.0, 30.0, float(cfg.get("strong_pct", 7.0)), 0.1, key="v80_strong_pct")
        with c3:
            cfg["near_limit_pct"] = st.number_input("接近高位阈值 %", 0.0, 30.0, float(cfg.get("near_limit_pct", 8.0)), 0.1, key="v80_near_limit")
        with c4:
            cfg["risk_pct"] = st.number_input("风险跌幅阈值 %", -30.0, 0.0, float(cfg.get("risk_pct", -5.0)), 0.1, key="v80_risk_pct")

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button("保存情绪参数", key="v80_save_cfg"):
                save_config(cfg)
                st.success("已保存到 config/market_emotion_v8_0.json。")
        with b2:
            if st.button("立即计算情绪", key="v80_compute_now"):
                result = compute_market_emotion(globs or {})
                st.success(f"已计算：{result.get('emotion_phase')} / {result.get('emotion_score')}")

        result = compute_market_emotion(globs or {}) if cfg.get("enabled", True) else {}

        if not result or result.get("emotion_phase") == "无数据":
            st.warning("未读取到有效股票池。请先刷新 8502 行情或运行 v7.9 状态机。")
            return

        score = float(result.get("emotion_score", 0))
        phase = result.get("emotion_phase", "")
        mainline = result.get("mainline_status", "")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("情绪分", f"{score:.1f}")
        m2.metric("情绪阶段", phase)
        m3.metric("主线状态", mainline)
        m4.metric("涨停/接近", f"{int(result.get('limit_count', 0))}/{int(result.get('near_limit_count', 0))}")
        m5.metric("买点状态", int(result.get("buy_state_count", 0)))

        # 进度条
        st.progress(min(1.0, max(0.0, score / 100.0)), text=f"{phase}：{result.get('emotion_comment', '')}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("强势股", int(result.get("strong_count", 0)))
        c2.metric("活跃股", int(result.get("active_count", 0)))
        c3.metric("风险股", int(result.get("risk_count", 0)))
        c4.metric("今日事件", int(result.get("event_count_today", 0)))

        with st.expander("情绪计算明细", expanded=False):
            detail_cols = [
                "stock_count", "avg_pct", "median_pct", "up_count", "down_count",
                "active_count", "strong_count", "limit_count", "near_limit_count",
                "risk_count", "speed_strong_count", "valid_state_count",
                "buy_state_count", "risk_state_count", "event_count_today",
                "buy_event_today", "risk_event_today", "fail_event_today",
                "amount_sum_yi", "board_score",
            ]
            detail = {k: result.get(k) for k in detail_cols}
            st.dataframe(pd.DataFrame([detail]), hide_index=True, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**行业联动 Top**")
            st.text(result.get("top_industry_summary", "暂无"))
        with c2:
            st.markdown("**概念联动 Top**")
            st.text(result.get("top_concept_summary", "暂无"))

        hist = load_emotion_history(tail=300)
        if not hist.empty:
            with st.expander("情绪历史", expanded=False):
                show_cols = [c for c in ["timestamp", "emotion_score", "emotion_phase", "mainline_status", "limit_count", "near_limit_count", "buy_state_count", "risk_count"] if c in hist.columns]
                st.dataframe(hist[show_cols].sort_values("timestamp", ascending=False).head(200), hide_index=True, use_container_width=True, height=320)
                st.download_button(
                    "下载情绪历史 CSV",
                    data=hist.to_csv(index=False).encode("utf-8-sig"),
                    file_name="market_emotion_history_v8_0_tail.csv",
                    mime="text/csv",
                    key="v80_download_history",
                )
