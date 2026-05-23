# -*- coding: utf-8 -*-
"""
v7 A股主板非ST实盘监控：自定义买卖规则 + 大模型接口 + 邮件提醒

核心新增：
1. 用户可在页面自行设置半路买点、接近涨停、风险/卖出提醒规则；
2. 支持 5 分钟涨速：系统运行满 5 分钟后自动计算；
3. 涨速榜默认删除已经涨停股票；
4. 支持 DeepSeek/OpenAI-compatible API 查询个股情况；
5. 支持 SMTP 邮件提醒，达到买入/卖出/风险状态时发邮件；
6. 保留 pytdx 行情源、自动刷新、行业映射、数值排序。
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, time as dtime
from pathlib import Path

import pandas as pd
import streamlit as st
from network_guard_v8_3_2 import install_network_guard_patch, render_network_guard_panel
from web_research_v8_3_2 import install_web_research_patch, render_web_research_panel
from realtime_logger_v8_3_2 import log_current_snapshot_v8_3_2, render_realtime_logger_panel
from backup_manager_v8_3_2 import auto_backup_once_v8_3_2, render_backup_manager_panel
from always_online_ai_chat_v8_3_1 import install_always_online_patch, force_online_switches, render_always_online_status_panel
from skill_manager_v8_3 import ensure_default_skills, install_skill_context_patch, render_skills_system_panel, enrich_latest_signals_with_skills_v8_3
from email_smallcap_alert_v8_2_2 import render_email_smallcap_alert_panel_v8_2_2, process_smallcap_alerts_v8_2_2
from kobe_rule_attribution_v8_2_1 import render_kobe_rule_panel_v8_2_1, process_kobe_rule_snapshot_v8_2_1, attribute_event_log_v8_2_1
from custom_rule_volume_v8_2_2 import render_volume_rule_panel_v8_2_2, process_volume_rule_snapshot_v8_2_2
from signal_effect_stats_v8_2 import render_signal_effect_stats_panel_v8_2, compute_and_save_signal_effects
from shared_image_vision import install_shared_vision_patch, render_shared_image_panel
from market_emotion_v8_0 import compute_market_emotion, render_market_emotion_panel_v8_0
from signal_state_v7_9 import process_signal_state_machine_v7_9, render_signal_events_panel_v7_9
from email_alert_v7_8 import render_email_alert_panel_v7_8, process_realtime_buy_alerts_v7_8
from watch_ai_chat_v7_7 import render_watch_ai_chat_v7_7
from watch_v7_6_runtime import install_v7_6_runtime_patch, save_latest_watch_from_globals
from env_loader import load_project_env
from news_fetcher import fetch_stock_news_context

from realtime_core import get_realtime_universe, force_no_proxy_env
from alert_utils import send_email_alert
from llm_client import ask_llm_stock


try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "reports"
CONFIG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

RULE_PATH = CONFIG_DIR / "trading_rules.json"
PRICE_HISTORY_PATH = REPORT_DIR / "realtime_price_history.csv"


DEFAULT_RULES = {
    "halfway": {
        "enabled": True,
        "min_pct": 3.0,
        "max_pct": 8.0,
        "min_speed5": 0.50,
        "min_amount_yi": 0.50,
        "min_sector_strong": 3,
        "min_sector_limit": 0,
        "require_bullish_flow": False,
    },
    "near_limit": {
        "enabled": True,
        "min_pct": 8.0,
        "min_speed5": 0.10,
        "min_amount_yi": 0.50,
        "min_sector_strong": 3,
        "min_sector_limit": 1,
        "require_bullish_flow": False,
    },
    "risk_sell": {
        "enabled": True,
        "max_pct": -3.0,
        "max_speed5": -1.0,
        "min_amount_yi": 0.30,
    },
    "filters": {
        "exclude_new": True,
        "exclude_limit_in_speed_rank": True,
        "min_amount_yi_global": 0.30,
    },
}


load_project_env()

install_v7_6_runtime_patch()

install_shared_vision_patch(app_name="8502")

ensure_default_skills()
install_skill_context_patch()

install_always_online_patch()
force_online_switches()

auto_backup_once_v8_3_2('auto_before_v832_8502')
install_network_guard_patch()
install_web_research_patch()

st.set_page_config(page_title="A股主板非ST实盘监控 8502", layout="wide")


def deep_update(base: dict, new: dict) -> dict:
    out = dict(base)
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = v
    return out


def load_rules() -> dict:
    if RULE_PATH.exists():
        try:
            return deep_update(DEFAULT_RULES, json.loads(RULE_PATH.read_text(encoding="utf-8")))
        except Exception:
            return DEFAULT_RULES.copy()
    return DEFAULT_RULES.copy()


def save_rules(rules: dict) -> None:
    RULE_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(name: str, default):
    path = CONFIG_DIR / name
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def norm_code(x) -> str:
    s = str(x).strip()
    if "." in s:
        s = s.split(".")[0]
    return s.zfill(6)[-6:]


def is_cn_trading_time(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 5))


def mapping_status() -> dict:
    files = {
        "code_to_industry.json": CONFIG_DIR / "code_to_industry.json",
        "code_to_concepts.json": CONFIG_DIR / "code_to_concepts.json",
        "industry_pct.json": CONFIG_DIR / "industry_pct.json",
        "concept_pct.json": CONFIG_DIR / "concept_pct.json",
    }
    status = {}
    for name, path in files.items():
        if not path.exists():
            status[name] = {"exists": False, "items": 0}
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            status[name] = {"exists": True, "items": len(obj)}
        except Exception:
            status[name] = {"exists": True, "items": -1}
    return status


def enrich_boards(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "代码" in df.columns:
        df["代码"] = df["代码"].map(norm_code)

    code_to_industry = load_json("code_to_industry.json", {})
    code_to_concepts = load_json("code_to_concepts.json", {})
    industry_pct = load_json("industry_pct.json", {})
    concept_pct = load_json("concept_pct.json", {})

    df["所属行业"] = df["代码"].map(lambda c: code_to_industry.get(c, "未知"))
    df["行业涨幅"] = df["所属行业"].map(lambda x: industry_pct.get(x, pd.NA))

    def concepts_text(code):
        arr = code_to_concepts.get(code, [])
        if not arr:
            return ""
        return "、".join(arr[:8])

    def strongest_concept(code):
        arr = code_to_concepts.get(code, [])
        if not arr:
            return ""
        arr2 = sorted(arr, key=lambda x: float(concept_pct.get(x, -999)), reverse=True)
        return arr2[0] if arr2 else ""

    df["所属概念"] = df["代码"].map(concepts_text)
    df["最强概念"] = df["代码"].map(strongest_concept)
    df["概念涨幅"] = df["最强概念"].map(lambda x: concept_pct.get(x, pd.NA) if x else pd.NA)
    df["主板块"] = df["最强概念"].where(df["最强概念"].astype(str).str.len() > 0, df["所属行业"])

    # 如果本地映射没有行业/概念指数涨幅，则用当前成分股平均涨幅近似
    try:
        if "所属行业" in df.columns and "涨跌幅" in df.columns:
            industry_avg = pd.to_numeric(df["涨跌幅"], errors="coerce").groupby(df["所属行业"]).transform("mean")
            df["行业涨幅"] = pd.to_numeric(df["行业涨幅"], errors="coerce").fillna(industry_avg)
        if "最强概念" in df.columns and "涨跌幅" in df.columns:
            concept_key = df["最强概念"].astype(str)
            concept_avg = pd.to_numeric(df["涨跌幅"], errors="coerce").groupby(concept_key).transform("mean")
            df["概念涨幅"] = pd.to_numeric(df["概念涨幅"], errors="coerce").fillna(concept_avg)
    except Exception:
        pass

    return df


def update_speed5_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算 5 分钟涨速。
    系统运行不满 5 分钟时，该列可能为空；规则会退回使用行情源自带“涨速”。
    """
    df = df.copy()
    now = pd.Timestamp.now()

    cur = df[["代码", "最新价"]].copy()
    cur["代码"] = cur["代码"].astype(str).str.zfill(6)
    cur["最新价"] = pd.to_numeric(cur["最新价"], errors="coerce")
    cur["_ts"] = now

    if PRICE_HISTORY_PATH.exists():
        try:
            hist = pd.read_csv(PRICE_HISTORY_PATH, dtype={"代码": str})
            hist["_ts"] = pd.to_datetime(hist["_ts"], errors="coerce")
        except Exception:
            hist = pd.DataFrame(columns=["代码", "最新价", "_ts"])
    else:
        hist = pd.DataFrame(columns=["代码", "最新价", "_ts"])

    hist = pd.concat([hist, cur], ignore_index=True)
    hist = hist.dropna(subset=["代码", "最新价", "_ts"])
    hist = hist[hist["_ts"] >= now - pd.Timedelta(minutes=40)]
    hist.to_csv(PRICE_HISTORY_PATH, index=False, encoding="utf-8-sig")

    target = now - pd.Timedelta(minutes=5)
    prev = hist[hist["_ts"] <= target].sort_values("_ts").groupby("代码").tail(1)
    prev = prev[["代码", "最新价"]].rename(columns={"最新价": "_price_5m_ago"})

    df = df.merge(prev, on="代码", how="left")
    df["涨速5分钟"] = (pd.to_numeric(df["最新价"], errors="coerce") / pd.to_numeric(df["_price_5m_ago"], errors="coerce") - 1) * 100
    df.drop(columns=["_price_5m_ago"], inplace=True)
    df["规则涨速"] = pd.to_numeric(df["涨速5分钟"], errors="coerce").fillna(pd.to_numeric(df.get("涨速", 0), errors="coerce"))
    return df


