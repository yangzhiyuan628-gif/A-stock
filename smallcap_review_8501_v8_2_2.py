# -*- coding: utf-8 -*-
"""
smallcap_review_8501_v8_2_2.py

8501：AI游资复盘接入“小市值高弹性偏好 + 中军参考 + 大市值例外”。

定位：
- 8502 负责盘中实时盯盘、触发信号、邮件提醒；
- 8501 负责盘后复盘、明日方向、候选池和AI游资复盘报告；
- 本模块把8502产生的小市值风格快照接入8501，让AI复盘更偏向“小市值高弹性”，同时把中军作为板块参考。

优先读取：
1. reports/latest_watch_signals_smallcap_v8_2_2.csv
2. reports/latest_watch_signals_kobe_v8_2_1.csv
3. reports/latest_watch_signals_rule_attribution_v8_2_1.csv
4. reports/latest_watch_states_v7_9.csv
5. reports/latest_watch_signals.csv

输出：
- reports/ai_youzhi_smallcap_pool_8501_v8_2_2.csv
- reports/ai_youzhi_smallcap_review_8501_v8_2_2.md
- config/smallcap_review_8501_v8_2_2.json
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

CONFIG_PATH = CONFIG_DIR / "smallcap_review_8501_v8_2_2.json"
POOL_PATH = REPORT_DIR / "ai_youzhi_smallcap_pool_8501_v8_2_2.csv"
REVIEW_PATH = REPORT_DIR / "ai_youzhi_smallcap_review_8501_v8_2_2.md"

DEFAULT_CONFIG = {
    "enabled": True,
    "top_n": 30,
    "smallcap_priority": True,
    "future_score_min": 55.0,
    "smallcap_total_min_yi": 15.0,
    "smallcap_total_max_yi": 220.0,
    "ideal_total_min_yi": 25.0,
    "ideal_total_max_yi": 120.0,
    "medium_reference_enabled": True,
    "medium_total_min_yi": 300.0,
    "medium_amount_min_yi": 15.0,
    "large_exception_enabled": True,
    "large_total_min_yi": 500.0,
    "large_min_amount_yi": 20.0,
    "ai_enabled": True,
    "ai_base_url": "https://api.deepseek.com",
    "ai_model": "deepseek-chat",
    "ai_temperature": 0.35,
    "ai_max_tokens": 3600,
    "style": "短线游资复盘风格：优先小市值高弹性，重视题材、情绪、板块前排、中军强度；大市值只有强情绪/核心前排时例外。",
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
    cfg["ai_base_url"] = os.getenv("AI_BASE_URL", cfg.get("ai_base_url", "https://api.deepseek.com")).rstrip("/")
    cfg["ai_model"] = os.getenv("AI_MODEL", cfg.get("ai_model", "deepseek-chat"))
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


def _missing(x: Any) -> bool:
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


def parse_yi(x: Any) -> float:
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
        return v * 10000
    if "亿" in s:
        return v
    if "万" in s:
        return v / 10000
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


def load_8502_snapshot() -> pd.DataFrame:
    paths = [
        REPORT_DIR / "latest_watch_signals_smallcap_v8_2_2.csv",
        REPORT_DIR / "latest_watch_signals_kobe_v8_2_1.csv",
        REPORT_DIR / "latest_watch_signals_rule_attribution_v8_2_1.csv",
        REPORT_DIR / "latest_watch_states_v7_9.csv",
        REPORT_DIR / "latest_watch_signals.csv",
    ]
    for p in paths:
        df = read_csv_safe(p)
        if not df.empty:
            df["_source_file"] = p.name
            return df
    return pd.DataFrame()


def standardize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    x = df.copy()
    x.columns = [str(c).strip() for c in x.columns]

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

    if "代码" not in x.columns:
        return pd.DataFrame()

    x["代码"] = x["代码"].map(_norm_code)
    if "名称" not in x.columns:
        x["名称"] = x["代码"]

    if "涨幅" in x.columns and "涨跌幅" not in x.columns:
        x["涨跌幅"] = x["涨幅"]
    if "现价" in x.columns and "最新价" not in x.columns:
        x["最新价"] = x["现价"]

    total_col = find_col(x, ["总市值_亿", "总市值", "市值", "total_mv", "market_cap"])
    float_col = find_col(x, ["流通市值_亿", "流通市值", "float_mv", "circ_mv"])
    amount_col = find_col(x, ["成交额_亿", "成交额", "amount"])
    pct_col = find_col(x, ["涨跌幅", "涨幅", "pct_chg"])
    speed_col = find_col(x, ["规则涨速", "5分钟涨速", "涨速", "speed"])
    turnover_col = find_col(x, ["换手率", "换手", "turnover"])
    vr_col = find_col(x, ["量比", "volume_ratio", "vol_ratio"])

    x["总市值_亿"] = x[total_col].map(parse_yi) if total_col else pd.NA
    x["流通市值_亿"] = x[float_col].map(parse_yi) if float_col else pd.NA
    x["成交额_亿"] = x[amount_col].map(parse_yi) if amount_col else pd.NA
    x["涨跌幅"] = x[pct_col].map(_to_float) if pct_col else pd.NA
    x["规则涨速"] = x[speed_col].map(_to_float) if speed_col else pd.NA
    x["换手率"] = x[turnover_col].map(_to_float) if turnover_col else pd.NA
    x["量比"] = x[vr_col].map(_to_float) if vr_col else pd.NA

    if "rule_name" not in x.columns:
        x["rule_name"] = x.get("买卖状态", x.get("标准状态", "未归因"))
    if "rule_type" not in x.columns:
        x["rule_type"] = x.get("pattern_signal", x.get("标准状态", "观察"))
    if "pattern_signal" not in x.columns:
        x["pattern_signal"] = x.get("买卖状态", x.get("标准状态", ""))

    for c in ["未来估值弹性分", "板块内涨幅排名", "板块内成交额排名", "全市场涨速排名", "股性评分", "个股板块联动分"]:
        if c in x.columns:
            x[c] = x[c].map(_to_float)

    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    return x


def board_key(row: pd.Series) -> str:
    for c in ["最强概念", "所属概念", "所属行业"]:
        v = _safe_str(row.get(c, ""))
        if v and v not in {"nan", "None", "未知"}:
            return re.split(r"[,，/|;；]", v)[0].strip()
    return "未知"


def is_board_front(row: pd.Series) -> bool:
    for c in ["板块前排", "是否板块前排", "人气前排"]:
        if c in row.index and _safe_str(row.get(c)).lower() in {"true", "1", "是", "yes"}:
            return True
    for c, lim in [("板块内涨幅排名", 3), ("板块内成交额排名", 5)]:
        v = row.get(c, pd.NA)
        if not _missing(v):
            try:
                if float(v) <= lim:
                    return True
            except Exception:
                pass
    return False


def classify_role(row: pd.Series, cfg: dict) -> str:
    total = row.get("总市值_亿", pd.NA)
    amount = row.get("成交额_亿", pd.NA)

    if _missing(total):
        return "市值未知"
    t = float(total)
    a = float(amount) if not _missing(amount) else 0.0

    if cfg["smallcap_total_min_yi"] <= t <= cfg["smallcap_total_max_yi"]:
        return "小市值高弹性"
    if t >= cfg["large_total_min_yi"]:
        return "大市值"
    if t >= cfg["medium_total_min_yi"] or a >= cfg["medium_amount_min_yi"]:
        return "中军参考"
    return "中等市值"


def calc_future_score(row: pd.Series, cfg: dict, emotion: dict) -> tuple[float, str]:
    # 若8502已经算过，先使用，再补充理由
    old = row.get("未来估值弹性分", pd.NA)
    if not _missing(old):
        reason = _safe_str(row.get("估值弹性原因", "8502已计算"))
        return float(old), reason

    score = 0.0
    reasons = []

    total = row.get("总市值_亿", pd.NA)
    if not _missing(total):
        t = float(total)
        if cfg["ideal_total_min_yi"] <= t <= cfg["ideal_total_max_yi"]:
            score += 30
            reasons.append(f"理想小市值{t:.1f}亿")
        elif cfg["smallcap_total_min_yi"] <= t <= cfg["smallcap_total_max_yi"]:
            score += 22
            reasons.append(f"小市值区间{t:.1f}亿")
        elif t >= cfg["large_total_min_yi"]:
            score += 2
            reasons.append(f"大市值{t:.1f}亿")
        else:
            score += 10
            reasons.append(f"中等市值{t:.1f}亿")
    else:
        score += 10
        reasons.append("市值缺失，暂用中性分")

    text = " ".join(_safe_str(row.get(c, "")) for c in ["最强概念", "所属概念", "所属行业", "新闻催化", "题材催化", "trigger_reason"] if c in row.index)
    hot_words = ["AI", "算力", "机器人", "低空", "半导体", "芯片", "固态", "并购", "重组", "订单", "政策", "数据中心"]
    hits = [w for w in hot_words if w.lower() in text.lower()]
    if hits:
        score += min(15, 5 + len(hits) * 3)
        reasons.append("题材关键词:" + "/".join(hits[:5]))

    if is_board_front(row):
        score += 12
        reasons.append("板块/人气前排")

    amount = row.get("成交额_亿", pd.NA)
    if not _missing(amount) and float(amount) >= 1:
        score += min(10, float(amount) / 3)
        reasons.append(f"成交活跃{float(amount):.1f}亿")

    speed_rank = row.get("全市场涨速排名", pd.NA)
    if not _missing(speed_rank) and float(speed_rank) <= 100:
        score += 8
        reasons.append(f"涨速排名{float(speed_rank):.0f}")

    stock_char = row.get("股性评分", pd.NA)
    if not _missing(stock_char) and float(stock_char) >= 60:
        score += 6
        reasons.append(f"股性评分{float(stock_char):.0f}")

    phase = _safe_str(emotion.get("emotion_phase", ""))
    if phase in {"强修复", "主升高热"}:
        score += 5
        reasons.append(f"情绪{phase}")

    return round(max(0, min(100, score)), 2), "；".join(reasons)


def build_medium_refs(df: pd.DataFrame, cfg: dict) -> dict[str, str]:
    if not cfg.get("medium_reference_enabled", True) or df.empty:
        return {}

    x = df.copy()
    x["_board_key"] = x.apply(board_key, axis=1)
    x["_total"] = pd.to_numeric(x.get("总市值_亿"), errors="coerce")
    x["_amount"] = pd.to_numeric(x.get("成交额_亿"), errors="coerce")

    ref = x[(x["_total"] >= cfg["medium_total_min_yi"]) | (x["_amount"] >= cfg["medium_amount_min_yi"]) | (x.get("市值角色", "") == "中军参考") | (x.get("市值角色", "") == "大市值")].copy()
    out = {}
    for board, g in ref.groupby("_board_key"):
        gg = g.sort_values(["_amount", "_total"], ascending=False).head(5)
        parts = []
        for _, r in gg.iterrows():
            parts.append(f"{r.get('名称','')}({r.get('代码','')},市值{fmt(r.get('总市值_亿'))}亿,额{fmt(r.get('成交额_亿'))}亿)")
        out[board] = "；".join(parts)
    return out


def fmt(x: Any, nd: int = 2) -> str:
    if _missing(x):
        return "-"
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return _safe_str(x)


def build_smallcap_pool(cfg: dict | None = None) -> tuple[pd.DataFrame, str]:
    cfg = cfg or load_config()
    raw = load_8502_snapshot()
    if raw.empty:
        return pd.DataFrame(), "没有找到8502快照文件。请先运行8502。"

    df = standardize(raw)
    if df.empty:
        return pd.DataFrame(), "8502快照标准化后为空。"

    emotion = load_emotion()

    roles, scores, reasons = [], [], []
    for _, row in df.iterrows():
        role = _safe_str(row.get("市值角色", "")) or classify_role(row, cfg)
        score, reason = calc_future_score(row, cfg, emotion)
        roles.append(role)
        scores.append(score)
        reasons.append(reason)

    df["市值角色"] = roles
    df["未来估值弹性分"] = scores
    df["估值弹性原因"] = reasons
    df["_board_key"] = df.apply(board_key, axis=1)

    refs = build_medium_refs(df, cfg)
    df["中军参考"] = df["_board_key"].map(refs).fillna("")

    # 8501复盘候选：优先小市值高弹性，其次大市值例外/中军参考
    role = df["市值角色"].astype(str)
    score = pd.to_numeric(df["未来估值弹性分"], errors="coerce")
    total = pd.to_numeric(df["总市值_亿"], errors="coerce")
    amount = pd.to_numeric(df["成交额_亿"], errors="coerce")

    is_small = (role == "小市值高弹性") & (score >= cfg["future_score_min"])
    is_large_exception = (role == "大市值") & (amount >= cfg["large_min_amount_yi"]) & df.apply(is_board_front, axis=1)
    is_medium_ref = role.isin(["中军参考", "大市值"]) & ((total >= cfg["medium_total_min_yi"]) | (amount >= cfg["medium_amount_min_yi"]))

    df["8501复盘定位"] = "观察"
    df.loc[is_small, "8501复盘定位"] = "明日重点小市值候选"
    df.loc[is_large_exception, "8501复盘定位"] = "大市值核心例外观察"
    df.loc[is_medium_ref & ~is_small & ~is_large_exception, "8501复盘定位"] = "中军参考"

    sort_key = df["8501复盘定位"].map({
        "明日重点小市值候选": 3,
        "大市值核心例外观察": 2,
        "中军参考": 1,
        "观察": 0,
    }).fillna(0)
    df["_sort"] = sort_key
    df = df.sort_values(["_sort", "未来估值弹性分", "涨跌幅"], ascending=[False, False, False], na_position="last").drop(columns=["_sort", "_board_key"], errors="ignore")

    top_n = int(cfg.get("top_n", 30))
    out = df.head(max(top_n, 1)).copy()
    out.to_csv(POOL_PATH, index=False, encoding="utf-8-sig")
    return out, f"已生成8501小市值复盘池：{len(out)}只。"


def table_text(df: pd.DataFrame, n: int = 20) -> str:
    if df.empty:
        return "暂无数据。"
    cols = [c for c in [
        "代码", "名称", "8501复盘定位", "市值角色", "未来估值弹性分", "总市值_亿", "流通市值_亿",
        "涨跌幅", "规则涨速", "成交额_亿", "换手率", "量比", "所属行业", "最强概念",
        "rule_name", "rule_type", "pattern_signal", "中军参考"
    ] if c in df.columns]
    return df[cols].head(n).to_string(index=False)


def build_local_review(df: pd.DataFrame, cfg: dict) -> str:
    emotion = load_emotion()
    small = df[df.get("8501复盘定位", "").astype(str).str.contains("小市值", na=False)] if not df.empty else pd.DataFrame()
    medium = df[df.get("8501复盘定位", "").astype(str).str.contains("中军", na=False)] if not df.empty else pd.DataFrame()
    large = df[df.get("8501复盘定位", "").astype(str).str.contains("大市值", na=False)] if not df.empty else pd.DataFrame()

    lines = []
    lines.append(f"# 8501 AI游资复盘：小市值高弹性视角 - {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"- 市场情绪：{emotion.get('emotion_phase','未知')} / {emotion.get('emotion_score','-')}")
    lines.append("- 策略偏好：优先小市值高弹性；中军用于确认板块强度；大市值只在强情绪、核心前排、放量时例外观察。")
    lines.append("")
    lines.append("## 明日重点小市值候选")
    lines.append("```text")
    lines.append(table_text(small, 15))
    lines.append("```")
    lines.append("")
    lines.append("## 中军参考")
    lines.append("```text")
    lines.append(table_text(medium, 10))
    lines.append("```")
    lines.append("")
    lines.append("## 大市值核心例外观察")
    lines.append("```text")
    lines.append(table_text(large, 10))
    lines.append("```")
    lines.append("")
    lines.append("## 复盘结论")
    lines.append("- 小市值候选只代表明日观察方向，不等于买入。")
    lines.append("- 若中军强、板块扩散、前排继续加强，则小市值补涨/首板/半路的胜率更高。")
    lines.append("- 若中军转弱、板块退潮或炸板扩散，小市值弹性也容易变成亏钱效应。")
    return "\n".join(lines)


def call_ai_review(df: pd.DataFrame, cfg: dict) -> tuple[bool, str]:
    load_env_files()
    key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY") or ""
    if not key:
        return False, "没有读取到API Key，已生成本地模板版。"

    emotion = load_emotion()
    prompt = f"""
