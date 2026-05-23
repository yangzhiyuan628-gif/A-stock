# -*- coding: utf-8 -*-
"""
email_smallcap_alert_v8_2_2.py

v8.2.2：邮件模板升级 + 小市值高弹性偏好 + 中军参考 + 大市值例外

策略偏好：
1. 底层更关注“未来估值弹性高的小市值公司”；
2. 中军公司主要作为板块强度和方向参考；
3. 大市值公司只有在特别适合的时候才允许进入买点提醒；
4. 只做提醒和复盘，不自动下单。

输出：
- reports/latest_watch_signals_smallcap_v8_2_2.csv
- reports/email_alert_log_v8_2_2.csv
- data/email_sent_cache_v8_2_2.json
"""

from __future__ import annotations

import json
import os
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
CONFIG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

CONFIG_PATH = CONFIG_DIR / "email_smallcap_alert_v8_2_2.json"
OUT_SNAPSHOT = REPORT_DIR / "latest_watch_signals_smallcap_v8_2_2.csv"
ALERT_LOG = REPORT_DIR / "email_alert_log_v8_2_2.csv"
CACHE_PATH = DATA_DIR / "email_sent_cache_v8_2_2.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "auto_send": False,
    "send_buy_alert": True,
    "send_risk_alert": True,
    "send_summary_only": True,
    "max_alert_rows": 12,
    "cooldown_minutes": 30,
    "same_rule_once_per_day": True,

    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "smtp_user": "",
    "smtp_sender": "",
    "smtp_recipients": "",
    "smtp_use_ssl": True,
    "smtp_password": "",

    "smallcap_preference_enabled": True,
    "allow_missing_market_cap": True,
    "smallcap_total_min_yi": 15.0,
    "smallcap_total_max_yi": 220.0,
    "smallcap_float_max_yi": 180.0,
    "ideal_total_min_yi": 25.0,
    "ideal_total_max_yi": 120.0,
    "future_score_min": 55.0,

    "medium_reference_enabled": True,
    "medium_total_min_yi": 300.0,
    "medium_amount_min_yi": 15.0,
    "show_medium_reference_count": 5,

    "large_cap_exception_enabled": True,
    "large_total_min_yi": 500.0,
    "large_require_emotion": True,
    "large_allowed_emotion_phases": ["强修复", "主升高热"],
    "large_require_market_mode": True,
    "large_allowed_modes": ["龙头模式", "混合模式"],
    "large_min_amount_yi": 20.0,
    "large_require_board_front": True,
    "large_allowed_rule_types": ["扫板", "排板", "回封", "半路"],

    "subject_prefix": "【8502短线信号提醒】",
    "include_medium_reference": True,
    "include_rule_params": False,
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
    env_map = {
        "smtp_host": ["SMTP_HOST", "EMAIL_SMTP_HOST"],
        "smtp_port": ["SMTP_PORT", "EMAIL_SMTP_PORT"],
        "smtp_user": ["SMTP_USER", "EMAIL_USER"],
        "smtp_sender": ["SMTP_SENDER", "EMAIL_SENDER"],
        "smtp_recipients": ["SMTP_RECIPIENTS", "EMAIL_RECIPIENTS", "EMAIL_TO"],
        "smtp_password": ["SMTP_PASSWORD", "EMAIL_PASSWORD", "SMTP_AUTH_CODE"],
    }
    for k, envs in env_map.items():
        if cfg.get(k):
            continue
        for e in envs:
            if os.getenv(e):
                cfg[k] = os.getenv(e)
                break
    try:
        cfg["smtp_port"] = int(cfg.get("smtp_port", 465))
    except Exception:
        cfg["smtp_port"] = 465
    return cfg


def save_config(cfg: dict, save_password: bool = False) -> None:
    out = dict(cfg)
    if not save_password:
        out["smtp_password"] = ""
    CONFIG_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\n", " ").replace("\r", " ").strip()


def _norm_code(x: Any) -> str:
    d = "".join(re.findall(r"\d", str(x)))
    return d[-6:].zfill(6) if d else ""


def _is_missing(x: Any) -> bool:
    try:
        return pd.isna(x)
    except Exception:
        return x is None


def _to_float(x: Any, default: float = float("nan")) -> float:
    if x is None:
        return default
    try:
        if pd.isna(x):
            return default
    except Exception:
        pass
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


def parse_amount_yi(x: Any) -> float:
    if x is None:
        return float("nan")
    try:
        if pd.isna(x):
            return float("nan")
    except Exception:
        pass
    if isinstance(x, (int, float)):
        v = float(x)
        return v / 1e8 if abs(v) > 1e6 else v
    s = str(x).strip().replace(",", "")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return float("nan")
    v = float(m.group(0))
    if "亿" in s:
        return v
    if "万" in s:
        return v / 10000.0
    if "元" in s:
        return v / 1e8
    return v / 1e8 if abs(v) > 1e6 else v


def parse_market_cap_yi(x: Any) -> float:
    if x is None:
        return float("nan")
    try:
        if pd.isna(x):
            return float("nan")
    except Exception:
        pass
    if isinstance(x, (int, float)):
        v = float(x)
        return v / 1e8 if abs(v) > 1e6 else v
    s = str(x).strip().replace(",", "")
    if not s or s in {"-", "--", "None", "nan", "NaN"}:
        return float("nan")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return float("nan")
    v = float(m.group(0))
    if "万亿" in s:
        return v * 10000.0
    if "亿" in s:
        return v
    if "万" in s:
        return v / 10000.0
    if "元" in s:
        return v / 1e8
    return v / 1e8 if abs(v) > 1e6 else v


