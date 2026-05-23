# -*- coding: utf-8 -*-
"""
after_review_v8_1.py

8501 / v8.1：盘后复盘闭环

目标：
1. 8501 自动读取 8502 全天日志；
2. 汇总市场情绪、行业/概念联动、状态机事件、邮件触发记录；
3. 调用大模型生成 AI 游资复盘报告；
4. 推荐明日观察方向；
5. 输出 reports/after_review_v8_1.md/json/csv，供后续继续迭代。

读取文件：
- reports/watch_signal_events.csv
- reports/latest_watch_states_v7_9.csv
- reports/latest_watch_signals.csv
- reports/market_emotion_v8_0.json
- reports/market_emotion_history_v8_0.csv
- reports/latest_industry_board.csv
- reports/latest_concept_board.csv
- reports/email_alert_log_v7_8.csv
- reports/signal_effect_stats_v8_2.csv
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
CONFIG_DIR = ROOT / "config"

REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

REVIEW_MD = REPORT_DIR / "after_review_v8_1.md"
REVIEW_JSON = REPORT_DIR / "after_review_v8_1.json"
REVIEW_CSV = REPORT_DIR / "after_review_v8_1_summary.csv"
CONFIG_PATH = CONFIG_DIR / "after_review_v8_1.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "temperature": 0.35,
    "max_tokens": 4200,
    "top_events": 80,
    "top_states": 80,
    "top_boards": 15,
    "top_stats": 30,
    "style": "短线游资复盘，重点看情绪、主线、首板扩散、半路/回封、风险和明日方向。",
}


def load_env_files() -> None:
    for name in [".env", ".env.watch", ".env.local"]:
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            pass

    load_env_files()
    cfg["base_url"] = os.getenv("AI_BASE_URL", cfg["base_url"]).rstrip("/")
    cfg["model"] = os.getenv("AI_MODEL", cfg["model"])
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
        return float(m.group(0))
    except Exception:
        return default


def read_csv_safe(name: str) -> pd.DataFrame:
    p = REPORT_DIR / name
    if not p.exists():
        return pd.DataFrame()
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030"]:
        try:
            return pd.read_csv(p, dtype={"代码": str}, encoding=enc)
        except Exception:
            pass
    try:
        return pd.read_csv(p, dtype={"代码": str})
    except Exception:
        return pd.DataFrame()


def load_emotion() -> dict:
    p = REPORT_DIR / "market_emotion_v8_0.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_numeric(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    for c in x.columns:
        name = str(c)
        if any(k in name for k in ["涨跌幅", "涨幅", "涨速", "成交额", "换手率", "联动分", "收益", "回撤", "胜率", "score"]):
            try:
                x[c] = x[c].map(_to_float)
            except Exception:
                pass
    return x


def top_table_text(df: pd.DataFrame, cols: list[str], top_n: int = 20, sort_col: str | None = None, ascending: bool = False) -> str:
    if df is None or df.empty:
        return "暂无数据。"
    x = normalize_numeric(df)
    if sort_col and sort_col in x.columns:
        x = x.sort_values(sort_col, ascending=ascending, na_position="last")
    cols = [c for c in cols if c in x.columns]
    if not cols:
        cols = list(x.columns[:10])
    x = x[cols].head(top_n)
    return x.to_string(index=False)


def build_after_review_context(cfg: dict | None = None) -> dict:
    cfg = {**DEFAULT_CONFIG, **(cfg or load_config())}

    events = read_csv_safe("watch_signal_events.csv")
    states = read_csv_safe("latest_watch_states_v7_9.csv")
    signals = read_csv_safe("latest_watch_signals.csv")
    emotion = load_emotion()
    industry = read_csv_safe("latest_industry_board.csv")
    concept = read_csv_safe("latest_concept_board.csv")
    email_log = read_csv_safe("email_alert_log_v7_8.csv")
    stats = read_csv_safe("signal_effect_stats_v8_2.csv")

    today = datetime.now().strftime("%Y-%m-%d")

    if not events.empty and "timestamp" in events.columns:
        today_events = events[events["timestamp"].astype(str).str.startswith(today)].copy()
    else:
        today_events = events

    if not email_log.empty and "timestamp" in email_log.columns:
        today_emails = email_log[email_log["timestamp"].astype(str).str.startswith(today)].copy()
    else:
        today_emails = email_log

    event_summary = {}
    if not today_events.empty and "to_state" in today_events.columns:
        event_summary = today_events["to_state"].astype(str).value_counts().to_dict()

    state_summary = {}
    if not states.empty and "标准状态" in states.columns:
        state_summary = states["标准状态"].astype(str).value_counts().to_dict()

    ctx = {
        "date": today,
        "emotion": emotion,
        "event_summary": event_summary,
        "state_summary": state_summary,
        "events_text": top_table_text(
            today_events,
            ["timestamp", "代码", "名称", "from_state", "to_state", "reason", "涨跌幅", "规则涨速", "成交额_亿", "所属行业", "最强概念"],
            top_n=int(cfg["top_events"]),
            sort_col="timestamp",
            ascending=False,
        ),
        "states_text": top_table_text(
            states,
            ["代码", "名称", "标准状态", "状态原因", "最新价", "涨跌幅", "规则涨速", "成交额_亿", "所属行业", "最强概念", "买卖状态"],
            top_n=int(cfg["top_states"]),
            sort_col="状态等级",
            ascending=False,
        ),
        "signals_text": top_table_text(
            signals,
            ["代码", "名称", "最新价", "涨跌幅", "规则涨速", "成交额_亿", "所属行业", "最强概念", "买卖状态", "个股板块联动分"],
            top_n=int(cfg["top_states"]),
            sort_col="个股板块联动分",
            ascending=False,
        ),
        "industry_text": top_table_text(
            industry,
            ["板块名称", "股票数", "平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速", "板块联动分"],
            top_n=int(cfg["top_boards"]),
            sort_col="板块联动分",
            ascending=False,
        ),
        "concept_text": top_table_text(
            concept,
            ["板块名称", "股票数", "平均涨幅", "板块成交额", "涨停数", "接近涨停数", "强势股数", "平均5分钟涨速", "板块联动分"],
            top_n=int(cfg["top_boards"]),
            sort_col="板块联动分",
            ascending=False,
        ),
        "email_text": top_table_text(
            today_emails,
            ["timestamp", "代码", "名称", "涨跌幅", "规则涨速", "成交额_亿", "所属行业", "最强概念", "买卖状态", "send_ok", "message"],
            top_n=50,
            sort_col="timestamp",
            ascending=False,
        ),
        "stats_text": top_table_text(
            stats,
            ["to_state", "样本数", "1分钟均值", "5分钟均值", "10分钟均值", "收盘均值", "胜率_5分钟", "胜率_收盘", "最大回撤均值", "建议"],
            top_n=int(cfg["top_stats"]),
            sort_col="样本数",
            ascending=False,
        ),
        "raw_counts": {
            "events_today": int(len(today_events)) if not today_events.empty else 0,
            "states": int(len(states)) if not states.empty else 0,
            "signals": int(len(signals)) if not signals.empty else 0,
            "emails_today": int(len(today_emails)) if not today_emails.empty else 0,
            "stats": int(len(stats)) if not stats.empty else 0,
        },
    }

    return ctx


def build_prompt(ctx: dict, cfg: dict) -> tuple[str, str]:
    emotion = ctx.get("emotion") or {}
    system = (
        "你是一个短线打板/首板/半路/回封风格的AI游资复盘机器人。"
        "你不负责自动下单，只做盘后复盘、明日方向推演和风险提示。"
        "你必须基于8502全天盯盘日志、状态机事件、市场情绪温度计、板块联动和信号效果统计来分析。"
        "不要编造新闻、龙虎榜、财务数据或盘口。没有数据就明确说没有。"
        "输出要偏实战，但必须有风控。"
    )

    user = f"""
