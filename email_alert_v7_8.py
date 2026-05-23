# -*- coding: utf-8 -*-
"""
email_alert_v7_8.py

8502 / v7.8 邮件提醒修复：
1. 只给“符合买入点/半路/封板观察”的股票发邮件；
2. 不发卖出/风险提醒，降低 163/QQ 反垃圾概率；
3. 每次最多发送 Top N，默认 5 条；
4. 同一股票 + 同一状态有冷却时间，默认 30 分钟；
5. 测试邮件使用极短纯文本；
6. 修复 st.write(st.success(...)) 导致页面显示 DeltaGenerator 的问题；
7. 支持自动刷新时实时检测：每轮刷新都会调用，但只在新触发且未冷却时发邮件。
"""

from __future__ import annotations

import json
import os
import re
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
CONFIG_DIR = ROOT / "config"
REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

STATE_PATH = REPORT_DIR / "email_alert_state_v7_8.json"
LOG_PATH = REPORT_DIR / "email_alert_log_v7_8.csv"
CONFIG_PATH = CONFIG_DIR / "email_alert_v7_8.json"


BUY_KEYWORDS = [
    "半路买点",
    "半路",
    "买点",
    "买入",
    "打板",
    "排板",
    "回封",
    "封板观察",
    "接近涨停",
]

RISK_KEYWORDS = [
    "卖出",
    "风险",
    "回避",
    "中性",
    "未知",
    "跌停",
    "破位",
    "清仓",
]