def find_col(df: pd.DataFrame, names: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    lower = {str(c).lower().strip(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        if n.lower() in lower:
            return lower[n.lower()]
    for c in df.columns:
        cs = str(c).lower()
        for n in names:
            if n.lower() in cs:
                return c
    return None


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


def load_emotion() -> dict:
    p = REPORT_DIR / "market_emotion_v8_0.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_watch_df_from_files() -> pd.DataFrame:
    paths = [
        REPORT_DIR / "latest_watch_signals_kobe_v8_2_1.csv",
        REPORT_DIR / "latest_watch_signals_rule_attribution_v8_2_1.csv",
        REPORT_DIR / "latest_watch_signals_volume_v8_2_2.csv",
        REPORT_DIR / "latest_watch_states_v7_9.csv",
        REPORT_DIR / "latest_watch_signals.csv",
    ]
    for p in paths:
        df = read_csv_safe(p)
        if not df.empty:
            df["_source_file"] = p.name
            return df
    return pd.DataFrame()


def find_watch_df_from_globals(globs: dict | None = None) -> pd.DataFrame:
    globs = globs or {}
    preferred = ["signal_df", "watch_df", "df", "main", "main_df", "data", "rank_df", "pool", "today_pool", "limit_pool"]
    candidates = []
    for name in preferred:
        obj = globs.get(name)
        if isinstance(obj, pd.DataFrame) and not obj.empty:
            cols = set(map(str, obj.columns))
            if any(c in cols for c in ["代码", "股票代码", "证券代码", "code", "symbol"]):
                candidates.append((1000000 + len(obj), name, obj))
    for name, obj in globs.items():
        if isinstance(obj, pd.DataFrame) and not obj.empty:
            cols = set(map(str, obj.columns))
            if any(c in cols for c in ["代码", "股票代码", "证券代码", "code", "symbol"]):
                candidates.append((len(obj), name, obj))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        df = candidates[0][2].copy()
        df["_source_file"] = f"globals:{candidates[0][1]}"
        return df
    return load_watch_df_from_files()


def standardize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    x.columns = [str(c).strip() for c in x.columns]

    if "代码" not in x.columns:
        for c in ["股票代码", "证券代码", "code", "symbol", "ts_code"]:
            if c in x.columns:
                x["代码"] = x[c]
                break
    if "名称" not in x.columns:
        for c in ["股票名称", "证券简称", "name", "stock_name"]:
            if c in x.columns:
                x["名称"] = x[c]
                break
    if "代码" not in x.columns:
        return pd.DataFrame()

    x["代码"] = x["代码"].map(_norm_code)
    if "名称" not in x.columns:
        x["名称"] = x["代码"]

    if "涨幅" in x.columns and "涨跌幅" not in x.columns:
        x["涨跌幅"] = x["涨幅"]
    if "现价" in x.columns and "最新价" not in x.columns:
        x["最新价"] = x["现价"]

    total_col = find_col(x, ["总市值_亿", "总市值", "市值", "total_mv", "total_market_cap", "market_cap"])
    float_col = find_col(x, ["流通市值_亿", "流通市值", "float_mv", "circ_mv", "float_market_cap", "流值"])
    amount_col = find_col(x, ["成交额_亿", "成交额", "amount"])
    pct_col = find_col(x, ["涨跌幅", "涨幅", "pct_chg"])
    speed_col = find_col(x, ["规则涨速", "5分钟涨速", "涨速", "speed"])
    turnover_col = find_col(x, ["换手率", "换手", "turnover", "turnover_rate"])
    vr_col = find_col(x, ["量比", "volume_ratio", "vol_ratio"])

    x["总市值_亿"] = x[total_col].map(parse_market_cap_yi) if total_col else pd.NA
    x["流通市值_亿"] = x[float_col].map(parse_market_cap_yi) if float_col else pd.NA
    x["成交额_亿"] = x[amount_col].map(parse_amount_yi) if amount_col else pd.NA
    x["涨跌幅"] = x[pct_col].map(_to_float) if pct_col else pd.NA
    x["规则涨速"] = x[speed_col].map(_to_float) if speed_col else pd.NA
    x["换手率"] = x[turnover_col].map(_to_float) if turnover_col else pd.NA
    x["量比"] = x[vr_col].map(_to_float) if vr_col else pd.NA

    for c in ["板块内涨幅排名", "板块内成交额排名", "全市场涨速排名", "板块涨停数", "板块强势股数量", "个股板块联动分", "股性评分", "近20日涨停次数", "近20日炸板次数"]:
        if c in x.columns:
            x[c] = x[c].map(_to_float)

    if "rule_name" not in x.columns:
        x["rule_name"] = x.get("买卖状态", x.get("标准状态", "未归因"))
    if "rule_type" not in x.columns:
        x["rule_type"] = x.get("pattern_signal", x.get("标准状态", "观察"))
    if "trade_allowed" not in x.columns:
        status = x.get("买卖状态", x.get("标准状态", pd.Series([""] * len(x)))).astype(str)
        x["trade_allowed"] = status.str.contains("半路|扫板|排板|回封|买点|接近涨停|封板", regex=True, na=False)

    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    return x


def is_truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = _safe_str(v).lower()
    return s in {"true", "1", "yes", "y", "是", "通过", "允许", "买点", "触发"}


def board_front(row: pd.Series, cfg: dict) -> bool:
    for c in ["板块前排", "是否板块前排", "人气前排"]:
        if c in row.index and is_truthy(row.get(c)):
            return True
    rank1 = row.get("板块内涨幅排名", pd.NA)
    rank2 = row.get("板块内成交额排名", pd.NA)
    try:
        if not _is_missing(rank1) and float(rank1) <= 3:
            return True
    except Exception:
        pass
    try:
        if not _is_missing(rank2) and float(rank2) <= 5:
            return True
    except Exception:
        pass
    return False


def calc_future_score(row: pd.Series, cfg: dict, emotion: dict) -> tuple[float, str]:
    score = 0.0
    reasons = []
    total = row.get("总市值_亿", pd.NA)
    flt = row.get("流通市值_亿", pd.NA)

    if not _is_missing(total):
        total_f = float(total)
        if cfg["ideal_total_min_yi"] <= total_f <= cfg["ideal_total_max_yi"]:
            score += 30
            reasons.append(f"理想小市值{total_f:.1f}亿")
        elif cfg["smallcap_total_min_yi"] <= total_f <= cfg["smallcap_total_max_yi"]:
            score += 22
            reasons.append(f"小市值区间{total_f:.1f}亿")
        elif total_f < cfg["smallcap_total_min_yi"]:
            score += 8
            reasons.append(f"市值过小{total_f:.1f}亿，弹性有但风险高")
        elif total_f >= cfg["large_total_min_yi"]:
            score += 2
            reasons.append(f"大市值{total_f:.1f}亿，弹性较弱")
        else:
            score += 10
            reasons.append(f"中等市值{total_f:.1f}亿")
    else:
        if cfg.get("allow_missing_market_cap", True):
            score += 12
            reasons.append("市值缺失，暂不过滤")
        else:
            reasons.append("市值缺失")

    if not _is_missing(flt) and float(flt) <= cfg["smallcap_float_max_yi"]:
        score += 8
        reasons.append(f"流通市值较小{float(flt):.1f}亿")

    text = " ".join(_safe_str(row.get(c, "")) for c in ["最强概念", "所属概念", "所属行业", "新闻催化", "题材催化", "公告", "trigger_reason"] if c in row.index)
    hot_words = ["AI", "算力", "机器人", "低空", "半导体", "芯片", "新能源", "固态", "并购", "重组", "订单", "政策", "数据中心"]
    hit_words = [w for w in hot_words if w.lower() in text.lower()]
    if hit_words:
        score += min(15, 5 + len(hit_words) * 3)
        reasons.append("题材关键词:" + "/".join(hit_words[:5]))
    if any(k in text for k in ["新闻", "公告", "政策", "订单", "并购", "重组", "中标"]):
        score += 10
        reasons.append("存在新闻/公告/催化文本")
    if board_front(row, cfg):
        score += 12
        reasons.append("板块/人气前排")
    amount = row.get("成交额_亿", pd.NA)
    if not _is_missing(amount):
        a = float(amount)
        if a >= 1:
            score += min(10, a / 3)
            reasons.append(f"成交活跃{a:.1f}亿")
    speed_rank = row.get("全市场涨速排名", pd.NA)
    if not _is_missing(speed_rank) and float(speed_rank) <= 100:
        score += 8
        reasons.append(f"涨速排名{float(speed_rank):.0f}")
    recent_limit = row.get("近20日涨停次数", pd.NA)
    if not _is_missing(recent_limit) and float(recent_limit) >= 1:
        score += 6
        reasons.append("近期有涨停记忆")
    stock_char = row.get("股性评分", pd.NA)
    if not _is_missing(stock_char) and float(stock_char) >= 60:
        score += 6
        reasons.append(f"股性评分{float(stock_char):.0f}")
    phase = _safe_str(emotion.get("emotion_phase", ""))
    if phase in {"强修复", "主升高热"}:
        score += 5
        reasons.append(f"市场情绪{phase}")
    score = max(0.0, min(100.0, round(score, 2)))
    return score, "；".join(reasons) if reasons else "缺少估值弹性代理字段"


def classify_marketcap_role(row: pd.Series, cfg: dict) -> str:
    total = row.get("总市值_亿", pd.NA)
    amount = row.get("成交额_亿", pd.NA)
    if _is_missing(total):
        return "市值未知"
    t = float(total)
    a = float(amount) if not _is_missing(amount) else 0.0
    if cfg["smallcap_total_min_yi"] <= t <= cfg["smallcap_total_max_yi"]:
        return "小市值高弹性"
    if t >= cfg["large_total_min_yi"]:
        return "大市值"
    if t >= cfg["medium_total_min_yi"] or a >= cfg["medium_amount_min_yi"]:
        return "中军参考"
    return "中等市值"


def large_cap_exception(row: pd.Series, cfg: dict, emotion: dict) -> tuple[bool, str]:
    if not cfg.get("large_cap_exception_enabled", True):
        return False, "大市值例外未启用"
    total = row.get("总市值_亿", pd.NA)
    if _is_missing(total) or float(total) < float(cfg["large_total_min_yi"]):
        return False, "非大市值"
    reasons = []
    phase = _safe_str(emotion.get("emotion_phase", "未知"))
    mode = _safe_str(row.get("market_mode_effective", ""))
    if cfg.get("large_require_emotion", True):
        allowed = set(cfg.get("large_allowed_emotion_phases", ["强修复", "主升高热"]))
        if phase not in allowed:
            return False, f"情绪{phase}不满足大市值例外"
        reasons.append(f"情绪{phase}")
    if cfg.get("large_require_market_mode", True):
        allowed_modes = set(cfg.get("large_allowed_modes", ["龙头模式", "混合模式"]))
        if mode and mode not in allowed_modes:
            return False, f"市场模式{mode}不满足大市值例外"
        reasons.append(f"模式{mode or '未知'}")
    amount = row.get("成交额_亿", pd.NA)
    if _is_missing(amount) or float(amount) < float(cfg["large_min_amount_yi"]):
        return False, f"成交额不足{amount}"
    reasons.append(f"成交额{float(amount):.1f}亿")
    if cfg.get("large_require_board_front", True) and not board_front(row, cfg):
        return False, "非板块/人气前排"
    reasons.append("板块前排")
    rt = _safe_str(row.get("rule_type", ""))
    allowed_types = set(cfg.get("large_allowed_rule_types", ["扫板", "排板", "回封", "半路"]))
    if rt and rt not in allowed_types:
        return False, f"规则类型{rt}不允许大市值例外"
    reasons.append(f"规则{rt or '未知'}")
    return True, "大市值例外通过：" + "；".join(reasons)


def _board_key(row: pd.Series) -> str:
    for c in ["最强概念", "所属概念", "所属行业"]:
        v = _safe_str(row.get(c, ""))
        if v and v not in {"nan", "None", "未知"}:
            return v.split(",")[0].split("，")[0].strip()
    return "未知"


def _fmt(x: Any, nd: int = 2) -> str:
    if _is_missing(x):
        return "-"
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return _safe_str(x)


def build_medium_reference_map(df: pd.DataFrame, cfg: dict) -> dict[str, str]:
    if not cfg.get("medium_reference_enabled", True) or df.empty:
        return {}
    x = df.copy()
    x["_board_key"] = x.apply(_board_key, axis=1)
    x["_total"] = pd.to_numeric(x.get("总市值_亿"), errors="coerce")
    x["_amount"] = pd.to_numeric(x.get("成交额_亿"), errors="coerce")
    role = x.get("市值角色", pd.Series([""] * len(x))).astype(str)
    is_ref = (x["_total"] >= float(cfg.get("medium_total_min_yi", 300))) | (x["_amount"] >= float(cfg.get("medium_amount_min_yi", 15))) | role.isin(["中军参考", "大市值"])
    x = x[is_ref].copy()
    if x.empty:
        return {}
    out = {}
    for board, g in x.groupby("_board_key"):
        gg = g.sort_values(["_amount", "_total"], ascending=False).head(int(cfg.get("show_medium_reference_count", 5)))
        parts = []
        for _, r in gg.iterrows():
            parts.append(f"{r.get('名称','')}({r.get('代码','')},市值{_fmt(r.get('总市值_亿'))}亿,额{_fmt(r.get('成交额_亿'))}亿)")
        out[board] = "；".join(parts)
    return out


def enhance_smallcap_style(df: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    emotion = load_emotion()
    x = standardize_df(df)
    if x.empty:
        return pd.DataFrame()

    roles, scores, score_reasons, style_pass, style_reason, large_passes, large_reasons, final_trade = [], [], [], [], [], [], [], []
    for _, row in x.iterrows():
        role = classify_marketcap_role(row, cfg)
        score, sreason = calc_future_score(row, cfg, emotion)
        lp, lreason = large_cap_exception(row, cfg, emotion)
        base_trade = is_truthy(row.get("trade_allowed", False))
        rule_type = _safe_str(row.get("rule_type", ""))
        is_risk = rule_type == "风控" or "风险" in _safe_str(row.get("pattern_signal", "")) or "风控" in _safe_str(row.get("rule_name", ""))
        if is_risk:
            spass = True
            reason = "风控信号不受小市值偏好限制"
            ftrade = True
        elif not cfg.get("smallcap_preference_enabled", True):
            spass = True
            reason = "小市值偏好未启用"
            ftrade = base_trade
        elif role == "小市值高弹性":
            spass = score >= float(cfg["future_score_min"])
            reason = f"小市值策略：弹性分{score:.1f}，阈值{cfg['future_score_min']}"
            ftrade = base_trade and spass
        elif role == "市值未知":
            spass = bool(cfg.get("allow_missing_market_cap", True))
            reason = "市值未知：" + ("允许通过" if spass else "不允许通过")
            ftrade = base_trade and spass
        elif role == "大市值":
            spass = lp
            reason = lreason
            ftrade = base_trade and lp
        elif role == "中军参考":
            spass = False
            reason = "中军公司作为板块方向和强度参考，默认不作为买点；需满足大市值例外才提醒买入"
            ftrade = False
        else:
            spass = score >= float(cfg["future_score_min"]) + 8
            reason = f"中等市值需更高弹性分：{score:.1f}"
            ftrade = base_trade and spass
        roles.append(role)
        scores.append(score)
        score_reasons.append(sreason)
        style_pass.append(spass)
        style_reason.append(reason)
        large_passes.append(lp)
        large_reasons.append(lreason)
        final_trade.append(bool(ftrade))

    x["市值角色"] = roles
    x["未来估值弹性分"] = scores
    x["估值弹性原因"] = score_reasons
    x["市值风格通过"] = style_pass
    x["市值风格原因"] = style_reason
    x["大市值例外通过"] = large_passes
    x["大市值例外原因"] = large_reasons
    x["最终邮件触发"] = final_trade
    ref_map = build_medium_reference_map(x, cfg)
    x["中军参考"] = x.apply(lambda r: ref_map.get(_board_key(r), ""), axis=1)
    sort_cols = [c for c in ["最终邮件触发", "未来估值弹性分", "涨跌幅"] if c in x.columns]
    if sort_cols:
        x = x.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
    x.to_csv(OUT_SNAPSHOT, index=False, encoding="utf-8-sig")
    return x


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def should_send(row: pd.Series, cfg: dict, cache: dict, now: datetime) -> tuple[bool, str]:
    code = _safe_str(row.get("代码", ""))
    rule = _safe_str(row.get("rule_name", ""))
    signal = _safe_str(row.get("pattern_signal", row.get("rule_type", "")))
    today = now.strftime("%Y-%m-%d")
    key = f"{today}|{code}|{rule}|{signal}" if cfg.get("same_rule_once_per_day", True) else f"{code}|{rule}|{signal}"
    last = cache.get(key)
    if last:
        try:
            lt = datetime.fromisoformat(last)
            if cfg.get("same_rule_once_per_day", True):
                return False, "同股同规则今日已发送"
            if now - lt < timedelta(minutes=int(cfg.get("cooldown_minutes", 30))):
                return False, f"{cfg.get('cooldown_minutes', 30)}分钟冷却中"
        except Exception:
            pass
    return True, key


def select_alert_rows(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    x = df.copy()
    rt = x.get("rule_type", pd.Series([""] * len(x))).astype(str)
    pattern = x.get("pattern_signal", pd.Series([""] * len(x))).astype(str)
    final = x.get("最终邮件触发", pd.Series([False] * len(x))).map(is_truthy)
    is_risk = (rt == "风控") | pattern.str.contains("风险|卖出|炸板|中位|退潮|失效", regex=True, na=False)
    buy = x[final & (~is_risk)].copy()
    risk = x[final & is_risk].copy()
    sort_cols = [c for c in ["未来估值弹性分", "涨跌幅", "成交额_亿"] if c in x.columns]
    if sort_cols:
        buy = buy.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
        risk = risk.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
    return buy.head(int(cfg.get("max_alert_rows", 12))), risk.head(int(cfg.get("max_alert_rows", 12)))


def make_email_subject(buy_df: pd.DataFrame, risk_df: pd.DataFrame, cfg: dict, emotion: dict) -> str:
    phase = emotion.get("emotion_phase", "未知")
    score = emotion.get("emotion_score", "-")
    nb = len(buy_df) if buy_df is not None else 0
    nr = len(risk_df) if risk_df is not None else 0
    return f"{cfg.get('subject_prefix', '【8502短线信号提醒】')}买点{nb}只/风险{nr}只｜情绪{phase}{score}"


def format_stock_block(row: pd.Series, idx: int, cfg: dict) -> str:
    lines = []
    lines.append(f"{idx}. {row.get('名称','')}（{row.get('代码','')}）")
    lines.append(f"   规则：{row.get('rule_name','')} ｜ 类型：{row.get('rule_type','')} ｜ 版本：{row.get('rule_version','')}")
    lines.append(f"   模式：{row.get('market_mode_effective','')} ｜ 信号：{row.get('pattern_signal','')} ｜ 市值角色：{row.get('市值角色','')}")
    lines.append(f"   涨幅：{_fmt(row.get('涨跌幅'))}% ｜ 涨速：{_fmt(row.get('规则涨速'))}% ｜ 成交额：{_fmt(row.get('成交额_亿'))}亿 ｜ 换手：{_fmt(row.get('换手率'))}% ｜ 量比：{_fmt(row.get('量比'))}")
    lines.append(f"   总市值：{_fmt(row.get('总市值_亿'))}亿 ｜ 流通市值：{_fmt(row.get('流通市值_亿'))}亿 ｜ 弹性分：{_fmt(row.get('未来估值弹性分'), 1)}")
    lines.append(f"   行业/概念：{row.get('所属行业','')} ｜ {row.get('最强概念', row.get('所属概念',''))}")
    if cfg.get("include_medium_reference", True):
        ref = _safe_str(row.get("中军参考", ""))
        if ref:
            lines.append(f"   中军参考：{ref}")
    lines.append(f"   触发原因：{row.get('trigger_reason', row.get('市值风格原因',''))}")
    lines.append(f"   市值逻辑：{row.get('市值风格原因','')}；{row.get('估值弹性原因','')}")
    if cfg.get("include_rule_params", False):
        lines.append(f"   参数快照：{row.get('rule_params','')}")
    return "\n".join(lines)


def make_email_body(buy_df: pd.DataFrame, risk_df: pd.DataFrame, cfg: dict, emotion: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("【8502短线信号提醒 v8.2.2】")
    lines.append("")
    lines.append(f"触发时间：{now}")
    lines.append(f"市场情绪：{emotion.get('emotion_phase','未知')} ｜ 情绪分：{emotion.get('emotion_score','-')} ｜ 主线状态：{emotion.get('mainline_status','-')}")
    lines.append("")
    lines.append("策略偏好：优先关注未来估值弹性较高的小市值公司；中军公司主要作为板块方向参考；大市值只在强情绪、前排、放量、核心规则触发时例外提醒。")
    lines.append("提醒性质：只做盯盘提醒，不自动下单，不承诺收益。")
    lines.append("")
    if buy_df is not None and not buy_df.empty:
        lines.append("一、买点/观察信号")
        for i, (_, row) in enumerate(buy_df.iterrows(), 1):
            lines.append(format_stock_block(row, i, cfg))
            lines.append("")
    else:
        lines.append("一、买点/观察信号：暂无")
        lines.append("")
    if risk_df is not None and not risk_df.empty:
        lines.append("二、风险/卖点信号")
        for i, (_, row) in enumerate(risk_df.iterrows(), 1):
            lines.append(format_stock_block(row, i, cfg))
            lines.append("")
    else:
        lines.append("二、风险/卖点信号：暂无")
        lines.append("")
    lines.append("三、操作提醒")
    lines.append("- 激进：只考虑规则通过、板块前排、量能确认的小市值高弹性标的。")
    lines.append("- 稳健：等待回踩不破、二次上攻、回封确认。")
    lines.append("- 风控：退潮/冰点、炸板扩散、中位股亏钱效应明显时减少出手。")
    lines.append("- 大市值：默认只看作中军参考；只有强修复/主升高热且板块核心前排时才考虑。")
    return "\n".join(lines)


def send_mail(subject: str, body: str, cfg: dict) -> tuple[bool, str]:
    host = _safe_str(cfg.get("smtp_host"))
    port = int(cfg.get("smtp_port", 465))
    user = _safe_str(cfg.get("smtp_user"))
    sender = _safe_str(cfg.get("smtp_sender") or user)
    password = _safe_str(cfg.get("smtp_password") or os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASSWORD") or os.getenv("SMTP_AUTH_CODE"))
    recipients = _safe_str(cfg.get("smtp_recipients"))
    if not host or not port or not sender or not recipients:
        return False, "SMTP配置不完整：host/port/sender/recipients不能为空"
    if not password:
        return False, "SMTP密码/授权码为空。建议写入环境变量 SMTP_PASSWORD 或在页面临时输入。"
    to_list = [x.strip() for x in re.split(r"[,;，；\s]+", recipients) if x.strip()]
    if not to_list:
        return False, "收件人为空"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    try:
        if bool(cfg.get("smtp_use_ssl", True)):
            server = smtplib.SMTP_SSL(host, port, timeout=25)
        else:
            server = smtplib.SMTP(host, port, timeout=25)
            server.starttls()
        try:
            server.login(user or sender, password)
            server.sendmail(sender, to_list, msg.as_string())
        finally:
            server.quit()
        return True, f"邮件发送成功：{len(to_list)} 个收件人"
    except Exception as exc:
        return False, f"邮件发送失败：{type(exc).__name__}: {exc}"


def append_alert_log(rows: list[dict]) -> None:
    if not rows:
        return
    new = pd.DataFrame(rows)
    if ALERT_LOG.exists():
        old = read_csv_safe(ALERT_LOG)
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    out.to_csv(ALERT_LOG, index=False, encoding="utf-8-sig")


def process_smallcap_alerts_v8_2_2(globs: dict | None = None, force_send: bool = False) -> tuple[bool, str, pd.DataFrame]:
    cfg = load_config()
    emotion = load_emotion()
    raw = find_watch_df_from_globals(globs)
    if raw.empty:
        return False, "没有读取到盯盘股票池。", pd.DataFrame()
    df = enhance_smallcap_style(raw, cfg)
    if df.empty:
        return False, "小市值风格增强后为空。", pd.DataFrame()
    buy_df, risk_df = select_alert_rows(df, cfg)
    if not cfg.get("send_buy_alert", True):
        buy_df = pd.DataFrame()
    if not cfg.get("send_risk_alert", True):
        risk_df = pd.DataFrame()
    if buy_df.empty and risk_df.empty:
        return True, "没有符合邮件提醒的信号。", df
    now = datetime.now()
    cache = load_cache()
    send_buy_rows, send_risk_rows, cache_updates = [], [], []
    for kind, part in [("buy", buy_df), ("risk", risk_df)]:
        for _, row in part.iterrows():
            ok, key_or_reason = should_send(row, cfg, cache, now)
            if force_send:
                ok = True
                key_or_reason = f"force|{now.isoformat()}|{row.get('代码','')}|{row.get('rule_name','')}"
            if ok:
                if kind == "buy":
                    send_buy_rows.append(row)
                else:
                    send_risk_rows.append(row)
                cache_updates.append(key_or_reason)
    send_buy_df = pd.DataFrame(send_buy_rows)
    send_risk_df = pd.DataFrame(send_risk_rows)
    if send_buy_df.empty and send_risk_df.empty:
        return True, "信号存在，但均在去重/冷却期内，未重复发送。", df
    if not (cfg.get("enabled", False) and (cfg.get("auto_send", False) or force_send)):
        return True, f"发现待提醒信号：买点{len(send_buy_df)}只，风险{len(send_risk_df)}只；邮件未启用自动发送。", df
    subject = make_email_subject(send_buy_df, send_risk_df, cfg, emotion)
    body = make_email_body(send_buy_df, send_risk_df, cfg, emotion)
    ok, msg = send_mail(subject, body, cfg)
    log_rows = []
    for kind, part in [("buy", send_buy_df), ("risk", send_risk_df)]:
        if part is None or part.empty:
            continue
        for _, row in part.iterrows():
            log_rows.append({
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "send_ok": ok,
                "message": msg,
                "代码": row.get("代码", ""),
                "名称": row.get("名称", ""),
                "rule_name": row.get("rule_name", ""),
                "rule_type": row.get("rule_type", ""),
                "pattern_signal": row.get("pattern_signal", ""),
                "市值角色": row.get("市值角色", ""),
                "未来估值弹性分": row.get("未来估值弹性分", ""),
                "涨跌幅": row.get("涨跌幅", ""),
                "成交额_亿": row.get("成交额_亿", ""),
                "trigger_reason": row.get("trigger_reason", ""),
            })
    append_alert_log(log_rows)
    if ok:
        for key in cache_updates:
            cache[key] = now.isoformat()
        save_cache(cache)
    return ok, msg, df


def render_email_smallcap_alert_panel_v8_2_2(globs: dict | None = None) -> None:
    import streamlit as st
    cfg = load_config()
    st.subheader("v8.2.2 邮件提醒：小市值高弹性优先 + 中军参考 + 大市值例外")
    st.caption("符合 v8.2.1 规则后，再经过市值风格过滤；默认优先提醒小市值高弹性票，中军作为参考，大市值只有强情绪/前排/放量时例外提醒。")

    with st.expander("一、邮件发送设置", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cfg["enabled"] = st.checkbox("启用邮件模块", value=bool(cfg.get("enabled", False)), key="mail822_enabled")
        with c2:
            cfg["auto_send"] = st.checkbox("符合信号自动发送", value=bool(cfg.get("auto_send", False)), key="mail822_auto")
        with c3:
            cfg["send_buy_alert"] = st.checkbox("发送买点提醒", value=bool(cfg.get("send_buy_alert", True)), key="mail822_buy")
        with c4:
            cfg["send_risk_alert"] = st.checkbox("发送风险提醒", value=bool(cfg.get("send_risk_alert", True)), key="mail822_risk")
        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["max_alert_rows"] = st.number_input("单次最多提醒股票数", 1, 100, int(cfg.get("max_alert_rows", 12)), 1, key="mail822_max_rows")
        with c2:
            cfg["cooldown_minutes"] = st.number_input("冷却分钟", 1, 1440, int(cfg.get("cooldown_minutes", 30)), 1, key="mail822_cool")
        with c3:
            cfg["same_rule_once_per_day"] = st.checkbox("同股同规则每日只发一次", value=bool(cfg.get("same_rule_once_per_day", True)), key="mail822_once")
        cfg["subject_prefix"] = st.text_input("邮件标题前缀", value=str(cfg.get("subject_prefix", "【8502短线信号提醒】")), key="mail822_subject")

    with st.expander("二、SMTP配置", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["smtp_host"] = st.text_input("SMTP Host", value=str(cfg.get("smtp_host", "smtp.qq.com")), key="mail822_host")
        with c2:
            cfg["smtp_port"] = st.number_input("SMTP Port", 1, 65535, int(cfg.get("smtp_port", 465)), 1, key="mail822_port")
        with c3:
            cfg["smtp_use_ssl"] = st.checkbox("使用SSL", value=bool(cfg.get("smtp_use_ssl", True)), key="mail822_ssl")
        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["smtp_user"] = st.text_input("SMTP用户名", value=str(cfg.get("smtp_user", "")), key="mail822_user")
        with c2:
            cfg["smtp_sender"] = st.text_input("发件人", value=str(cfg.get("smtp_sender", cfg.get("smtp_user", ""))), key="mail822_sender")
        with c3:
            cfg["smtp_recipients"] = st.text_input("收件人，多个用逗号", value=str(cfg.get("smtp_recipients", "")), key="mail822_recipients")
        cfg["smtp_password"] = st.text_input("SMTP授权码/密码", value=str(cfg.get("smtp_password", "")), type="password", key="mail822_pwd")
        save_pwd = st.checkbox("把SMTP授权码保存到config文件", value=False, key="mail822_save_pwd")
        st.caption("更推荐写到 .env：SMTP_PASSWORD=你的授权码。")

    with st.expander("三、小市值高弹性偏好", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cfg["smallcap_preference_enabled"] = st.checkbox("启用小市值偏好", value=bool(cfg.get("smallcap_preference_enabled", True)), key="mail822_small_enabled")
        with c2:
            cfg["allow_missing_market_cap"] = st.checkbox("市值缺失时允许通过", value=bool(cfg.get("allow_missing_market_cap", True)), key="mail822_allow_missing_mv")
        with c3:
            cfg["future_score_min"] = st.number_input("未来估值弹性分阈值", 0.0, 100.0, float(cfg.get("future_score_min", 55.0)), 1.0, key="mail822_future_score")
        with c4:
            cfg["include_medium_reference"] = st.checkbox("邮件显示中军参考", value=bool(cfg.get("include_medium_reference", True)), key="mail822_include_medium")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cfg["smallcap_total_min_yi"] = st.number_input("小市值总市值下限 亿", 0.0, 10000.0, float(cfg.get("smallcap_total_min_yi", 15.0)), 1.0, key="mail822_small_min")
        with c2:
            cfg["smallcap_total_max_yi"] = st.number_input("小市值总市值上限 亿", 0.0, 10000.0, float(cfg.get("smallcap_total_max_yi", 220.0)), 1.0, key="mail822_small_max")
        with c3:
            cfg["ideal_total_min_yi"] = st.number_input("理想总市值下限 亿", 0.0, 10000.0, float(cfg.get("ideal_total_min_yi", 25.0)), 1.0, key="mail822_ideal_min")
        with c4:
            cfg["ideal_total_max_yi"] = st.number_input("理想总市值上限 亿", 0.0, 10000.0, float(cfg.get("ideal_total_max_yi", 120.0)), 1.0, key="mail822_ideal_max")
        c1, c2 = st.columns(2)
        with c1:
            cfg["smallcap_float_max_yi"] = st.number_input("小市值流通市值上限 亿", 0.0, 10000.0, float(cfg.get("smallcap_float_max_yi", 180.0)), 1.0, key="mail822_float_max")
        with c2:
            cfg["medium_reference_enabled"] = st.checkbox("启用中军参考", value=bool(cfg.get("medium_reference_enabled", True)), key="mail822_medium_enabled")

    with st.expander("四、中军参考 / 大市值例外", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["medium_total_min_yi"] = st.number_input("中军参考：总市值≥亿", 0.0, 100000.0, float(cfg.get("medium_total_min_yi", 300.0)), 10.0, key="mail822_medium_mv")
        with c2:
            cfg["medium_amount_min_yi"] = st.number_input("中军参考：成交额≥亿", 0.0, 10000.0, float(cfg.get("medium_amount_min_yi", 15.0)), 1.0, key="mail822_medium_amount")
        with c3:
            cfg["show_medium_reference_count"] = st.number_input("每个板块显示中军数", 1, 20, int(cfg.get("show_medium_reference_count", 5)), 1, key="mail822_medium_count")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cfg["large_cap_exception_enabled"] = st.checkbox("启用大市值例外", value=bool(cfg.get("large_cap_exception_enabled", True)), key="mail822_large_enabled")
        with c2:
            cfg["large_total_min_yi"] = st.number_input("大市值定义：总市值≥亿", 0.0, 100000.0, float(cfg.get("large_total_min_yi", 500.0)), 10.0, key="mail822_large_mv")
        with c3:
            cfg["large_min_amount_yi"] = st.number_input("大市值例外：成交额≥亿", 0.0, 10000.0, float(cfg.get("large_min_amount_yi", 20.0)), 1.0, key="mail822_large_amount")
        with c4:
            cfg["large_require_board_front"] = st.checkbox("大市值必须板块前排", value=bool(cfg.get("large_require_board_front", True)), key="mail822_large_front")
        cfg["large_require_emotion"] = st.checkbox("大市值必须强情绪", value=bool(cfg.get("large_require_emotion", True)), key="mail822_large_emotion")
        cfg["large_require_market_mode"] = st.checkbox("大市值必须龙头/混合模式", value=bool(cfg.get("large_require_market_mode", True)), key="mail822_large_mode")

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("保存邮件/市值设置", type="primary", key="mail822_save"):
            save_config(cfg, save_password=save_pwd)
            st.success("已保存 config/email_smallcap_alert_v8_2_2.json。")
    with b2:
        if st.button("刷新小市值风格快照", key="mail822_refresh"):
            save_config(cfg, save_password=save_pwd)
            raw = find_watch_df_from_globals(globs)
            out = enhance_smallcap_style(raw, cfg)
            st.success(f"已生成 {len(out)} 条快照。")
    with b3:
        if st.button("发送测试邮件", key="mail822_test"):
            save_config(cfg, save_password=save_pwd)
            ok, msg = send_mail("【测试】8502邮件提醒v8.2.2", "这是一封测试邮件。", cfg)
            st.success(msg) if ok else st.error(msg)
    with b4:
        if st.button("立即按当前信号发送", key="mail822_force"):
            save_config(cfg, save_password=save_pwd)
            ok, msg, _ = process_smallcap_alerts_v8_2_2(globs, force_send=True)
            st.success(msg) if ok else st.error(msg)

    ok, msg, df = process_smallcap_alerts_v8_2_2(globs, force_send=False)
    st.info(msg)
    if df is not None and not df.empty:
        show_cols = [c for c in ["代码", "名称", "最新价", "涨跌幅", "规则涨速", "成交额_亿", "换手率", "量比", "总市值_亿", "流通市值_亿", "市值角色", "未来估值弹性分", "市值风格通过", "大市值例外通过", "最终邮件触发", "rule_name", "rule_type", "pattern_signal", "所属行业", "最强概念", "中军参考", "市值风格原因"] if c in df.columns]
        st.dataframe(df[show_cols].head(300), hide_index=True, use_container_width=True, height=420)
    if ALERT_LOG.exists():
        with st.expander("邮件发送日志", expanded=False):
            log = read_csv_safe(ALERT_LOG)
            st.dataframe(log.tail(200).sort_index(ascending=False), hide_index=True, use_container_width=True, height=260)