【复盘日期】
{ctx.get('date')}

【当前复盘风格】
{cfg.get('style')}

【市场情绪温度计】
情绪阶段: {emotion.get('emotion_phase')}
情绪分: {emotion.get('emotion_score')}
主线状态: {emotion.get('mainline_status')}
说明: {emotion.get('emotion_comment')}
涨停数: {emotion.get('limit_count')}，接近涨停: {emotion.get('near_limit_count')}，强势股: {emotion.get('strong_count')}，风险股: {emotion.get('risk_count')}
买点状态数: {emotion.get('buy_state_count')}，今日事件数: {emotion.get('event_count_today')}

【今日状态机事件统计】
{json.dumps(ctx.get('event_summary', {}), ensure_ascii=False)}

【当前标准状态统计】
{json.dumps(ctx.get('state_summary', {}), ensure_ascii=False)}

【今日状态机事件明细】
{ctx.get('events_text')}

【当前有效状态/盯盘股票】
{ctx.get('states_text')}

【当前盯盘快照】
{ctx.get('signals_text')}

【行业联动】
{ctx.get('industry_text')}

【概念联动】
{ctx.get('concept_text')}

【邮件触发记录】
{ctx.get('email_text')}

【v8.2 信号效果统计，如没有则忽略】
{ctx.get('stats_text')}

