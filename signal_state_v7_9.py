# -*- coding: utf-8 -*-
"""
signal_state_v7_9.py

8502 / v7.9 信号状态机 + 事件日志

核心目标：
1. 把盯盘信号统一成标准状态；
2. 只在“状态变化”时记录事件；
3. 为后续邮件提醒、8501盘后复盘、信号回测提供稳定数据。

输出：
- reports/watch_signal_events.csv
- reports/latest_watch_states_v7_9.csv
- data/signal_state_v7_9.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
CONFIG_DIR = ROOT / "config"

DATA_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

STATE_PATH = DATA_DIR / "signal_state_v7_9.json"
EVENT_LOG_PATH = REPORT_DIR / "watch_signal_events.csv"
CURRENT_STATE_PATH = REPORT_DIR / "latest_watch_states_v7_9.csv"
CONFIG_PATH = CONFIG_DIR / "signal_state_v7_9.json"

STATE_ORDER = [
    "无信号",
    "低位异动",
    "半路观察",
    "半路触发",
    "接近涨停",
    "封板观察",
    "回封确认",
    "炸板风险",
    "风险回避",
    "失效",
]

BUY_STATES = {"半路触发", "接近涨停", "封板观察", "回封确认"}

DEFAULT_CONFIG = {
    "enabled": True,
    "min_amount_yi": 0.30,
    "low_pct_min": 2.0,
    "halfway_pct_min": 3.0,
    "halfway_pct_max": 8.5,
    "speed_watch_min": 0.35,
    "speed_trigger_min": 0.60,
    "near_limit_pct": 8.0,
    "limit_pct": 9.85,
    "risk_pct": -5.0,
    "risk_speed": -2.0,
    "log_no_signal_to_invalid": True,
    "max_log_rows": 200000,
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


def _norm_code(x: Any) -> str:
    d = "".join(re.findall(r"\d", str(x)))
    return d[-6:].zfill(6) if d else ""


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


def _to_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    return s in {"true", "1", "yes", "y", "是", "对", "触发"}


def _pick(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for n in names:
        if n in row.index:
            v = row.get(n)
            if not pd.isna(v):
                return v
    return default


def _is_stock_df(df: pd.DataFrame) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return False

    cols = set(map(str, df.columns))
    has_code = any(c in cols for c in ["代码", "股票代码", "证券代码", "code", "symbol"])
    has_name = any(c in cols for c in ["名称", "股票名称", "证券简称", "name"])
    has_signal = any(c in cols for c in ["涨跌幅", "涨幅", "最新价", "买卖状态", "多空状态"])
    return has_code and has_name and has_signal


def standardize_df(df: pd.DataFrame) -> pd.DataFrame:
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

    numeric_cols = [
        "最新价", "涨跌幅", "涨速", "5分钟涨速", "规则涨速", "成交额_亿",
        "换手率", "行业涨幅", "概念涨幅", "个股板块联动分", "距涨停幅度",
    ]
    for c in numeric_cols:
        if c in x.columns:
            x[c] = x[c].map(_to_float)

    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    return x


def find_watch_df_from_globals(globs: dict) -> pd.DataFrame:
    preferred = [
        "signal_df",
        "watch_df",
        "df",
        "main",
        "main_df",
        "data",
        "rank_df",
        "pool",
        "today_pool",
        "limit_pool",
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
        return standardize_df(candidates[0][2])

    # 兜底读取 8502 快照
    for p in [
        REPORT_DIR / "latest_watch_signals.csv",
        REPORT_DIR / "realtime_last_snapshot.csv",
        REPORT_DIR / "watch_fallback_cache.csv",
    ]:
        if p.exists():
            try:
                return standardize_df(pd.read_csv(p, dtype={"代码": str}))
            except Exception:
                pass

    return pd.DataFrame()


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_signal_state(row: pd.Series, cfg: dict | None = None) -> tuple[str, str]:
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}

    pct = _to_float(_pick(row, ["涨跌幅", "涨幅"], 0))
    speed = _to_float(_pick(row, ["规则涨速", "5分钟涨速", "涨速"], 0))
    amount = _to_float(_pick(row, ["成交额_亿", "成交额"], 0))

    state_text = " ".join(
        _safe_str(row.get(c, ""))
        for c in ["买卖状态", "多空状态", "实时信号", "操作提示", "信号", "买点规则"]
        if c in row.index
    )

    is_limit = _to_bool(row.get("是否涨停", False)) or pct >= float(cfg["limit_pct"])
    near_limit = _to_bool(row.get("接近涨停", False)) or pct >= float(cfg["near_limit_pct"])
    halfway_bool = _to_bool(row.get("半路触发", False))
    board_bool = _to_bool(row.get("打板观察", False))

    # 1. 明确风险优先
    if any(k in state_text for k in ["风险", "回避", "卖出", "跌停", "破位", "清仓"]):
        return "风险回避", f"状态文本含风险词：{state_text[:80]}"

    if pct <= float(cfg["risk_pct"]) or speed <= float(cfg["risk_speed"]):
        return "风险回避", f"涨幅/速度风险：涨幅{pct:.2f}%，速度{speed:.2f}%"

    # 2. 炸板/回封
    if any(k in state_text for k in ["炸板", "开板", "封板失败"]):
        return "炸板风险", f"状态文本提示炸板/开板：{state_text[:80]}"

    if "回封" in state_text:
        return "回封确认", f"状态文本提示回封：{state_text[:80]}"

    # 3. 封板/接近涨停
    if is_limit or board_bool or any(k in state_text for k in ["打板", "排板", "封板观察", "封单"]):
        return "封板观察", f"封板/排板观察：涨幅{pct:.2f}%，成交额{amount:.2f}亿"

    if near_limit or "接近涨停" in state_text:
        return "接近涨停", f"接近高位触发：涨幅{pct:.2f}%，速度{speed:.2f}%"

    # 4. 半路
    if halfway_bool or "半路买点" in state_text or (
        float(cfg["halfway_pct_min"]) <= pct <= float(cfg["halfway_pct_max"])
        and speed >= float(cfg["speed_trigger_min"])
        and amount >= float(cfg["min_amount_yi"])
    ):
        return "半路触发", f"半路条件触发：涨幅{pct:.2f}%，速度{speed:.2f}%，成交额{amount:.2f}亿"

    if "半路" in state_text or (
        float(cfg["halfway_pct_min"]) <= pct <= float(cfg["halfway_pct_max"])
        and speed >= float(cfg["speed_watch_min"])
    ):
        return "半路观察", f"半路观察：涨幅{pct:.2f}%，速度{speed:.2f}%"

    # 5. 低位异动
    if pct >= float(cfg["low_pct_min"]) and speed >= float(cfg["speed_watch_min"]) and amount >= float(cfg["min_amount_yi"]):
        return "低位异动", f"低位异动：涨幅{pct:.2f}%，速度{speed:.2f}%，成交额{amount:.2f}亿"

    return "无信号", f"未达到触发条件：涨幅{pct:.2f}%，速度{speed:.2f}%，成交额{amount:.2f}亿"


def build_event_row(row: pd.Series, from_state: str, to_state: str, reason: str) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "timestamp": now,
        "代码": _norm_code(row.get("代码", "")),
        "名称": _safe_str(row.get("名称", "")),
        "from_state": from_state or "无信号",
        "to_state": to_state,
        "reason": reason,
        "最新价": _to_float(row.get("最新价", 0)),
        "涨跌幅": _to_float(_pick(row, ["涨跌幅", "涨幅"], 0)),
        "规则涨速": _to_float(_pick(row, ["规则涨速", "5分钟涨速", "涨速"], 0)),
        "成交额_亿": _to_float(_pick(row, ["成交额_亿", "成交额"], 0)),
        "换手率": _to_float(row.get("换手率", 0)),
        "所属行业": _safe_str(row.get("所属行业", "")),
        "最强概念": _safe_str(_pick(row, ["最强概念", "所属概念"], "")),
        "买卖状态": _safe_str(_pick(row, ["买卖状态", "多空状态"], "")),
        "邮件候选": to_state in BUY_STATES,
        "状态等级": STATE_ORDER.index(to_state) if to_state in STATE_ORDER else 0,
    }


def append_events(events: list[dict], max_log_rows: int = 200000) -> None:
    if not events:
        return

    new = pd.DataFrame(events)

    if EVENT_LOG_PATH.exists():
        try:
            old = pd.read_csv(EVENT_LOG_PATH, dtype={"代码": str})
            out = pd.concat([old, new], ignore_index=True).tail(int(max_log_rows))
        except Exception:
            out = new
    else:
        out = new

    out.to_csv(EVENT_LOG_PATH, index=False, encoding="utf-8-sig")


def process_signal_state_machine_v7_9(globs: dict | None = None) -> tuple[pd.DataFrame, str]:
    cfg = load_config()

    if not cfg.get("enabled", True):
        return pd.DataFrame(), "v7.9 状态机未启用。"

    globs = globs or {}
    df = find_watch_df_from_globals(globs)

    if df.empty:
        return pd.DataFrame(), "未找到盯盘股票池。"

    prev_state = load_state()
    new_state: dict[str, dict] = {}
    events: list[dict] = []
    current_rows: list[dict] = []

    for _, row in df.iterrows():
        code = _norm_code(row.get("代码", ""))
        if not code:
            continue

        name = _safe_str(row.get("名称", ""))
        classified, reason = classify_signal_state(row, cfg)

        old_record = prev_state.get(code, {})
        old_state = old_record.get("state", "无信号")

        event_state = classified
        should_log = False

        # 从有效状态掉回无信号，记录一次“失效”
        if classified == "无信号" and old_state not in {"", "无信号", "失效"}:
            if cfg.get("log_no_signal_to_invalid", True):
                event_state = "失效"
                should_log = True
                reason = f"原状态 {old_state} 已失效；当前未达到触发条件。"
            saved_state = "无信号"
        else:
            saved_state = classified
            if classified != "无信号" and classified != old_state:
                should_log = True

        if should_log:
            events.append(build_event_row(row, old_state, event_state, reason))

        new_state[code] = {
            "name": name,
            "state": saved_state,
            "reason": reason,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        current = dict(row)
        current["标准状态"] = saved_state
        current["状态原因"] = reason
        current["邮件候选"] = saved_state in BUY_STATES
        current["状态等级"] = STATE_ORDER.index(saved_state) if saved_state in STATE_ORDER else 0
        current_rows.append(current)

    save_state(new_state)

    current_df = pd.DataFrame(current_rows)
    if not current_df.empty:
        current_df.to_csv(CURRENT_STATE_PATH, index=False, encoding="utf-8-sig")

    append_events(events, max_log_rows=int(cfg.get("max_log_rows", 200000)))

    event_df = pd.DataFrame(events)
    msg = f"v7.9 状态机完成：当前股票 {len(current_df)} 只，本轮新事件 {len(event_df)} 条。"
    return event_df, msg


def load_event_log(tail: int = 500) -> pd.DataFrame:
    if not EVENT_LOG_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(EVENT_LOG_PATH, dtype={"代码": str})
        return df.tail(tail).copy()
    except Exception:
        return pd.DataFrame()


def load_current_states() -> pd.DataFrame:
    if not CURRENT_STATE_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(CURRENT_STATE_PATH, dtype={"代码": str})
    except Exception:
        return pd.DataFrame()


def render_signal_events_panel_v7_9(globs: dict | None = None) -> None:
    import streamlit as st

    cfg = load_config()

    with st.expander("v7.9 信号状态机 / 事件日志", expanded=False):
        st.caption("统一低位异动、半路观察、半路触发、接近涨停、封板观察、回封确认、炸板风险、失效等状态。只在状态变化时记录事件。")

        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            cfg["enabled"] = st.checkbox("启用状态机", value=bool(cfg.get("enabled", True)), key="v79_state_enabled")
        with c2:
            cfg["min_amount_yi"] = st.number_input("最低成交额（亿）", 0.0, 200.0, float(cfg.get("min_amount_yi", 0.30)), 0.10, key="v79_min_amount")
        with c3:
            cfg["speed_trigger_min"] = st.number_input("半路触发速度阈值 %", -20.0, 20.0, float(cfg.get("speed_trigger_min", 0.60)), 0.10, key="v79_speed_trigger")
        with c4:
            cfg["near_limit_pct"] = st.number_input("接近高位阈值 %", 0.0, 30.0, float(cfg.get("near_limit_pct", 8.0)), 0.10, key="v79_near_limit")

        b1, b2, b3 = st.columns([1, 1, 2])
        with b1:
            if st.button("保存状态机设置", key="v79_save_cfg"):
                save_config(cfg)
                st.success("已保存到 config/signal_state_v7_9.json。")
        with b2:
            if st.button("立即运行状态机", key="v79_run_now"):
                ev, msg = process_signal_state_machine_v7_9(globs or {})
                st.success(msg)

        current = load_current_states()
        events = load_event_log(tail=500)

        if not current.empty:
            valid = current[~current["标准状态"].astype(str).isin(["无信号"])].copy() if "标准状态" in current.columns else current.copy()

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("当前有效状态", len(valid))
            if "邮件候选" in current.columns:
                m2.metric("邮件候选", int(current["邮件候选"].astype(str).str.lower().isin(["true", "1", "是"]).sum()))
            else:
                m2.metric("邮件候选", 0)
            if not events.empty:
                today = datetime.now().strftime("%Y-%m-%d")
                m3.metric("今日事件", int(events["timestamp"].astype(str).str.startswith(today).sum()))
            else:
                m3.metric("今日事件", 0)
            m4.metric("累计事件", len(events))

            st.markdown("**当前有效信号状态**")
            cols = [c for c in [
                "代码", "名称", "标准状态", "状态原因", "最新价", "涨跌幅", "规则涨速",
                "成交额_亿", "所属行业", "最强概念", "买卖状态", "邮件候选"
            ] if c in valid.columns]
            if cols:
                valid = valid.sort_values(["状态等级", "涨跌幅"], ascending=[False, False], na_position="last") if "状态等级" in valid.columns and "涨跌幅" in valid.columns else valid
                st.dataframe(valid[cols].head(200), hide_index=True, use_container_width=True, height=320)
            else:
                st.info("当前无有效状态。")
        else:
            st.info("还没有生成 latest_watch_states_v7_9.csv。请刷新行情或点击“立即运行状态机”。")

        st.markdown("**最近事件日志**")
        if events.empty:
            st.info("暂无事件日志。")
        else:
            cols = [c for c in [
                "timestamp", "代码", "名称", "from_state", "to_state", "reason", "最新价",
                "涨跌幅", "规则涨速", "成交额_亿", "所属行业", "最强概念", "邮件候选"
            ] if c in events.columns]
            st.dataframe(events[cols].sort_values("timestamp", ascending=False).head(300), hide_index=True, use_container_width=True, height=360)

            st.download_button(
                "下载事件日志 CSV",
                data=events.to_csv(index=False).encode("utf-8-sig"),
                file_name="watch_signal_events_tail.csv",
                mime="text/csv",
                key="v79_download_events",
            )

        if st.button("清空事件日志和状态缓存", key="v79_clear_events"):
            if EVENT_LOG_PATH.exists():
                EVENT_LOG_PATH.unlink()
            if CURRENT_STATE_PATH.exists():
                CURRENT_STATE_PATH.unlink()
            if STATE_PATH.exists():
                STATE_PATH.unlink()
            st.success("已清空 v7.9 事件日志和状态缓存。")
            st.rerun()