你是一个短线游资复盘机器人。请基于8502盯盘结果，从“小市值高弹性优先、中军参考、大市值例外”的策略框架，生成8501盘后复盘。

策略框架：
1. 小市值高弹性公司优先：未来估值弹性、题材催化、板块前排、成交活跃。
2. 中军公司不作为主要买点，而是作为板块强度、资金锚点和方向确认。
3. 大市值公司只有在强修复/主升高热、核心前排、成交额充分、规则触发时才例外观察。
4. 输出只做复盘和明日观察计划，不自动下单。

市场情绪：
{json.dumps(emotion, ensure_ascii=False)}

候选池：
{table_text(df, int(cfg.get("top_n", 30)))}

请输出：
1. 今日小市值高弹性方向判断；
2. 哪些题材/行业有明日观察价值；
3. 中军是否支撑板块继续发酵；
4. 大市值是否有例外买入观察价值；
5. 明日小市值候选池分层：激进/稳健/只观察；
6. 风险条件：什么情况下不出手；
7. 结论：明天优先盯什么。
"""
    payload = {
        "model": cfg.get("ai_model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": cfg.get("style", DEFAULT_CONFIG["style"])},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(cfg.get("ai_temperature", 0.35)),
        "max_tokens": int(cfg.get("ai_max_tokens", 3600)),
    }
    try:
        r = requests.post(
            cfg.get("ai_base_url", "https://api.deepseek.com").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return False, f"大模型调用失败：{type(exc).__name__}: {exc}"


def generate_smallcap_review_8501(use_ai: bool = True, cfg: dict | None = None) -> tuple[bool, str, pd.DataFrame]:
    cfg = cfg or load_config()
    df, msg = build_smallcap_pool(cfg)
    if df.empty:
        text = f"# 8501小市值复盘\n\n{msg}"
        REVIEW_PATH.write_text(text, encoding="utf-8")
        return False, text, df

    if use_ai and cfg.get("ai_enabled", True):
        ok, ai_text = call_ai_review(df, cfg)
        if ok:
            text = ai_text
        else:
            text = build_local_review(df, cfg) + "\n\n---\n\n" + ai_text
    else:
        ok = True
        text = build_local_review(df, cfg)

    REVIEW_PATH.write_text(text, encoding="utf-8")
    return ok, text, df


def render_smallcap_review_8501_panel() -> None:
    import streamlit as st

    cfg = load_config()

    st.subheader("8501小市值高弹性复盘")
    st.caption("读取8502全天盯盘结果，按“小市值高弹性优先、中军参考、大市值例外”生成AI游资复盘和明日观察池。")

    with st.expander("小市值复盘设置", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["enabled"] = st.checkbox("启用8501小市值复盘", value=bool(cfg.get("enabled", True)), key="s8501_enabled")
            cfg["top_n"] = st.number_input("读取Top N", 5, 200, int(cfg.get("top_n", 30)), 1, key="s8501_topn")
        with c2:
            cfg["future_score_min"] = st.number_input("小市值弹性分阈值", 0.0, 100.0, float(cfg.get("future_score_min", 55.0)), 1.0, key="s8501_score")
            cfg["smallcap_total_min_yi"] = st.number_input("小市值下限 亿", 0.0, 10000.0, float(cfg.get("smallcap_total_min_yi", 15.0)), 1.0, key="s8501_smin")
            cfg["smallcap_total_max_yi"] = st.number_input("小市值上限 亿", 0.0, 10000.0, float(cfg.get("smallcap_total_max_yi", 220.0)), 1.0, key="s8501_smax")
        with c3:
            cfg["medium_total_min_yi"] = st.number_input("中军总市值≥亿", 0.0, 100000.0, float(cfg.get("medium_total_min_yi", 300.0)), 10.0, key="s8501_mmv")
            cfg["medium_amount_min_yi"] = st.number_input("中军成交额≥亿", 0.0, 10000.0, float(cfg.get("medium_amount_min_yi", 15.0)), 1.0, key="s8501_mamt")
            cfg["large_total_min_yi"] = st.number_input("大市值定义≥亿", 0.0, 100000.0, float(cfg.get("large_total_min_yi", 500.0)), 10.0, key="s8501_lmv")
            cfg["large_min_amount_yi"] = st.number_input("大市值例外成交额≥亿", 0.0, 10000.0, float(cfg.get("large_min_amount_yi", 20.0)), 1.0, key="s8501_lamt")

        cfg["ai_enabled"] = st.checkbox("生成AI复盘", value=bool(cfg.get("ai_enabled", True)), key="s8501_ai_enabled")
        cfg["ai_base_url"] = st.text_input("AI Base URL", value=str(cfg.get("ai_base_url", "https://api.deepseek.com")), key="s8501_ai_base")
        cfg["ai_model"] = st.text_input("AI模型", value=str(cfg.get("ai_model", "deepseek-chat")), key="s8501_ai_model")
        cfg["style"] = st.text_area("AI复盘风格", value=str(cfg.get("style", DEFAULT_CONFIG["style"])), height=90, key="s8501_style")

        if st.button("保存小市值复盘设置", key="s8501_save"):
            save_config(cfg)
            st.success("已保存 config/smallcap_review_8501_v8_2_2.json")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("生成小市值复盘池", key="s8501_pool"):
            save_config(cfg)
            df, msg = build_smallcap_pool(cfg)
            st.session_state["s8501_msg"] = msg
            st.success(msg)
    with c2:
        if st.button("生成AI小市值复盘", type="primary", key="s8501_review"):
            save_config(cfg)
            with st.spinner("正在生成8501小市值AI复盘..."):
                ok, text, df = generate_smallcap_review_8501(use_ai=True, cfg=cfg)
            st.session_state["s8501_review_text"] = text
            st.success("AI复盘已生成。" if ok else "已生成本地模板/降级复盘。")
    with c3:
        if REVIEW_PATH.exists():
            st.download_button("下载复盘报告", REVIEW_PATH.read_text(encoding="utf-8"), "ai_youzhi_smallcap_review_8501_v8_2_2.md", "text/markdown", key="s8501_download")

    df = read_csv_safe(POOL_PATH)
    if df.empty:
        df, msg = build_smallcap_pool(cfg)

    if not df.empty:
        show_cols = [c for c in [
            "代码", "名称", "8501复盘定位", "市值角色", "未来估值弹性分", "总市值_亿", "流通市值_亿",
            "涨跌幅", "规则涨速", "成交额_亿", "换手率", "量比", "所属行业", "最强概念",
            "rule_name", "rule_type", "pattern_signal", "中军参考", "估值弹性原因"
        ] if c in df.columns]
        st.dataframe(df[show_cols], hide_index=True, use_container_width=True, height=380)

    text = st.session_state.get("s8501_review_text")
    if not text and REVIEW_PATH.exists():
        text = REVIEW_PATH.read_text(encoding="utf-8")
    if text:
        st.markdown(text)