请生成一份完整的 AI 游资盘后复盘报告，结构如下：
1. 今日市场情绪判断：冰点/退潮/弱修复/混沌偏强/强修复/主升高热，并解释依据。
2. 今日主线与支线：按行业/概念联动、涨停扩散、强势股数量判断。
3. 今日最有效信号：低位异动、半路触发、接近涨停、封板观察、回封确认哪些更有效。
4. 今日失败/风险信号：炸板、失效、风险回避集中在哪些方向。
5. 明日观察方向：主线延续、支线轮动、首板方向、半路方向。
6. 明日候选池：从现有数据里挑 5-10 个需要观察的标的，说明只观察不等于买入。
7. 交易计划：激进模式、稳健模式、防守模式分别怎么做。
8. 风险提示：哪些情形明日不宜出手。
"""
    return system, user


def call_llm(system: str, user: str, cfg: dict) -> tuple[bool, str]:
    load_env_files()
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY") or ""
    if not api_key:
        return False, "没有读取到 API Key。请在 .env 设置 DEEPSEEK_API_KEY / OPENAI_API_KEY。"

    base_url = str(cfg.get("base_url") or os.getenv("AI_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = str(cfg.get("model") or os.getenv("AI_MODEL") or "deepseek-chat")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(cfg.get("temperature", 0.35)),
        "max_tokens": int(cfg.get("max_tokens", 4200)),
    }

    try:
        r = requests.post(
            base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=140,
        )
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return False, f"大模型调用失败：{type(exc).__name__}: {exc}"


def generate_after_review(use_llm: bool = True, cfg: dict | None = None) -> tuple[bool, str, dict]:
    cfg = {**DEFAULT_CONFIG, **(cfg or load_config())}
    ctx = build_after_review_context(cfg)

    if use_llm:
        system, user = build_prompt(ctx, cfg)
        ok, text = call_llm(system, user, cfg)
        if not ok:
            text = build_local_review(ctx) + "\n\n---\n\n" + "【大模型调用失败】\n" + text
            ok = False
    else:
        text = build_local_review(ctx)
        ok = True

    result = {
        "date": ctx.get("date"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "llm_ok": bool(ok),
        "counts": ctx.get("raw_counts", {}),
        "emotion": ctx.get("emotion", {}),
        "report_md": text,
    }

    REVIEW_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    REVIEW_MD.write_text(text, encoding="utf-8")
    pd.DataFrame([{
        "date": result["date"],
        "generated_at": result["generated_at"],
        "llm_ok": result["llm_ok"],
        **{f"count_{k}": v for k, v in result["counts"].items()},
        "emotion_score": result["emotion"].get("emotion_score"),
        "emotion_phase": result["emotion"].get("emotion_phase"),
        "mainline_status": result["emotion"].get("mainline_status"),
    }]).to_csv(REVIEW_CSV, index=False, encoding="utf-8-sig")

    return ok, text, result


def build_local_review(ctx: dict) -> str:
    emotion = ctx.get("emotion") or {}
    lines = []
    lines.append(f"# AI游资盘后复盘 v8.1 - {ctx.get('date')}")
    lines.append("")
    lines.append("## 1. 市场情绪")
    lines.append(f"- 情绪阶段：{emotion.get('emotion_phase', '未知')}")
    lines.append(f"- 情绪分：{emotion.get('emotion_score', '无')}")
    lines.append(f"- 主线状态：{emotion.get('mainline_status', '未知')}")
    lines.append(f"- 说明：{emotion.get('emotion_comment', '暂无')}")
    lines.append("")
    lines.append("## 2. 今日事件统计")
    lines.append("```json")
    lines.append(json.dumps(ctx.get("event_summary", {}), ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 3. 行业联动")
    lines.append("```text")
    lines.append(ctx.get("industry_text", "暂无"))
    lines.append("```")
    lines.append("")
    lines.append("## 4. 概念联动")
    lines.append("```text")
    lines.append(ctx.get("concept_text", "暂无"))
    lines.append("```")
    lines.append("")
    lines.append("## 5. 明日观察方向")
    lines.append("- 本地模板版：优先观察今日有状态机事件、板块联动分靠前、且未出现风险回避/炸板风险的方向。")
    lines.append("- 若情绪为强修复/主升高热，可提高对首板扩散和回封确认的关注；若为退潮/冰点，则降低仓位，只看低位异动和换手承接。")
    lines.append("")
    lines.append("## 6. 当前有效状态")
    lines.append("```text")
    lines.append(ctx.get("states_text", "暂无"))
    lines.append("```")
    return "\n".join(lines)


def render_after_review_panel_v8_1() -> None:
    import streamlit as st

    cfg = load_config()

    st.subheader("v8.1 盘后复盘闭环")
    st.caption("自动读取 8502 全天日志、状态机、市场情绪、板块联动和信号统计，生成 AI 游资复盘报告。")

    with st.expander("复盘设置", expanded=False):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            cfg["base_url"] = st.text_input("AI Base URL", value=str(cfg.get("base_url", "https://api.deepseek.com")), key="v81_review_base")
        with c2:
            cfg["model"] = st.text_input("模型", value=str(cfg.get("model", "deepseek-chat")), key="v81_review_model")
        with c3:
            cfg["temperature"] = st.number_input("temperature", 0.0, 1.5, float(cfg.get("temperature", 0.35)), 0.05, key="v81_review_temp")

        cfg["style"] = st.text_area("复盘风格", value=str(cfg.get("style", DEFAULT_CONFIG["style"])), height=80, key="v81_review_style")

        if st.button("保存复盘设置", key="v81_review_save"):
            save_config(cfg)
            st.success("已保存到 config/after_review_v8_1.json。")

    ctx = build_after_review_context(cfg)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("今日事件", ctx["raw_counts"].get("events_today", 0))
    c2.metric("当前状态", ctx["raw_counts"].get("states", 0))
    c3.metric("邮件记录", ctx["raw_counts"].get("emails_today", 0))
    c4.metric("效果统计", ctx["raw_counts"].get("stats", 0))

    emo = ctx.get("emotion") or {}
    if emo:
        st.info(f"当前情绪：{emo.get('emotion_phase')} / {emo.get('emotion_score')} ｜ 主线：{emo.get('mainline_status')}")

    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        if st.button("生成 AI 复盘报告", type="primary", key="v81_generate_llm"):
            with st.spinner("正在调用大模型生成盘后复盘..."):
                ok, text, _ = generate_after_review(use_llm=True, cfg=cfg)
            if ok:
                st.success("AI 复盘报告已生成。")
            else:
                st.warning("大模型调用失败，已生成本地模板版。")
            st.session_state["v81_review_text"] = text
    with b2:
        if st.button("生成本地模板复盘", key="v81_generate_local"):
            ok, text, _ = generate_after_review(use_llm=False, cfg=cfg)
            st.session_state["v81_review_text"] = text
            st.success("本地模板复盘已生成。")
    with b3:
        if REVIEW_MD.exists():
            st.download_button("下载复盘报告", data=REVIEW_MD.read_text(encoding="utf-8"), file_name="after_review_v8_1.md", mime="text/markdown", key="v81_download")

    text = st.session_state.get("v81_review_text")
    if not text and REVIEW_MD.exists():
        text = REVIEW_MD.read_text(encoding="utf-8")

    if text:
        st.markdown(text)

    with st.expander("复盘数据预览", expanded=False):
        st.markdown("**状态机事件**")
        st.text(ctx.get("events_text", "暂无"))
        st.markdown("**行业联动**")
        st.text(ctx.get("industry_text", "暂无"))
        st.markdown("**概念联动**")
        st.text(ctx.get("concept_text", "暂无"))