DEFAULT_CONFIG = {
    "enabled": False,
    "smtp_host": "smtp.163.com",
    "smtp_port": 465,
    "smtp_user": "",
    "smtp_pass": "",
    "smtp_sender": "",
    "smtp_receiver": "",
    "use_ssl": True,
    "max_alerts": 5,
    "cooldown_minutes": 30,
    "min_amount_yi": 0.30,
    "subject": "8502监控提醒",
    "only_buy_signals": True,
    "send_test_plain": True,
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
    load_env_files()
    cfg = dict(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            pass

    # 环境变量兜底
    env_map = {
        "SMTP_HOST": "smtp_host",
        "SMTP_PORT": "smtp_port",
        "SMTP_USER": "smtp_user",
        "SMTP_PASS": "smtp_pass",
        "SMTP_SENDER": "smtp_sender",
        "SMTP_RECEIVER": "smtp_receiver",
        "SMTP_USE_SSL": "use_ssl",
    }
    for env, key in env_map.items():
        val = os.getenv(env)
        if val is None or val == "":
            continue
        if key == "smtp_port":
            try:
                cfg[key] = int(val)
            except Exception:
                pass
        elif key == "use_ssl":
            cfg[key] = str(val).lower() in {"1", "true", "yes", "y", "on"}
        else:
            cfg[key] = val

    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    safe = dict(cfg)
    # 保存到本地配置时保留 pass，方便用户“不用每次登录”
    CONFIG_PATH.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")


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
    if "万" in s:
        m = re.search(r"[-+]?\d*\.?\d+", s)
        return float(m.group(0)) / 10000 if m else default
    if "亿" in s:
        m = re.search(r"[-+]?\d*\.?\d+", s)
        return float(m.group(0)) if m else default
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return default
    try:
        return float(m.group(0))
    except Exception:
        return default


def _norm_code(x: Any) -> str:
    d = "".join(re.findall(r"\d", str(x)))
    return d[-6:].zfill(6) if d else ""


def _is_stock_df(df: pd.DataFrame) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return False
    cols = set(map(str, df.columns))
    has_code = any(c in cols for c in ["代码", "股票代码", "证券代码", "code", "symbol"])
    has_name = any(c in cols for c in ["名称", "股票名称", "证券简称", "name"])
    has_signal = any(c in cols for c in ["买卖状态", "多空状态", "半路触发", "打板观察", "涨跌幅", "涨幅"])
    return has_code and has_name and has_signal


def _standardize_df(df: pd.DataFrame) -> pd.DataFrame:
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

    if "涨幅" in x.columns and "涨跌幅" not in x.columns:
        x["涨跌幅"] = x["涨幅"]

    if "成交额_亿" not in x.columns and "成交额" in x.columns:
        x["成交额_亿"] = x["成交额"].map(_to_float)

    for c in ["涨跌幅", "涨速", "5分钟涨速", "规则涨速", "成交额_亿", "换手率", "个股板块联动分"]:
        if c in x.columns:
            x[c] = x[c].map(_to_float)

    return x


def find_watch_df_from_globals(globs: dict) -> pd.DataFrame:
    candidates = []
    preferred_names = [
        "signal_df",
        "watch_df",
        "df",
        "main",
        "main_df",
        "data",
        "rank_df",
        "pool",
    ]

    for name in preferred_names:
        obj = globs.get(name)
        if isinstance(obj, pd.DataFrame) and _is_stock_df(obj):
            candidates.append((1000000 + len(obj), name, obj))

    for name, obj in globs.items():
        if isinstance(obj, pd.DataFrame) and _is_stock_df(obj):
            candidates.append((len(obj), name, obj))

    if not candidates:
        # 兜底读快照
        p = REPORT_DIR / "latest_watch_signals.csv"
        if p.exists():
            try:
                return _standardize_df(pd.read_csv(p, dtype={"代码": str}))
            except Exception:
                return pd.DataFrame()
        return pd.DataFrame()

    candidates.sort(key=lambda x: x[0], reverse=True)
    return _standardize_df(candidates[0][2])


def is_buy_signal_row(row: pd.Series, min_amount_yi: float = 0.0) -> bool:
    code = _norm_code(row.get("代码", ""))
    if not code:
        return False

    # 成交额过滤
    amount = _to_float(row.get("成交额_亿", row.get("成交额", 0)))
    if amount < float(min_amount_yi or 0):
        return False

    state_text = " ".join(
        _safe_str(row.get(c, ""))
        for c in ["买卖状态", "多空状态", "实时信号", "操作提示", "信号", "买点规则"]
        if c in row.index
    )

    if any(k in state_text for k in RISK_KEYWORDS):
        return False

    if any(k in state_text for k in BUY_KEYWORDS):
        return True

    # 布尔列兜底
    for c in ["半路触发", "打板观察", "接近涨停"]:
        if c in row.index:
            v = row.get(c)
            if isinstance(v, bool) and v:
                return True
            if str(v).lower() in {"true", "1", "yes", "y", "是"}:
                return True

    return False


def filter_buy_alerts(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    x = _standardize_df(df)
    min_amount = float(cfg.get("min_amount_yi", 0.0) or 0.0)

    mask = x.apply(lambda r: is_buy_signal_row(r, min_amount_yi=min_amount), axis=1)
    out = x[mask].copy()

    if out.empty:
        return out

    if "个股板块联动分" in out.columns:
        out = out.sort_values("个股板块联动分", ascending=False, na_position="last")
    elif "涨跌幅" in out.columns:
        out = out.sort_values("涨跌幅", ascending=False, na_position="last")

    max_n = int(cfg.get("max_alerts", 5) or 5)
    return out.head(max_n).copy()


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


def alert_key(row: pd.Series) -> str:
    code = _norm_code(row.get("代码", ""))
    state = _safe_str(row.get("买卖状态", row.get("多空状态", "触发观察")))
    return f"{code}|{state}"


def remove_cooldown(alerts: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if alerts is None or alerts.empty:
        return pd.DataFrame()

    state = load_state()
    now = datetime.now()
    cooldown = int(cfg.get("cooldown_minutes", 30) or 30)

    keep = []
    for _, row in alerts.iterrows():
        key = alert_key(row)
        last_s = state.get(key)
        if not last_s:
            keep.append(row)
            continue
        try:
            last = datetime.fromisoformat(last_s)
        except Exception:
            keep.append(row)
            continue
        if now - last >= timedelta(minutes=cooldown):
            keep.append(row)

    return pd.DataFrame(keep) if keep else pd.DataFrame()


def mark_sent(alerts: pd.DataFrame) -> None:
    if alerts is None or alerts.empty:
        return

    state = load_state()
    now_s = datetime.now().isoformat(timespec="seconds")

    for _, row in alerts.iterrows():
        state[alert_key(row)] = now_s

    save_state(state)


def _sanitize_for_anti_spam(text: str) -> str:
    # 尽量降低 163/QQ 对金融营销/垃圾邮件的误判
    repl = {
        "买入": "观察点",
        "卖出": "风险处理",
        "涨停": "高位触发",
        "打板": "封板观察",
        "排板": "封单观察",
        "股票": "标的",
        "推荐": "关注",
        "暴涨": "强波动",
        "盈利": "结果",
        "收益": "结果",
    }
    out = text
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def build_email_body(alerts: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "8502监控提醒",
        f"时间：{now}",
        "",
        "本轮出现新的观察触发，仅作盯盘记录，不自动下单。",
        "",
    ]

    for i, (_, r) in enumerate(alerts.iterrows(), start=1):
        code = _safe_str(r.get("代码", ""))
        name = _safe_str(r.get("名称", ""))
        state = _safe_str(r.get("买卖状态", r.get("多空状态", "触发观察")))
        pct = _safe_str(r.get("涨跌幅", ""))
        speed = _safe_str(r.get("规则涨速", r.get("5分钟涨速", r.get("涨速", ""))))
        amount = _safe_str(r.get("成交额_亿", ""))
        industry = _safe_str(r.get("所属行业", ""))
        concept = _safe_str(r.get("最强概念", r.get("所属概念", "")))

        lines.append(f"{i}. {code} {name}")
        lines.append(f"   状态：{state}")
        lines.append(f"   涨幅：{pct}%  速度：{speed}%  成交额：{amount}亿")
        lines.append(f"   行业：{industry}  概念：{concept}")
        lines.append("")

    lines.append("提示：请结合分时承接、板块联动和个人风控再判断。")

    return _sanitize_for_anti_spam("\n".join(lines))


def append_log(alerts: pd.DataFrame, send_ok: bool, msg: str) -> None:
    if alerts is None or alerts.empty:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = [c for c in ["代码", "名称", "最新价", "涨跌幅", "规则涨速", "涨速", "成交额_亿", "所属行业", "最强概念", "买卖状态", "多空状态"] if c in alerts.columns]
    log = alerts[cols].copy()
    log["timestamp"] = now
    log["send_ok"] = send_ok
    log["message"] = msg

    if LOG_PATH.exists():
        try:
            old = pd.read_csv(LOG_PATH, dtype={"代码": str})
            log = pd.concat([old, log], ignore_index=True)
        except Exception:
            pass

    log.to_csv(LOG_PATH, index=False, encoding="utf-8-sig")


def send_email(subject: str, body: str, cfg: dict) -> tuple[bool, str]:
    host = _safe_str(cfg.get("smtp_host", ""))
    port = int(cfg.get("smtp_port", 465) or 465)
    user = _safe_str(cfg.get("smtp_user", ""))
    pwd = _safe_str(cfg.get("smtp_pass", ""))
    sender = _safe_str(cfg.get("smtp_sender", "")) or user
    receiver = _safe_str(cfg.get("smtp_receiver", ""))

    if not all([host, port, user, pwd, sender, receiver]):
        return False, "SMTP配置不完整。"

    # 避免 smtp.qq.com + 163账号 这种不匹配
    if "smtp.qq.com" in host and "@163.com" in user:
        return False, "SMTP Host 是 QQ，但用户名是 163 邮箱。请改成 smtp.163.com，或换 QQ 邮箱账号。"
    if "smtp.163.com" in host and "@qq.com" in user:
        return False, "SMTP Host 是 163，但用户名是 QQ 邮箱。请改成 smtp.qq.com，或换 163 邮箱账号。"

    subject = _sanitize_for_anti_spam(subject or "8502监控提醒")
    body = _sanitize_for_anti_spam(body or "8502监控提醒。")

    try:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = subject
        msg.set_content(body, subtype="plain", charset="utf-8")

        timeout = 30
        if bool(cfg.get("use_ssl", True)):
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
            smtp.starttls()

        smtp.login(user, pwd)
        smtp.send_message(msg)
        smtp.quit()
        return True, "邮件已发送。"
    except smtplib.SMTPDataError as exc:
        return False, f"邮件被服务器拒收：{exc}. 建议减少条数、简化内容，或换 QQ/企业邮箱。"
    except TimeoutError as exc:
        return False, f"邮件发送超时：{exc}. 请检查网络、防火墙或尝试 587 端口。"
    except Exception as exc:
        return False, f"邮件发送失败：{type(exc).__name__}: {exc}"


def send_test_email(cfg: dict) -> tuple[bool, str]:
    return send_email(
        subject="8502测试",
        body="这是一封8502系统测试邮件。",
        cfg=cfg,
    )


def process_realtime_buy_alerts_v7_8(globs: dict) -> tuple[bool, str, int]:
    """
    自动刷新时调用。
    返回：是否发送成功/消息/本轮新发送数量。
    """
    try:
        import streamlit as st
    except Exception:
        st = None

    cfg = load_config()

    # UI 状态覆盖本地配置
    if st is not None:
        ss = st.session_state
        if "email_v78_enabled" in ss:
            cfg["enabled"] = bool(ss.get("email_v78_enabled"))
        if "email_v78_max_alerts" in ss:
            cfg["max_alerts"] = int(ss.get("email_v78_max_alerts") or 5)
        if "email_v78_cooldown" in ss:
            cfg["cooldown_minutes"] = int(ss.get("email_v78_cooldown") or 30)
        if "email_v78_min_amount" in ss:
            cfg["min_amount_yi"] = float(ss.get("email_v78_min_amount") or 0)

    if not cfg.get("enabled", False):
        return False, "邮件提醒未启用。", 0

    df = find_watch_df_from_globals(globs)
    if df.empty:
        return False, "未找到盯盘股票池。", 0

    alerts = filter_buy_alerts(df, cfg)
    alerts = remove_cooldown(alerts, cfg)

    if alerts.empty:
        return True, "本轮没有新的买点观察触发，或仍在冷却时间内。", 0

    body = build_email_body(alerts)
    ok, msg = send_email(cfg.get("subject", "8502监控提醒"), body, cfg)

    if ok:
        mark_sent(alerts)

    append_log(alerts, ok, msg)

    if st is not None:
        st.session_state["email_v78_last_msg"] = msg
        st.session_state["email_v78_last_count"] = len(alerts)
        st.session_state["email_v78_last_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return ok, msg, len(alerts)


def render_email_alert_panel_v7_8(globs: dict) -> None:
    """
    替换原“邮件提醒”Tab 的 UI。
    """
    import streamlit as st

    cfg = load_config()

    st.subheader("邮件提醒")
    st.caption("v7.8：只在符合买点/半路/封板观察时发送邮件；不发送卖出/风险提醒；支持实时刷新检测和冷却时间。")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        cfg["enabled"] = st.checkbox(
            "启用自动邮件提醒",
            value=bool(cfg.get("enabled", False)),
            key="email_v78_enabled",
        )
    with c2:
        cfg["max_alerts"] = st.number_input(
            "每次最多发送标的数",
            min_value=1,
            max_value=20,
            value=int(cfg.get("max_alerts", 5) or 5),
            step=1,
            key="email_v78_max_alerts",
        )
    with c3:
        cfg["cooldown_minutes"] = st.number_input(
            "同一标的同一状态冷却分钟",
            min_value=1,
            max_value=240,
            value=int(cfg.get("cooldown_minutes", 30) or 30),
            step=1,
            key="email_v78_cooldown",
        )

    cfg["min_amount_yi"] = st.number_input(
        "最低成交额过滤（亿）",
        min_value=0.0,
        max_value=200.0,
        value=float(cfg.get("min_amount_yi", 0.30) or 0.30),
        step=0.10,
        key="email_v78_min_amount",
    )

    st.markdown("#### SMTP 设置")
    c1, c2, c3 = st.columns([1, 0.5, 0.7])
    with c1:
        cfg["smtp_host"] = st.text_input("SMTP Host", value=_safe_str(cfg.get("smtp_host", "smtp.163.com")), key="email_v78_host")
    with c2:
        cfg["smtp_port"] = int(st.number_input("SMTP Port", min_value=1, max_value=65535, value=int(cfg.get("smtp_port", 465) or 465), key="email_v78_port"))
    with c3:
        cfg["use_ssl"] = st.checkbox("SSL", value=bool(cfg.get("use_ssl", True)), key="email_v78_ssl")

    c1, c2, c3 = st.columns(3)
    with c1:
        cfg["smtp_user"] = st.text_input("SMTP 用户名", value=_safe_str(cfg.get("smtp_user", "")), key="email_v78_user")
    with c2:
        cfg["smtp_pass"] = st.text_input("SMTP 授权码/密码", value=_safe_str(cfg.get("smtp_pass", "")), type="password", key="email_v78_pass")
    with c3:
        cfg["smtp_sender"] = st.text_input("发件人", value=_safe_str(cfg.get("smtp_sender", "")) or _safe_str(cfg.get("smtp_user", "")), key="email_v78_sender")

    cfg["smtp_receiver"] = st.text_input("收件人，多个用英文逗号分隔", value=_safe_str(cfg.get("smtp_receiver", "")), key="email_v78_receiver")
    cfg["subject"] = st.text_input("邮件标题", value=_safe_str(cfg.get("subject", "8502监控提醒")), key="email_v78_subject")

    b1, b2, b3 = st.columns([1, 1, 2])
    with b1:
        if st.button("保存设置", type="primary", key="email_v78_save"):
            save_config(cfg)
            st.success("已保存到 config/email_alert_v7_8.json。")

    with b2:
        if st.button("发送测试邮件", key="email_v78_test"):
            save_config(cfg)
            ok, msg = send_test_email(cfg)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    with b3:
        if st.button("立即检测并发送买点提醒", key="email_v78_send_now"):
            save_config(cfg)
            ok, msg, n = process_realtime_buy_alerts_v7_8(globs)
            if ok:
                st.success(f"{msg} 本轮数量：{n}")
            else:
                st.error(msg)

    st.markdown("#### 当前符合邮件条件的标的")
    df = find_watch_df_from_globals(globs)
    if df.empty:
        st.warning("未找到当前盯盘股票池。请先刷新行情。")
    else:
        alerts = filter_buy_alerts(df, cfg)
        if alerts.empty:
            st.info("当前没有符合买点/半路/封板观察条件的标的。")
        else:
            cols = [c for c in [
                "代码", "名称", "最新价", "涨跌幅", "规则涨速", "涨速",
                "成交额_亿", "换手率", "所属行业", "最强概念",
                "买卖状态", "多空状态", "个股板块联动分",
            ] if c in alerts.columns]
            st.info(f"当前符合提醒条件数量：{len(alerts)}；实际发送会受 Top N 和冷却时间限制。")
            st.dataframe(alerts[cols], hide_index=True, use_container_width=True, height=360)

    last_msg = st.session_state.get("email_v78_last_msg")
    last_count = st.session_state.get("email_v78_last_count")
    last_time = st.session_state.get("email_v78_last_time")
    if last_msg:
        st.caption(f"最近自动检测：{last_time} ｜ 数量：{last_count} ｜ {last_msg}")

    if LOG_PATH.exists():
        with st.expander("邮件发送日志", expanded=False):
            try:
                log = pd.read_csv(LOG_PATH, dtype={"代码": str}).tail(100)
                st.dataframe(log, hide_index=True, use_container_width=True, height=260)
            except Exception as exc:
                st.warning(f"日志读取失败：{exc}")
