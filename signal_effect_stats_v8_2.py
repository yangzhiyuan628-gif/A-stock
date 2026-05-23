# -*- coding: utf-8 -*-
"""
signal_effect_stats_v8_2.py

8502 / v8.2：信号效果统计

目标：
1. 读取 v7.9 状态机事件日志；
2. 读取价格历史；
3. 计算信号触发后收益：
   - 1分钟
   - 5分钟
   - 10分钟
   - 30分钟
   - 收盘/最后价格
   - 最大有利波动 MFE
   - 最大回撤 MAE
4. 按信号类型统计半路/打板/回封胜率；
5. 给出简单参数优化建议。

读取文件：
- reports/watch_signal_events.csv
- reports/realtime_price_history.csv
- reports/watch_price_history.csv
- reports/realtime_last_snapshot.csv
- reports/latest_watch_signals.csv

输出：
- reports/signal_effect_records_v8_2.csv
- reports/signal_effect_stats_v8_2.csv
- reports/signal_param_suggestions_v8_2.md
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)

EVENT_PATH = REPORT_DIR / "watch_signal_events.csv"
RECORDS_PATH = REPORT_DIR / "signal_effect_records_v8_2.csv"
STATS_PATH = REPORT_DIR / "signal_effect_stats_v8_2.csv"
SUGGEST_PATH = REPORT_DIR / "signal_param_suggestions_v8_2.md"


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


def _norm_code(x: Any) -> str:
    d = "".join(re.findall(r"\d", str(x)))
    return d[-6:].zfill(6) if d else ""


def _to_float(x: Any, default: float = float("nan")) -> float:
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


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030"]:
        try:
            return pd.read_csv(path, dtype={"代码": str, "code": str, "股票代码": str}, encoding=enc)
        except Exception:
            pass
    try:
        return pd.read_csv(path, dtype={"代码": str, "code": str, "股票代码": str})
    except Exception:
        return pd.DataFrame()


def normalize_events(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    x = df.copy()
    if "代码" not in x.columns:
        for c in ["code", "股票代码", "证券代码"]:
            if c in x.columns:
                x["代码"] = x[c]
                break
    if "timestamp" not in x.columns:
        for c in ["时间", "time", "datetime", "date"]:
            if c in x.columns:
                x["timestamp"] = x[c]
                break
    if "to_state" not in x.columns and "标准状态" in x.columns:
        x["to_state"] = x["标准状态"]
    if "名称" not in x.columns:
        x["名称"] = x.get("代码", "")
    x["代码"] = x["代码"].map(_norm_code)
    x["timestamp"] = pd.to_datetime(x["timestamp"], errors="coerce")
    for c in ["最新价", "涨跌幅", "规则涨速", "成交额_亿"]:
        if c in x.columns:
            x[c] = x[c].map(_to_float)
    x = x.dropna(subset=["timestamp"])
    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)]
    return x


def normalize_price_history(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    if df.empty:
        return df

    x = df.copy()

    # 识别代码列
    if "代码" not in x.columns:
        for c in ["code", "symbol", "股票代码", "证券代码"]:
            if c in x.columns:
                x["代码"] = x[c]
                break

    if "代码" not in x.columns:
        return pd.DataFrame()

    # 识别时间列
    if "timestamp" not in x.columns:
        for c in ["time", "datetime", "date", "时间", "当前时间"]:
            if c in x.columns:
                x["timestamp"] = x[c]
                break

    if "timestamp" not in x.columns:
        # 如果是最后快照，没有时间，使用当前时间
        x["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 识别价格列
    if "price" not in x.columns:
        for c in ["最新价", "现价", "price", "close", "收盘", "最新"]:
            if c in x.columns:
                x["price"] = x[c]
                break

    if "price" not in x.columns:
        return pd.DataFrame()

    x["代码"] = x["代码"].map(_norm_code)
    x["timestamp"] = pd.to_datetime(x["timestamp"], errors="coerce")
    x["price"] = x["price"].map(_to_float)
    x["source"] = source

    x = x.dropna(subset=["timestamp", "price"])
    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)]
    x = x[x["price"] > 0]
    return x[["timestamp", "代码", "price", "source"]].copy()


def load_price_history() -> pd.DataFrame:
    paths = [
        REPORT_DIR / "realtime_price_history.csv",
        REPORT_DIR / "watch_price_history.csv",
        REPORT_DIR / "realtime_last_snapshot.csv",
        REPORT_DIR / "latest_watch_signals.csv",
        REPORT_DIR / "latest_watch_states_v7_9.csv",
    ]

    dfs = []
    for p in paths:
        df = read_csv_safe(p)
        norm = normalize_price_history(df, source=p.name)
        if not norm.empty:
            dfs.append(norm)

    if not dfs:
        return pd.DataFrame()

    out = pd.concat(dfs, ignore_index=True)
    out = out.drop_duplicates(["timestamp", "代码", "price"]).sort_values(["代码", "timestamp"])
    return out


def first_price_after(ph: pd.DataFrame, code: str, t: pd.Timestamp) -> tuple[float, pd.Timestamp | None]:
    x = ph[(ph["代码"] == code) & (ph["timestamp"] >= t)].sort_values("timestamp")
    if x.empty:
        return float("nan"), None
    r = x.iloc[0]
    return float(r["price"]), r["timestamp"]


def price_near_after(ph: pd.DataFrame, code: str, t: pd.Timestamp, minutes: int) -> float:
    target = t + timedelta(minutes=minutes)
    x = ph[(ph["代码"] == code) & (ph["timestamp"] >= target)].sort_values("timestamp")
    if x.empty:
        # 兜底：取 target 前后的最后一个后续价格
        x2 = ph[(ph["代码"] == code) & (ph["timestamp"] >= t)].sort_values("timestamp")
        if x2.empty:
            return float("nan")
        return float(x2.iloc[-1]["price"])
    return float(x.iloc[0]["price"])


def future_mfe_mae(ph: pd.DataFrame, code: str, t: pd.Timestamp, entry: float, minutes: int = 30) -> tuple[float, float]:
    if not entry or pd.isna(entry):
        return float("nan"), float("nan")
    end = t + timedelta(minutes=minutes)
    x = ph[(ph["代码"] == code) & (ph["timestamp"] >= t) & (ph["timestamp"] <= end)].sort_values("timestamp")
    if x.empty:
        return float("nan"), float("nan")
    prices = pd.to_numeric(x["price"], errors="coerce").dropna()
    if prices.empty:
        return float("nan"), float("nan")
    mfe = (prices.max() / entry - 1) * 100
    mae = (prices.min() / entry - 1) * 100
    return round(float(mfe), 4), round(float(mae), 4)


def compute_signal_effect_records() -> pd.DataFrame:
    events = normalize_events(read_csv_safe(EVENT_PATH))
    ph = load_price_history()

    if events.empty or ph.empty:
        return pd.DataFrame()

    records = []
    for _, ev in events.iterrows():
        code = _norm_code(ev.get("代码", ""))
        t = ev.get("timestamp")
        if not code or pd.isna(t):
            continue

        entry, entry_time = first_price_after(ph, code, t)
        if pd.isna(entry) or not entry:
            # 如果事件自身有最新价，用它当近似入场
            entry = _to_float(ev.get("最新价", float("nan")))
            entry_time = t

        if pd.isna(entry) or not entry:
            continue

        prices = {}
        returns = {}
        for m in [1, 5, 10, 30]:
            p = price_near_after(ph, code, t, m)
            prices[f"price_{m}m"] = p
            returns[f"ret_{m}m"] = round((p / entry - 1) * 100, 4) if p and not pd.isna(p) else float("nan")

        # 收盘/最后价：取该代码当日事件后的最后一个价格
        same = ph[(ph["代码"] == code) & (ph["timestamp"] >= t)].sort_values("timestamp")
        if not same.empty:
            last_price = float(same.iloc[-1]["price"])
            last_time = same.iloc[-1]["timestamp"]
        else:
            last_price = float("nan")
            last_time = None

        ret_close = round((last_price / entry - 1) * 100, 4) if last_price and not pd.isna(last_price) else float("nan")
        mfe, mae = future_mfe_mae(ph, code, t, entry, minutes=30)

        records.append({
            "timestamp": t,
            "代码": code,
            "名称": _safe_str(ev.get("名称", "")),
            "from_state": _safe_str(ev.get("from_state", "")),
            "to_state": _safe_str(ev.get("to_state", "")),
            "reason": _safe_str(ev.get("reason", "")),
            "entry_time": entry_time,
            "entry_price": round(float(entry), 4),
            **prices,
            **returns,
            "last_time": last_time,
            "last_price": round(float(last_price), 4) if last_price and not pd.isna(last_price) else float("nan"),
            "ret_close": ret_close,
            "mfe_30m": mfe,
            "mae_30m": mae,
            "event_pct": _to_float(ev.get("涨跌幅", float("nan"))),
            "event_speed": _to_float(ev.get("规则涨速", float("nan"))),
            "event_amount_yi": _to_float(ev.get("成交额_亿", float("nan"))),
            "所属行业": _safe_str(ev.get("所属行业", "")),
            "最强概念": _safe_str(ev.get("最强概念", "")),
        })

    out = pd.DataFrame(records)
    if not out.empty:
        out = out.sort_values("timestamp", ascending=False)
        out.to_csv(RECORDS_PATH, index=False, encoding="utf-8-sig")
    return out


def _win_rate(s: pd.Series) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return float("nan")
    return round(float((s > 0).mean() * 100), 2)


def summarize_signal_effects(records: pd.DataFrame | None = None) -> pd.DataFrame:
    if records is None:
        records = compute_signal_effect_records()
    if records is None or records.empty:
        return pd.DataFrame()

    rows = []
    group_col = "to_state"

    for state, g in records.groupby(group_col):
        row = {
            "to_state": state,
            "样本数": int(len(g)),
            "1分钟均值": round(float(pd.to_numeric(g["ret_1m"], errors="coerce").mean()), 4),
            "5分钟均值": round(float(pd.to_numeric(g["ret_5m"], errors="coerce").mean()), 4),
            "10分钟均值": round(float(pd.to_numeric(g["ret_10m"], errors="coerce").mean()), 4),
            "30分钟均值": round(float(pd.to_numeric(g["ret_30m"], errors="coerce").mean()), 4),
            "收盘均值": round(float(pd.to_numeric(g["ret_close"], errors="coerce").mean()), 4),
            "胜率_5分钟": _win_rate(g["ret_5m"]),
            "胜率_10分钟": _win_rate(g["ret_10m"]),
            "胜率_收盘": _win_rate(g["ret_close"]),
            "最大有利波动均值": round(float(pd.to_numeric(g["mfe_30m"], errors="coerce").mean()), 4),
            "最大回撤均值": round(float(pd.to_numeric(g["mae_30m"], errors="coerce").mean()), 4),
        }

        # 简单建议
        if row["样本数"] < 5:
            row["建议"] = "样本偏少，继续观察"
        elif row["5分钟均值"] > 0 and row["胜率_5分钟"] >= 55:
            row["建议"] = "短线有效，可保留"
        elif row["收盘均值"] > 0 and row["胜率_收盘"] >= 55:
            row["建议"] = "偏持有有效，注意分时承接"
        elif row["最大回撤均值"] < -2:
            row["建议"] = "回撤偏大，需提高过滤或缩短持有"
        else:
            row["建议"] = "效果一般，需优化参数"

        rows.append(row)

    out = pd.DataFrame(rows).sort_values(["样本数", "5分钟均值"], ascending=[False, False])
    out.to_csv(STATS_PATH, index=False, encoding="utf-8-sig")
    write_suggestions(out, records)
    return out


def write_suggestions(stats: pd.DataFrame, records: pd.DataFrame) -> None:
    lines = ["# v8.2 信号效果统计与参数建议", ""]
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 总体结论")
    if stats.empty:
        lines.append("- 暂无足够数据。")
    else:
        for _, r in stats.iterrows():
            lines.append(
                f"- {r['to_state']}：样本 {int(r['样本数'])}，5分钟均值 {r['5分钟均值']}%，"
                f"5分钟胜率 {r['胜率_5分钟']}%，收盘均值 {r['收盘均值']}%。建议：{r['建议']}"
            )

    lines.append("")
    lines.append("## 参数优化提示")
    lines.append("- 如果“半路触发”的 5分钟均值为负：提高涨速阈值、提高成交额阈值、要求行业/概念联动更强。")
    lines.append("- 如果“接近涨停”回撤大：减少追高，只做回封确认或换手充分的标的。")
    lines.append("- 如果“封板观察”收盘收益弱：检查炸板率，增加封单/换手/板块强度过滤。")
    lines.append("- 如果“低位异动”有效：可把它作为明日首板候选池来源，但不要直接作为买入依据。")
    lines.append("")
    lines.append("## 注意")
    lines.append("- 这些统计依赖本地价格历史。如果实时价格历史不完整，收益统计只是近似。")
    SUGGEST_PATH.write_text("\n".join(lines), encoding="utf-8")


def compute_and_save_signal_effects() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    records = compute_signal_effect_records()
    if records.empty:
        msg = "未能生成信号效果记录。可能原因：缺少 watch_signal_events.csv 或价格历史。"
        return records, pd.DataFrame(), msg

    stats = summarize_signal_effects(records)
    msg = f"已生成信号效果记录 {len(records)} 条，统计分组 {len(stats)} 个。"
    return records, stats, msg


def render_signal_effect_stats_panel_v8_2() -> None:
    import streamlit as st

    st.subheader("v8.2 信号效果统计")
    st.caption("统计信号触发后 1/5/10/30 分钟收益、收盘收益、胜率、最大有利波动和最大回撤。")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("计算信号效果", type="primary", key="v82_compute"):
            with st.spinner("正在计算信号触发后的收益..."):
                records, stats, msg = compute_and_save_signal_effects()
            st.session_state["v82_msg"] = msg
            st.success(msg if not stats.empty else msg)
    with c2:
        if RECORDS_PATH.exists():
            st.download_button("下载明细记录", RECORDS_PATH.read_bytes(), "signal_effect_records_v8_2.csv", "text/csv", key="v82_download_records")
    with c3:
        if STATS_PATH.exists():
            st.download_button("下载统计结果", STATS_PATH.read_bytes(), "signal_effect_stats_v8_2.csv", "text/csv", key="v82_download_stats")

    if st.session_state.get("v82_msg"):
        st.info(st.session_state["v82_msg"])

    records = read_csv_safe(RECORDS_PATH)
    stats = read_csv_safe(STATS_PATH)

    if stats.empty:
        st.warning("暂无统计结果。请先点击“计算信号效果”。如果仍为空，说明缺少价格历史或状态机事件日志。")
    else:
        st.markdown("**按信号类型统计**")
        st.dataframe(stats, hide_index=True, use_container_width=True, height=280)

    if not records.empty:
        st.markdown("**最近信号效果明细**")
        show_cols = [c for c in [
            "timestamp", "代码", "名称", "to_state", "entry_price", "ret_1m", "ret_5m",
            "ret_10m", "ret_30m", "ret_close", "mfe_30m", "mae_30m",
            "event_pct", "event_speed", "event_amount_yi", "所属行业", "最强概念"
        ] if c in records.columns]
        st.dataframe(records[show_cols].head(300), hide_index=True, use_container_width=True, height=420)

    if SUGGEST_PATH.exists():
        with st.expander("参数优化建议", expanded=True):
            st.markdown(SUGGEST_PATH.read_text(encoding="utf-8"))