def add_sector_counts(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    if "所属行业" in x.columns:
        industry_strong = x.groupby("所属行业")["强势异动"].sum().to_dict() if "强势异动" in x.columns else {}
        industry_limit = x.groupby("所属行业")["是否涨停"].sum().to_dict() if "是否涨停" in x.columns else {}
        x["行业强势数"] = x["所属行业"].map(industry_strong).fillna(0)
        x["行业涨停数"] = x["所属行业"].map(industry_limit).fillna(0)
    else:
        x["行业强势数"] = 0
        x["行业涨停数"] = 0

    if "最强概念" in x.columns:
        concept_strong = x.groupby("最强概念")["强势异动"].sum().to_dict() if "强势异动" in x.columns else {}
        concept_limit = x.groupby("最强概念")["是否涨停"].sum().to_dict() if "是否涨停" in x.columns else {}
        x["概念强势数"] = x["最强概念"].map(concept_strong).fillna(0)
        x["概念涨停数"] = x["最强概念"].map(concept_limit).fillna(0)
    else:
        x["概念强势数"] = 0
        x["概念涨停数"] = 0

    return x


def add_flow_state(df: pd.DataFrame) -> pd.DataFrame:
    """
    多空状态：
    - 若有主力净流入，用主力净流入判断；
    - pytdx 没有主力净流入时，用涨跌幅 + 5分钟涨速 + 成交额做近似判断。
    """
    x = df.copy()
    amount_yi = pd.to_numeric(x.get("成交额", 0), errors="coerce").fillna(0) / 1e8
    pct = pd.to_numeric(x.get("涨跌幅", 0), errors="coerce").fillna(0)
    speed5 = pd.to_numeric(x.get("规则涨速", 0), errors="coerce").fillna(0)
    main_flow = pd.to_numeric(x.get("主力净流入", pd.NA), errors="coerce")

    def state(i):
        mf = main_flow.iloc[i] if len(main_flow) > i else pd.NA
        if pd.notna(mf):
            if mf > 0:
                return "多方"
            if mf < 0:
                return "空方"
            return "中性"
        if pct.iloc[i] > 0 and speed5.iloc[i] > 0 and amount_yi.iloc[i] >= 0.3:
            return "多方近似"
        if pct.iloc[i] < 0 and speed5.iloc[i] < 0:
            return "空方近似"
        return "中性/未知"

    x["多空状态"] = [state(i) for i in range(len(x))]
    return x


def evaluate_custom_rules(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    x = df.copy()
    for col in ["涨跌幅", "规则涨速", "涨速5分钟", "涨速", "成交额", "行业涨幅", "概念涨幅", "距涨停幅度"]:
        if col in x.columns:
            x[col] = pd.to_numeric(x[col], errors="coerce")

    x["成交额_亿"] = pd.to_numeric(x.get("成交额", 0), errors="coerce").fillna(0) / 1e8
    x["是否新股"] = x["名称"].astype(str).str.startswith(("N", "C"))

    # 联动分
    x["个股板块联动分"] = (
        x["涨跌幅"].fillna(0).clip(lower=0) * 5
        + x["规则涨速"].fillna(0).clip(lower=0) * 8
        + x["行业涨幅"].fillna(0).clip(lower=0) * 4
        + x["概念涨幅"].fillna(0).clip(lower=0) * 5
        + x["行业强势数"].fillna(0) * 1.5
        + x["概念强势数"].fillna(0) * 2.0
        + x["行业涨停数"].fillna(0) * 5
        + x["概念涨停数"].fillna(0) * 6
        + x["成交额_亿"].rank(pct=True).fillna(0) * 8
    ).round(1)

    half = rules["halfway"]
    near = rules["near_limit"]
    risk = rules["risk_sell"]

    def bullish_ok(row, rule):
        if not rule.get("require_bullish_flow", False):
            return True
        return str(row.get("多空状态", "")).startswith("多方")

    def rule_name(row):
        pct = row.get("涨跌幅", 0) or 0
        spd = row.get("规则涨速", 0) or 0
        amt = row.get("成交额_亿", 0) or 0
        sector_strong = max(row.get("行业强势数", 0) or 0, row.get("概念强势数", 0) or 0)
        sector_limit = max(row.get("行业涨停数", 0) or 0, row.get("概念涨停数", 0) or 0)
        is_limit = bool(row.get("是否涨停", False))
        is_new = bool(row.get("是否新股", False))

        if rules["filters"].get("exclude_new", True) and is_new:
            return "新股：仅观察"

        if risk.get("enabled", True) and amt >= risk.get("min_amount_yi", 0.3):
            if pct <= risk.get("max_pct", -3.0) or spd <= risk.get("max_speed5", -1.0):
                return "卖出/风险提醒"

        if near.get("enabled", True):
            if (
                pct >= near.get("min_pct", 8.0)
                and spd >= near.get("min_speed5", 0.1)
                and amt >= near.get("min_amount_yi", 0.5)
                and sector_strong >= near.get("min_sector_strong", 3)
                and sector_limit >= near.get("min_sector_limit", 1)
                and bullish_ok(row, near)
            ):
                return "打板/排板观察" if is_limit else "接近涨停观察"

        if half.get("enabled", True):
            if (
                half.get("min_pct", 3.0) <= pct <= half.get("max_pct", 8.0)
                and spd >= half.get("min_speed5", 0.5)
                and amt >= half.get("min_amount_yi", 0.5)
                and sector_strong >= half.get("min_sector_strong", 3)
                and sector_limit >= half.get("min_sector_limit", 0)
                and bullish_ok(row, half)
            ):
                return "半路买点观察"

        if pct >= 5 and sector_strong <= 1:
            return "谨慎：孤立拉升"
        if pct >= 3 and sector_strong >= 2:
            return "低位异动观察"
        return "观察"

    x["买卖状态"] = x.apply(rule_name, axis=1)

    def action(row):
        r = row.get("买卖状态", "")
        if r in ["打板/排板观察", "接近涨停观察"]:
            return "人工确认：封单、炸板、回封、板块助攻"
        if r == "半路买点观察":
            return "人工确认：分时承接，不追尖峰"
        if r == "卖出/风险提醒":
            return "检查持仓：跌速/跌幅触发风险"
        if r == "谨慎：孤立拉升":
            return "联动不足，不作为优先买点"
        return "等待确认"

    x["操作提示"] = x.apply(action, axis=1)
    return x.sort_values("个股板块联动分", ascending=False, na_position="last")


def rebuild_board_table(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if df.empty or by not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    for col in ["涨跌幅", "规则涨速", "成交额"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    group = work.groupby(by, dropna=False).agg(
        股票数=("代码", "count"),
        平均涨幅=("涨跌幅", "mean"),
        板块成交额=("成交额", "sum"),
        涨停数=("是否涨停", "sum"),
        接近涨停数=("接近涨停", "sum"),
        强势股数=("强势异动", "sum"),
        平均5分钟涨速=("规则涨速", "mean"),
    ).reset_index().rename(columns={by: "板块名称"})

    group["板块联动分"] = (
        group["涨停数"] * 30
        + group["接近涨停数"] * 15
        + group["强势股数"] * 5
        + group["平均涨幅"].fillna(0).clip(lower=0) * 2
        + group["平均5分钟涨速"].fillna(0).clip(lower=0) * 3
        + group["板块成交额"].rank(pct=True).fillna(0) * 10
    ).round(1)
    return group.sort_values("板块联动分", ascending=False, na_position="last")


def make_stock_context(row: pd.Series) -> str:
    fields = [
        "代码", "名称", "最新价", "涨跌幅", "涨速5分钟", "涨速", "成交额_亿",
        "多空状态", "所属行业", "行业涨幅", "最强概念", "概念涨幅", "所属概念",
        "行业强势数", "行业涨停数", "概念强势数", "概念涨停数",
        "买卖状态", "操作提示", "个股板块联动分"
    ]
    lines = []
    for f in fields:
        if f in row.index:
            lines.append(f"{f}: {row.get(f)}")
    return "\n".join(lines)


def build_alert_body(alert_df: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = ["代码", "名称", "涨跌幅", "规则涨速", "成交额_亿", "所属行业", "最强概念", "买卖状态", "操作提示"]
    cols = [c for c in cols if c in alert_df.columns]
    lines = [f"A股实盘监控提醒：{now}", ""]
    for _, row in alert_df.head(30).iterrows():
        lines.append(
            f"{row.get('代码')} {row.get('名称')} | "
            f"涨幅 {row.get('涨跌幅'):.2f}% | "
            f"5分钟/规则涨速 {row.get('规则涨速'):.2f}% | "
            f"成交额 {row.get('成交额_亿'):.2f}亿 | "
            f"{row.get('所属行业')} / {row.get('最强概念')} | "
            f"{row.get('买卖状态')} | {row.get('操作提示')}"
        )
    lines.append("")
    lines.append("本邮件只做信号提醒，不构成投资建议。")
    return "\n".join(lines)


# ---------------- Sidebar ----------------
rules = load_rules()

st.sidebar.title("监控设置")
source = st.sidebar.selectbox("行情源", ["auto", "eastmoney", "pytdx", "cache"], index=2)
top_n = st.sidebar.slider("榜单 Top N", 20, 200, 80, 10)

st.sidebar.divider()
st.sidebar.subheader("实时刷新")
# ===== v7.1 force stop refresh =====
if "force_stop_refresh" not in st.session_state:
    st.session_state.force_stop_refresh = False
if st.sidebar.button("停止实时刷新"):
    st.session_state.force_stop_refresh = True
    st.cache_data.clear()
    st.rerun()
if st.sidebar.button("恢复实时刷新"):
    st.session_state.force_stop_refresh = False
    st.cache_data.clear()
    st.rerun()
# ===== end v7.1 force stop refresh =====

auto_refresh = st.sidebar.checkbox("启用自动刷新", value=True)
interval_sec = st.sidebar.selectbox("刷新间隔", [5, 10, 15, 30, 60], index=2)
only_trading_time = st.sidebar.checkbox("仅交易时段自动刷新", value=True)
refresh = st.sidebar.button("立即刷新", type="primary")

now = datetime.now()
trading_now = is_cn_trading_time(now)
auto_active = (not st.session_state.get("force_stop_refresh", False)) and auto_refresh and ((not only_trading_time) or trading_now)
auto_counter = 0
if auto_active:
    if st_autorefresh is not None:
        auto_counter = st_autorefresh(interval=interval_sec * 1000, key="realtime_auto_refresh_counter")
        st.sidebar.success(f"自动刷新中：每 {interval_sec} 秒一次")
    else:
        st.sidebar.warning("未安装 streamlit-autorefresh：pip install streamlit-autorefresh")
elif st.session_state.get("force_stop_refresh", False):
    st.sidebar.warning("已手动停止实时刷新。")
elif auto_refresh and only_trading_time and not trading_now:
    st.sidebar.info("当前不在A股交易时段，自动刷新暂停。")
st.sidebar.caption(f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

st.sidebar.divider()
st.sidebar.subheader("过滤")
rules["filters"]["exclude_new"] = st.sidebar.checkbox("排除 N/C 新股", value=rules["filters"].get("exclude_new", True))
rules["filters"]["exclude_limit_in_speed_rank"] = st.sidebar.checkbox("涨速榜删除已涨停股票", value=rules["filters"].get("exclude_limit_in_speed_rank", True))
rules["filters"]["min_amount_yi_global"] = st.sidebar.number_input("全局最低成交额（亿元）", value=float(rules["filters"].get("min_amount_yi_global", 0.30)), min_value=0.0, step=0.10)

st.sidebar.divider()
st.sidebar.subheader("代理/网络")
if st.sidebar.button("本进程禁用代理并刷新"):
    force_no_proxy_env()
    st.cache_data.clear()
    st.rerun()


# ---------------- Main ----------------
st.title("A股主板非ST实盘监控 v8.0.9.8.7")
st.caption("自定义买卖规则 + 5分钟涨速 + 涨速榜剔除涨停 + 大模型接口 + 邮件提醒。信号只做观察，不自动下单。")


@st.cache_data(ttl=3, show_spinner="正在获取实时行情...")
def load_data(_stamp: str, source: str, min_amount_yi: float):
    return get_realtime_universe(source=source, min_amount_yi=min_amount_yi)


if refresh:
    stamp = "manual_" + datetime.now().strftime("%Y%m%d%H%M%S%f")
elif auto_active and st_autorefresh is not None:
    stamp = f"auto_{auto_counter}_{datetime.now().strftime('%H%M%S')}"
else:
    stamp = "cached"

try:
    df, board_raw = load_data(stamp, source, rules["filters"]["min_amount_yi_global"])
except Exception:
    st.error("实时行情获取失败。通常是代理、网络或行情接口问题。")
    with st.expander("查看错误详情", expanded=True):
        st.code(traceback.format_exc(), language="python")
    st.stop()

if df.empty:
    st.warning("没有获取到行情数据。")
    st.stop()

df = enrich_boards(df)
df = update_speed5_history(df)
df = add_sector_counts(df)
df = add_flow_state(df)
signal_df = evaluate_custom_rules(df, rules)

if rules["filters"].get("exclude_new", True):
    signal_df = signal_df[~signal_df["名称"].astype(str).str.startswith(("N", "C"))].copy()

industry_board = rebuild_board_table(signal_df, "所属行业")
concept_board = rebuild_board_table(signal_df[signal_df["最强概念"].astype(str).str.len() > 0], "最强概念")

# numeric
NUMERIC_COLS = [
    "最新价", "涨跌幅", "涨速", "涨速5分钟", "规则涨速", "成交额", "换手率", "振幅",
    "距涨停幅度", "今开", "最高", "最低", "昨收", "流通市值", "总市值", "主力净流入",
    "股票数", "平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速",
    "行业涨幅", "概念涨幅", "行业强势数", "行业涨停数", "概念强势数", "概念涨停数",
    "个股板块联动分", "成交额_亿"
]
for table in [signal_df, industry_board, concept_board]:
    for col in NUMERIC_COLS:
        if isinstance(table, pd.DataFrame) and col in table.columns:
            table[col] = pd.to_numeric(table[col], errors="coerce")

data_source = signal_df["数据源"].dropna().astype(str).unique() if "数据源" in signal_df.columns else []
status_cols = st.columns([2, 1, 1])
status_cols[0].success(f"行情获取成功。数据源：{', '.join(data_source[:3])}；更新时间：{datetime.now().strftime('%H:%M:%S')}")
status_cols[1].metric("刷新模式", "自动" if auto_active else "手动/缓存")
status_cols[2].metric("刷新计数", int(auto_counter) if auto_active else 0)

# metrics
total = len(signal_df)
limit_up = int(signal_df.get("是否涨停", pd.Series(dtype=bool)).sum())
near_limit = int(signal_df.get("接近涨停", pd.Series(dtype=bool)).sum())
buy_count = int(signal_df["买卖状态"].isin(["半路买点观察", "接近涨停观察", "打板/排板观察"]).sum())
risk_count = int(signal_df["买卖状态"].isin(["卖出/风险提醒"]).sum())
avg_pct = pd.to_numeric(signal_df.get("涨跌幅", 0), errors="coerce").mean()

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("主板非ST数量", f"{total}")
m2.metric("涨停数", f"{limit_up}")
m3.metric("接近涨停", f"{near_limit}")
m4.metric("买点触发", f"{buy_count}")
m5.metric("风险触发", f"{risk_count}")
m6.metric("平均涨幅", f"{avg_pct:.2f}%")


def prepare_display_table(x: pd.DataFrame) -> pd.DataFrame:
    y = x.copy()
    for col in ["成交额", "流通市值", "总市值", "主力净流入", "板块成交额"]:
        if col in y.columns:
            y[col] = pd.to_numeric(y[col], errors="coerce") / 1e8
    for col in NUMERIC_COLS:
        if col in y.columns and col not in ["成交额", "流通市值", "总市值", "主力净流入", "板块成交额"]:
            y[col] = pd.to_numeric(y[col], errors="coerce")
    if "代码" in y.columns:
        y["代码"] = y["代码"].astype(str).str.zfill(6)
    return y


def get_column_config():
    return {
        "最新价": st.column_config.NumberColumn("最新价", format="%.2f"),
        "涨跌幅": st.column_config.NumberColumn("涨跌幅", format="%.2f%%"),
        "涨速": st.column_config.NumberColumn("涨速", format="%.2f%%"),
        "涨速5分钟": st.column_config.NumberColumn("5分钟涨速", format="%.2f%%"),
        "规则涨速": st.column_config.NumberColumn("规则涨速", format="%.2f%%"),
        "换手率": st.column_config.NumberColumn("换手率", format="%.2f%%"),
        "距涨停幅度": st.column_config.NumberColumn("距涨停幅度", format="%.2f%%"),
        "行业涨幅": st.column_config.NumberColumn("行业涨幅", format="%.2f%%"),
        "概念涨幅": st.column_config.NumberColumn("概念涨幅", format="%.2f%%"),
        "平均涨幅": st.column_config.NumberColumn("平均涨幅", format="%.2f%%"),
        "平均5分钟涨速": st.column_config.NumberColumn("平均5分钟涨速", format="%.2f%%"),
        "成交额": st.column_config.NumberColumn("成交额", format="%.2f亿"),
        "流通市值": st.column_config.NumberColumn("流通市值", format="%.2f亿"),
        "总市值": st.column_config.NumberColumn("总市值", format="%.2f亿"),
        "主力净流入": st.column_config.NumberColumn("主力净流入", format="%.2f亿"),
        "板块成交额": st.column_config.NumberColumn("板块成交额", format="%.2f亿"),
        "成交额_亿": st.column_config.NumberColumn("成交额_亿", format="%.2f"),
        "个股板块联动分": st.column_config.NumberColumn("个股板块联动分", format="%.1f"),
    }


column_config = get_column_config()

base_cols = [
    "代码", "名称", "最新价", "涨跌幅", "涨速5分钟", "涨速", "成交额", "换手率",
    "多空状态", "所属行业", "行业涨幅", "最强概念", "概念涨幅", "所属概念",
    "行业强势数", "行业涨停数", "概念强势数", "概念涨停数",
    "个股板块联动分", "买卖状态", "操作提示", "距涨停幅度", "是否涨停", "接近涨停", "数据源"
]
base_cols = [c for c in base_cols if c in signal_df.columns]

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "涨幅榜", "涨速榜", "自定义规则", "买卖信号", "行业联动", "概念联动", "大模型问股", "邮件提醒", "映射诊断"
])

with tab1:
    st.subheader("涨幅榜")
    show = signal_df.sort_values("涨跌幅", ascending=False, na_position="last").head(top_n)
    st.dataframe(prepare_display_table(show[base_cols]), column_config=column_config, width="stretch", height=620, hide_index=True)

with tab2:
    st.subheader("涨速榜：默认删除已涨停股票")
    speed_df = signal_df.copy()
    if rules["filters"].get("exclude_limit_in_speed_rank", True) and "是否涨停" in speed_df.columns:
        speed_df = speed_df[~speed_df["是否涨停"].fillna(False)].copy()
    show = speed_df.sort_values("规则涨速", ascending=False, na_position="last").head(top_n)
    st.dataframe(prepare_display_table(show[base_cols]), column_config=column_config, width="stretch", height=620, hide_index=True)

with tab3:
    render_kobe_rule_panel_v8_2_1(globals())
with tab4:
    st.subheader("买卖信号")
    status_order = ["打板/排板观察", "接近涨停观察", "半路买点观察", "卖出/风险提醒", "低位异动观察", "谨慎：孤立拉升", "观察"]
    cand = signal_df.copy()
    cand["_order"] = cand["买卖状态"].apply(lambda x: status_order.index(x) if x in status_order else 99)
    cand = cand.sort_values(["_order", "个股板块联动分"], ascending=[True, False])
    alert_states = ["打板/排板观察", "接近涨停观察", "半路买点观察", "卖出/风险提醒"]
    signal_view = cand[cand["买卖状态"].isin(alert_states + ["低位异动观察", "谨慎：孤立拉升"])]
    st.dataframe(prepare_display_table(signal_view[base_cols].head(top_n)), column_config=column_config, width="stretch", height=650, hide_index=True)

with tab5:
    st.subheader("行业联动")
    if industry_board.empty:
        st.warning("行业映射为空，请先运行本地通达信映射脚本。")
    else:
        bcols = ["板块名称", "股票数", "平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速", "板块联动分"]
        st.dataframe(prepare_display_table(industry_board[bcols].head(150)), column_config=column_config, width="stretch", height=620, hide_index=True)

with tab6:
    st.subheader("概念联动")
    if concept_board.empty:
        st.warning("概念映射为空。你的本地通达信可能没有标准 block_gn.dat；可以后续用自建概念词典补充。")
    else:
        bcols = ["板块名称", "股票数", "平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速", "板块联动分"]
        st.dataframe(prepare_display_table(concept_board[bcols].head(150)), column_config=column_config, width="stretch", height=620, hide_index=True)


with tab7:
    render_always_online_status_panel()
    render_skills_system_panel(app_name="8502")
    render_shared_image_panel(namespace="watch_ai", title="图片资料 / 视觉输入", expanded=False)
    render_watch_ai_chat_v7_7(
        data_candidates=[
            globals().get('df'),
            globals().get('data'),
            globals().get('main'),
            globals().get('main_df'),
            globals().get('raw'),
            globals().get('rank_df'),
            globals().get('watch_df'),
            globals().get('signal_df'),
            globals().get('board_df'),
            globals().get('pool'),
        ],
        market_context=globals(),
    )
with tab8:
    render_email_smallcap_alert_panel_v8_2_2(globals())
    render_email_alert_panel_v7_8(globals())
with tab9:
    st.subheader("映射诊断")
    ms = mapping_status()
    diag_rows = [{"文件": k, "是否存在": v["exists"], "条目数": v["items"]} for k, v in ms.items()]
    st.dataframe(pd.DataFrame(diag_rows), width="stretch", hide_index=True)

    unknown_rate = (signal_df["所属行业"].astype(str).eq("未知").mean() * 100) if "所属行业" in signal_df.columns else 100
    concept_empty_rate = (signal_df["所属概念"].astype(str).eq("").mean() * 100) if "所属概念" in signal_df.columns else 100
    c1, c2 = st.columns(2)
    c1.metric("行业未知比例", f"{unknown_rate:.1f}%")
    c2.metric("概念为空比例", f"{concept_empty_rate:.1f}%")
    st.info("行业映射来自 config/code_to_industry.json；概念映射来自 config/code_to_concepts.json。若概念为空，可以后续做自建概念词典。")

st.caption("8502：实时盯盘、自定义规则、信号归因、邮件提醒、联网问股。信号仅用于观察与复盘，不构成投资建议。")


# ===== v7.6 save snapshot for 8501 =====
try:
    save_latest_watch_from_globals(globals())
except Exception:
    pass
# ===== end v7.6 save snapshot for 8501 =====


# ===== v7.8 realtime buy email alert =====
try:
    process_realtime_buy_alerts_v7_8(globals())
except Exception:
    pass
# ===== end v7.8 realtime buy email alert =====


# ===== v7.9 signal state machine =====
try:
    process_signal_state_machine_v7_9(globals())
except Exception:
    pass

try:
    render_signal_events_panel_v7_9(globals())
except Exception:
    pass
# ===== end v7.9 signal state machine =====


# ===== v8.0 market emotion thermometer =====
try:
    compute_market_emotion(globals())
except Exception:
    pass

try:
    render_market_emotion_panel_v8_0(globals())
except Exception:
    pass
# ===== end v8.0 market emotion thermometer =====


# ===== v8.2 signal effect stats =====
try:
    render_signal_effect_stats_panel_v8_2()
except Exception:
    pass
# ===== end v8.2 signal effect stats =====


# ===== v8.2.2 custom volume rule auto process =====
try:
    process_volume_rule_snapshot_v8_2_2(globals())
except Exception:
    pass
# ===== end v8.2.2 custom volume rule auto process =====


# ===== v8.2.1 kobe rule attribution auto process =====
try:
    process_kobe_rule_snapshot_v8_2_1(globals())
    attribute_event_log_v8_2_1()
except Exception:
    pass
# ===== end v8.2.1 kobe rule attribution auto process =====


# ===== v8.2.2 email smallcap alert auto process =====
try:
    process_smallcap_alerts_v8_2_2(globals(), force_send=False)
except Exception:
    pass
# ===== end v8.2.2 email smallcap alert auto process =====


# ===== v8.3 Skills 8502 auto enrich =====
try:
    enrich_latest_signals_with_skills_v8_3(globals())
except Exception:
    pass
# ===== end v8.3 Skills 8502 auto enrich =====


# ===== v8.3.1 AI chat always online auto force =====
try:
    force_online_switches()
except Exception:
    pass
# ===== end v8.3.1 AI chat always online auto force =====

# ===== v8.3.2 stability panels 8502 =====
try:
    render_network_guard_panel(app_name='8502')
    render_web_research_panel(app_name='8502')
    render_realtime_logger_panel()
    render_backup_manager_panel()
except Exception:
    pass
# ===== end v8.3.2 stability panels 8502 =====

# ===== v8.3.2 realtime logger auto =====
try:
    log_current_snapshot_v8_3_2(globals())
except Exception:
    pass
# ===== end v8.3.2 realtime logger auto =====
