# -*- coding: utf-8 -*-
"""
kobe_rule_attribution_v8_2_1.py

v8.2.1：92科比模式化自定义规则归因版

这版替代旧的横向“自定义交易规则”页面，改成 5 个折叠区：

一、市场模式：龙头 / 补涨 / 切换 / 空仓
二、半路买点：涨幅、涨速、成交额、板块联动、人气排名、量能
三、打板细分：扫板 / 排板 / 回封
四、题材与人气：新闻催化、题材阶段、板块前排、辨识度、股性
五、风险与卖点：中位股、炸板、退潮、成交额异常、弱转强失败

核心输出字段：
- rule_name
- rule_type
- rule_version
- rule_params
- signal_source
- trigger_reason

输出：
- reports/latest_watch_signals_kobe_v8_2_1.csv
- reports/watch_signal_events_kobe_v8_2_1.csv
- reports/signal_effect_stats_by_rule_kobe_v8_2_1.csv
- reports/signal_effect_stats_by_rule_type_kobe_v8_2_1.csv
- reports/kobe_rule_param_suggestions_v8_2_1.md
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "reports"
CONFIG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

CONFIG_PATH = CONFIG_DIR / "kobe_rule_attribution_v8_2_1.json"

SNAPSHOT_PATH = REPORT_DIR / "latest_watch_signals_kobe_v8_2_1.csv"
ATTR_EVENT_PATH = REPORT_DIR / "watch_signal_events_kobe_v8_2_1.csv"
RULE_STATS_PATH = REPORT_DIR / "signal_effect_stats_by_rule_kobe_v8_2_1.csv"
RULE_TYPE_STATS_PATH = REPORT_DIR / "signal_effect_stats_by_rule_type_kobe_v8_2_1.csv"
SUGGEST_PATH = REPORT_DIR / "kobe_rule_param_suggestions_v8_2_1.md"

EVENT_LOG_PATH = REPORT_DIR / "watch_signal_events.csv"

DEFAULT_CONFIG = {
    "enabled": True,
    "rule_version": "v8.2.1-kobe",

    # 一、市场模式
    "market_mode": "自动判断",
    "index_condition": "自动/未知",
    "emotion_auto": True,
    "allow_trade_in_cold": False,
    "prefer_leader_when_strong": True,
    "prefer_first_board_when_index_weak": True,

    # 二、半路买点
    "half_enabled": True,
    "half_rule_name": "半路买点-主线前排量能确认",
    "half_rule_type": "半路",
    "half_min_pct": 3.0,
    "half_max_pct": 8.0,
    "half_min_speed": 0.50,
    "half_min_amount_yi": 0.50,
    "half_min_board_strong_count": 3,
    "half_min_board_limit_count": 0,
    "half_min_turnover": 3.0,
    "half_max_turnover": 30.0,
    "half_min_volume_ratio": 1.0,
    "half_min_volume_wan_shou": 5.0,
    "half_min_volume_vs_yesterday": 0.25,

    # 三、打板细分
    "sweep_enabled": True,
    "sweep_rule_name": "扫板-强情绪前排确认",
    "sweep_rule_type": "扫板",
    "sweep_min_pct": 9.3,
    "sweep_min_speed": 0.30,
    "sweep_min_amount_yi": 0.50,
    "sweep_min_board_limit_count": 1,
    "sweep_block_cold_phase": True,

    "queue_enabled": True,
    "queue_rule_name": "排板-封单观察",
    "queue_rule_type": "排板",
    "queue_min_pct": 9.7,
    "queue_allow_observe_cancel": True,
    "queue_require_seal_fund": False,
    "queue_min_seal_fund_wan": 1000.0,

    "reseal_enabled": True,
    "reseal_rule_name": "回封-承接确认",
    "reseal_rule_type": "回封",
    "reseal_max_open_count": 2,
    "reseal_latest_time": "14:30",
    "reseal_max_amount_expansion": 3.0,
    "reseal_min_seal_fund_wan": 800.0,

    "board_min_turnover": 5.0,
    "board_max_turnover": 45.0,
    "board_min_volume_ratio": 1.2,
    "board_min_volume_wan_shou": 8.0,
    "board_min_volume_vs_yesterday": 0.35,

    # 四、题材与人气
    "theme_enabled": True,
    "require_news_catalyst": False,
    "require_main_theme": False,
    "require_first_ferment_or_divergence_to_consensus": False,
    "exclude_retired_theme": True,
    "theme_fresh_days": 3,
    "news_strength": "不限",
    "theme_stage": "不限",

    "popularity_enabled": True,
    "require_board_front": False,
    "industry_pct_rank_max": 3,
    "industry_amount_rank_max": 5,
    "global_speed_rank_max": 100,
    "recent_limit_days": 20,
    "min_recent_limit_count": 0,
    "max_recent_bomb_count": 2,
    "require_good_stock_character": False,

    # 五、风险与卖点
    "middle_filter_enabled": True,
    "avoid_middle_position": True,
    "low_chain_max": 1,
    "low_pct_max": 5.0,
    "high_chain_min": 3,
    "high_is_board_front": True,

    "risk_enabled": True,
    "risk_rule_name": "风控-退潮/中位/量能异常",
    "risk_rule_type": "风控",
    "risk_min_pct": -3.0,
    "risk_min_speed": -1.0,
    "risk_max_turnover": 55.0,
    "risk_max_volume_vs_yesterday": 3.5,
    "risk_low_volume_ratio": 0.5,
    "risk_block_emotion_phases": ["冰点", "退潮"],
    "risk_weak_to_strong_fail": True,

    # 缺失字段策略
    "allow_missing_news": True,
    "allow_missing_popularity": True,
    "allow_missing_volume": True,
    "allow_missing_stock_character": True,
}


# -------------------------
# 基础IO
# -------------------------

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


# -------------------------
# 数据标准化
# -------------------------

def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\n", " ").replace("\r", " ").strip()


def _norm_code(x: Any) -> str:
    d = "".join(re.findall(r"\d", str(x)))
    return d[-6:].zfill(6) if d else ""


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
        val = float(m.group(0))
    except Exception:
        return default

    if "亿" in s:
        return val * 10000.0
    if "万" in s:
        return val
    return val


def parse_amount_yi(x: Any) -> float:
    if x is None:
        return float("nan")
    try:
        if pd.isna(x):
            return float("nan")
    except Exception:
        pass
    if isinstance(x, (int, float)):
        # 若原始巨大，按元转亿；若已经很小，认为是亿
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


def parse_volume_wan_shou(x: Any) -> float:
    if x is None:
        return float("nan")
    try:
        if pd.isna(x):
            return float("nan")
    except Exception:
        pass
    if isinstance(x, (int, float)):
        return float(x) / 10000.0

    s = str(x).strip().replace(",", "")
    if not s or s in {"-", "--", "None", "nan", "NaN"}:
        return float("nan")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return float("nan")
    val = float(m.group(0))

    if "亿手" in s:
        return val * 10000
    if "万手" in s:
        return val
    if "手" in s:
        return val / 10000.0

    if "亿股" in s:
        return val * 10000 / 100
    if "万股" in s:
        return val / 100
    if "股" in s:
        return val / 100 / 10000

    return val / 10000.0


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


def standardize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
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

    pct_col = find_col(x, ["涨跌幅", "涨幅", "pct_chg"])
    speed_col = find_col(x, ["规则涨速", "5分钟涨速", "涨速", "speed"])
    amount_col = find_col(x, ["成交额_亿", "成交额", "amount"])
    turnover_col = find_col(x, ["换手率", "换手", "turnover", "turnover_rate"])
    vr_col = find_col(x, ["量比", "volume_ratio", "vol_ratio"])
    vol_col = find_col(x, ["成交量", "成交量_手", "volume", "vol"])
    yvol_col = find_col(x, ["昨日成交量", "昨成交量", "昨日量", "昨量", "pre_volume", "yesterday_volume"])
    chain_col = find_col(x, ["连板数", "连续涨停", "连板高度", "height"])
    board_strong_col = find_col(x, ["板块强势股数量", "行业强势数", "概念强势数", "强势股数"])
    board_limit_col = find_col(x, ["板块涨停数", "行业涨停数", "概念涨停数", "涨停数"])

    x["涨跌幅"] = x[pct_col].map(_to_float) if pct_col else pd.NA
    x["规则涨速"] = x[speed_col].map(_to_float) if speed_col else pd.NA
    x["成交额_亿"] = x[amount_col].map(parse_amount_yi) if amount_col else pd.NA
    x["换手率"] = x[turnover_col].map(_to_float) if turnover_col else pd.NA
    x["量比"] = x[vr_col].map(_to_float) if vr_col else pd.NA
    x["成交量_万手"] = x[vol_col].map(parse_volume_wan_shou) if vol_col else pd.NA
    x["昨日成交量_万手"] = x[yvol_col].map(parse_volume_wan_shou) if yvol_col else pd.NA

    cur = pd.to_numeric(x["成交量_万手"], errors="coerce")
    pre = pd.to_numeric(x["昨日成交量_万手"], errors="coerce")
    x["成交量较昨日倍数"] = cur / pre.replace(0, pd.NA)

    x["连板数"] = x[chain_col].map(_to_float) if chain_col else pd.NA
    x["板块强势股数量"] = x[board_strong_col].map(_to_float) if board_strong_col else pd.NA
    x["板块涨停数"] = x[board_limit_col].map(_to_float) if board_limit_col else pd.NA

    # 常见字段兜底
    for c in ["个股板块联动分", "封单资金", "封板资金", "炸板次数", "近20日涨停次数", "近20日炸板次数", "股性评分"]:
        if c in x.columns:
            x[c] = x[c].map(_to_float)

    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    return x


def find_watch_df_from_globals(globs: dict) -> pd.DataFrame:
    preferred = [
        "signal_df", "watch_df", "df", "main", "main_df", "data", "rank_df", "pool",
        "today_pool", "limit_pool",
    ]

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
        return candidates[0][2].copy()

    for p in [
        REPORT_DIR / "latest_watch_states_v7_9.csv",
        REPORT_DIR / "latest_watch_signals.csv",
        REPORT_DIR / "latest_watch_signals_rule_attribution_v8_2_1.csv",
        REPORT_DIR / "realtime_last_snapshot.csv",
    ]:
        df = read_csv_safe(p)
        if not df.empty:
            return df

    return pd.DataFrame()


# -------------------------
# 排名/辅助字段
# -------------------------

def add_popularity_ranks(x: pd.DataFrame) -> pd.DataFrame:
    if x.empty:
        return x

    out = x.copy()

    if "所属行业" in out.columns and "涨跌幅" in out.columns:
        out["板块内涨幅排名"] = out.groupby("所属行业")["涨跌幅"].rank(ascending=False, method="min")
    elif "最强概念" in out.columns and "涨跌幅" in out.columns:
        out["板块内涨幅排名"] = out.groupby("最强概念")["涨跌幅"].rank(ascending=False, method="min")
    else:
        out["板块内涨幅排名"] = pd.NA

    if "所属行业" in out.columns and "成交额_亿" in out.columns:
        out["板块内成交额排名"] = out.groupby("所属行业")["成交额_亿"].rank(ascending=False, method="min")
    elif "最强概念" in out.columns and "成交额_亿" in out.columns:
        out["板块内成交额排名"] = out.groupby("最强概念")["成交额_亿"].rank(ascending=False, method="min")
    else:
        out["板块内成交额排名"] = pd.NA

    if "规则涨速" in out.columns:
        out["全市场涨速排名"] = out["规则涨速"].rank(ascending=False, method="min")
    else:
        out["全市场涨速排名"] = pd.NA

    return out


def _missing(v: Any) -> bool:
    try:
        return pd.isna(v)
    except Exception:
        return v is None


def check_range(value: Any, lo: float | None = None, hi: float | None = None, allow_missing: bool = True) -> tuple[bool, str]:
    if _missing(value):
        return allow_missing, "缺失"
    v = float(value)
    if lo is not None and v < lo:
        return False, f"{v:.2f} < {lo:.2f}"
    if hi is not None and v > hi:
        return False, f"{v:.2f} > {hi:.2f}"
    return True, f"{v:.2f}"


def check_ge(value: Any, lo: float, allow_missing: bool = True) -> tuple[bool, str]:
    return check_range(value, lo=lo, hi=None, allow_missing=allow_missing)


# -------------------------
# 五大模块评分/过滤
# -------------------------

def infer_market_mode(cfg: dict, emotion: dict) -> tuple[str, bool, str]:
    mode = cfg.get("market_mode", "自动判断")
    phase = _safe_str(emotion.get("emotion_phase", "未知"))
    score = _to_float(emotion.get("emotion_score", float("nan")))
    index_cond = cfg.get("index_condition", "自动/未知")

    if mode != "自动判断":
        if mode == "空仓/防守模式":
            return mode, bool(cfg.get("allow_trade_in_cold", False)), "手动选择空仓/防守模式"
        return mode, True, f"手动选择{mode}"

    # 自动判断：情绪好/差 + 指数好/弱
    good_emotion = phase in {"主升高热", "强修复", "混沌偏强"} or (not _missing(score) and score >= 55)
    bad_emotion = phase in {"冰点", "退潮"} or (not _missing(score) and score < 35)
    index_good = index_cond == "指数好"
    index_weak = index_cond == "指数弱"

    if good_emotion and index_good:
        return "龙头模式", True, "情绪好+指数好：优先龙头/人气核心"
    if good_emotion and index_weak:
        return "补涨模式", True, "情绪好+指数弱：优先低位首板/补涨"
    if bad_emotion and index_good:
        return "切换模式", True, "情绪差+指数好：尝试切换"
    if bad_emotion and index_weak:
        return "空仓/防守模式", bool(cfg.get("allow_trade_in_cold", False)), "情绪差+指数差：空仓/只观察"

    if phase in {"主升高热", "强修复"}:
        return "龙头模式", True, f"情绪阶段{phase}：偏龙头/人气核心"
    if phase in {"退潮", "冰点"}:
        return "空仓/防守模式", bool(cfg.get("allow_trade_in_cold", False)), f"情绪阶段{phase}：防守"
    return "混合模式", True, "情绪中性或未知：混合模式"


def check_middle_filter(row: pd.Series, cfg: dict) -> tuple[bool, str, str]:
    if not cfg.get("middle_filter_enabled", True) or not cfg.get("avoid_middle_position", True):
        return True, "未启用中位股过滤", "未分类"

    pct = row.get("涨跌幅", pd.NA)
    chain = row.get("连板数", pd.NA)
    pct = _to_float(pct)
    chain = _to_float(chain)

    board_front = False
    for c in ["板块前排", "是否板块前排", "人气前排"]:
        if c in row.index:
            board_front = str(row.get(c)).lower() in {"true", "1", "是", "yes", "y"}
    rank = row.get("板块内涨幅排名", pd.NA)
    if not _missing(rank) and float(rank) <= float(cfg.get("industry_pct_rank_max", 3)):
        board_front = True

    low = (not _missing(chain) and chain <= cfg.get("low_chain_max", 1)) or (not _missing(pct) and pct <= cfg.get("low_pct_max", 5.0))
    high = (not _missing(chain) and chain >= cfg.get("high_chain_min", 3)) or (cfg.get("high_is_board_front", True) and board_front)

    if low:
        return True, "低位定义通过：首板/1进2/低涨幅", "低位"
    if high:
        return True, "高位定义通过：空间龙头/板块核心/连板高度", "高位"

    return False, "中位股过滤：非龙头、非首板、非补涨前排", "中位"


def check_theme(row: pd.Series, cfg: dict) -> tuple[bool, str]:
    if not cfg.get("theme_enabled", True):
        return True, "题材过滤未启用"

    reasons = []
    allow_missing = bool(cfg.get("allow_missing_news", True))

    text = " ".join(_safe_str(row.get(c, "")) for c in [
        "新闻催化", "题材催化", "当日新闻", "新闻", "公告", "题材阶段", "最强概念", "所属概念"
    ] if c in row.index)

    has_news = bool(text.strip()) and not any(x in text for x in ["无", "暂无", "None", "nan"])
    if cfg.get("require_news_catalyst", False):
        if not has_news:
            return allow_missing, "要求当日新闻催化，但字段缺失/无新闻"
        reasons.append("有新闻/公告/题材文本")

    if cfg.get("require_main_theme", False):
        is_main = False
        for c in ["是否主线", "主线题材", "属于主线", "主线"]:
            if c in row.index and str(row.get(c)).lower() in {"true", "1", "是", "yes", "y"}:
                is_main = True
        if not is_main and "主线" not in text:
            return allow_missing, "要求当前主线题材，但缺少主线字段"
        reasons.append("主线题材通过")

    if cfg.get("exclude_retired_theme", True):
        if any(k in text for k in ["退潮", "淘汰", "过气", "兑现"]):
            return False, "题材退潮/淘汰"

    stage = cfg.get("theme_stage", "不限")
    if stage != "不限" and stage not in text:
        # 没有字段时不强杀，除非不允许缺失
        return allow_missing, f"要求题材阶段{stage}，但字段缺失/不匹配"

    return True, "题材通过：" + ("；".join(reasons) if reasons else "未强制要求新闻/主线")


def check_popularity(row: pd.Series, cfg: dict) -> tuple[bool, str]:
    if not cfg.get("popularity_enabled", True):
        return True, "人气过滤未启用"

    allow_missing = bool(cfg.get("allow_missing_popularity", True))
    reasons = []

    if cfg.get("require_board_front", False):
        ok1, msg1 = check_range(row.get("板块内涨幅排名", pd.NA), hi=float(cfg.get("industry_pct_rank_max", 3)), allow_missing=allow_missing)
        ok2, msg2 = check_range(row.get("板块内成交额排名", pd.NA), hi=float(cfg.get("industry_amount_rank_max", 5)), allow_missing=allow_missing)
        if not (ok1 or ok2):
            return False, f"板块前排不满足：涨幅排名{msg1}，成交额排名{msg2}"
        reasons.append(f"板块前排：涨幅排名{msg1}，成交额排名{msg2}")

    ok, msg = check_range(row.get("全市场涨速排名", pd.NA), hi=float(cfg.get("global_speed_rank_max", 100)), allow_missing=allow_missing)
    if not ok:
        return False, f"全市场涨速排名不满足：{msg}"
    reasons.append(f"涨速排名{msg}")

    recent_limit = row.get("近20日涨停次数", row.get("近N日涨停次数", pd.NA))
    ok, msg = check_ge(recent_limit, float(cfg.get("min_recent_limit_count", 0)), allow_missing=allow_missing)
    if not ok:
        return False, f"近期涨停记忆不足：{msg}"
    reasons.append(f"近期涨停记忆{msg}")

    recent_bomb = row.get("近20日炸板次数", row.get("近N日炸板次数", pd.NA))
    ok, msg = check_range(recent_bomb, hi=float(cfg.get("max_recent_bomb_count", 2)), allow_missing=allow_missing)
    if not ok:
        return False, f"近期炸板次数过多：{msg}"
    reasons.append(f"炸板次数{msg}")

    if cfg.get("require_good_stock_character", False):
        score = row.get("股性评分", pd.NA)
        ok, msg = check_ge(score, 60.0, allow_missing=bool(cfg.get("allow_missing_stock_character", True)))
        if not ok:
            return False, f"股性评分不足：{msg}"
        reasons.append(f"股性评分{msg}")

    return True, "人气通过：" + "；".join(reasons)


def check_volume(row: pd.Series, cfg: dict, bucket: str) -> tuple[bool, str]:
    allow = bool(cfg.get("allow_missing_volume", True))

    turnover = row.get("换手率", pd.NA)
    vr = row.get("量比", pd.NA)
    vol = row.get("成交量_万手", pd.NA)
    vy = row.get("成交量较昨日倍数", pd.NA)

    checks = []
    if bucket == "half":
        checks.append(("换手率", *check_range(turnover, cfg["half_min_turnover"], cfg["half_max_turnover"], allow)))
        checks.append(("量比", *check_ge(vr, cfg["half_min_volume_ratio"], allow)))
        checks.append(("成交量", *check_ge(vol, cfg["half_min_volume_wan_shou"], allow)))
        checks.append(("今日/昨日量", *check_ge(vy, cfg["half_min_volume_vs_yesterday"], allow)))
    elif bucket in {"sweep", "queue", "reseal"}:
        checks.append(("换手率", *check_range(turnover, cfg["board_min_turnover"], cfg["board_max_turnover"], allow)))
        checks.append(("量比", *check_ge(vr, cfg["board_min_volume_ratio"], allow)))
        checks.append(("成交量", *check_ge(vol, cfg["board_min_volume_wan_shou"], allow)))
        checks.append(("今日/昨日量", *check_ge(vy, cfg["board_min_volume_vs_yesterday"], allow)))
    else:
        flags = []
        if not _missing(turnover) and float(turnover) >= float(cfg["risk_max_turnover"]):
            flags.append(f"换手过高{float(turnover):.2f}%")
        if not _missing(vy) and float(vy) >= float(cfg["risk_max_volume_vs_yesterday"]):
            flags.append(f"今日/昨日量过高{float(vy):.2f}")
        if not _missing(vr) and float(vr) <= float(cfg["risk_low_volume_ratio"]):
            flags.append(f"量比过低{float(vr):.2f}")
        if flags:
            return True, "量能风险：" + "；".join(flags)
        return False, "未触发量能风险"

    passed = all(ok for _, ok, _ in checks)
    text = "；".join(f"{name}:{msg}" for name, ok, msg in checks)
    return passed, ("量能通过：" if passed else "量能不足：") + text


def check_half(row: pd.Series, cfg: dict) -> tuple[bool, str]:
    if not cfg.get("half_enabled", True):
        return False, "半路规则未启用"

    pct_ok, pct_msg = check_range(row.get("涨跌幅", pd.NA), cfg["half_min_pct"], cfg["half_max_pct"], False)
    speed_ok, speed_msg = check_ge(row.get("规则涨速", pd.NA), cfg["half_min_speed"], True)
    amount_ok, amount_msg = check_ge(row.get("成交额_亿", pd.NA), cfg["half_min_amount_yi"], True)
    strong_ok, strong_msg = check_ge(row.get("板块强势股数量", pd.NA), cfg["half_min_board_strong_count"], True)
    limit_ok, limit_msg = check_ge(row.get("板块涨停数", pd.NA), cfg["half_min_board_limit_count"], True)
    volume_ok, volume_msg = check_volume(row, cfg, "half")

    checks = [pct_ok, speed_ok, amount_ok, strong_ok, limit_ok, volume_ok]
    reason = f"涨幅{pct_msg}；涨速{speed_msg}；成交额{amount_msg}；板块强势{strong_msg}；板块涨停{limit_msg}；{volume_msg}"
    return all(checks), reason


def check_sweep(row: pd.Series, cfg: dict, emotion: dict) -> tuple[bool, str]:
    if not cfg.get("sweep_enabled", True):
        return False, "扫板规则未启用"

    phase = _safe_str(emotion.get("emotion_phase", "未知"))
    if cfg.get("sweep_block_cold_phase", True) and phase in {"冰点", "退潮"}:
        return False, f"情绪阶段{phase}，禁止扫板"

    pct_ok, pct_msg = check_ge(row.get("涨跌幅", pd.NA), cfg["sweep_min_pct"], False)
    speed_ok, speed_msg = check_ge(row.get("规则涨速", pd.NA), cfg["sweep_min_speed"], True)
    amount_ok, amount_msg = check_ge(row.get("成交额_亿", pd.NA), cfg["sweep_min_amount_yi"], True)
    board_ok, board_msg = check_ge(row.get("板块涨停数", pd.NA), cfg["sweep_min_board_limit_count"], True)
    volume_ok, volume_msg = check_volume(row, cfg, "sweep")

    checks = [pct_ok, speed_ok, amount_ok, board_ok, volume_ok]
    reason = f"扫板：涨幅{pct_msg}；涨速{speed_msg}；成交额{amount_msg}；板块涨停{board_msg}；{volume_msg}"
    return all(checks), reason


def check_queue(row: pd.Series, cfg: dict) -> tuple[bool, str]:
    if not cfg.get("queue_enabled", True):
        return False, "排板规则未启用"

    pct_ok, pct_msg = check_ge(row.get("涨跌幅", pd.NA), cfg["queue_min_pct"], False)
    seal_fund = row.get("封单资金", row.get("封板资金", pd.NA))

    if cfg.get("queue_require_seal_fund", False):
        seal_ok, seal_msg = check_ge(seal_fund, cfg["queue_min_seal_fund_wan"], True)
    else:
        seal_ok, seal_msg = True, "未强制"

    volume_ok, volume_msg = check_volume(row, cfg, "queue")
    checks = [pct_ok, seal_ok, volume_ok]

    reason = f"排板：涨幅{pct_msg}；封单资金{seal_msg}；允许撤单观察{cfg.get('queue_allow_observe_cancel', True)}；{volume_msg}"
    return all(checks), reason


def check_reseal(row: pd.Series, cfg: dict) -> tuple[bool, str]:
    if not cfg.get("reseal_enabled", True):
        return False, "回封规则未启用"

    open_count = row.get("炸板次数", row.get("开板次数", pd.NA))
    seal_fund = row.get("封单资金", row.get("封板资金", pd.NA))

    open_ok, open_msg = check_range(open_count, hi=cfg["reseal_max_open_count"], allow_missing=True)
    seal_ok, seal_msg = check_ge(seal_fund, cfg["reseal_min_seal_fund_wan"], True)
    volume_ok, volume_msg = check_volume(row, cfg, "reseal")

    text = " ".join(_safe_str(row.get(c, "")) for c in ["买卖状态", "标准状态", "操作提示", "实时信号"] if c in row.index)
    has_reseal_text = ("回封" in text) or ("封板" in text and "炸" in text)
    text_ok = has_reseal_text or True  # 缺少明确回封字段时不强杀，由涨幅/封单/量能判断

    checks = [open_ok, seal_ok, volume_ok, text_ok]
    reason = f"回封：炸板次数{open_msg}；封单资金{seal_msg}；最晚回封时间{cfg.get('reseal_latest_time')}；{volume_msg}"
    return all(checks), reason


def check_risk(row: pd.Series, cfg: dict, emotion: dict, middle_ok: bool, middle_type: str) -> tuple[bool, str]:
    if not cfg.get("risk_enabled", True):
        return False, "风控未启用"

    reasons = []
    phase = _safe_str(emotion.get("emotion_phase", "未知"))

    if phase in set(cfg.get("risk_block_emotion_phases", ["冰点", "退潮"])):
        reasons.append(f"情绪{phase}")

    pct = _to_float(row.get("涨跌幅", pd.NA))
    speed = _to_float(row.get("规则涨速", pd.NA))
    if not _missing(pct) and pct <= float(cfg["risk_min_pct"]):
        reasons.append(f"涨幅弱{pct:.2f}%")
    if not _missing(speed) and speed <= float(cfg["risk_min_speed"]):
        reasons.append(f"涨速弱{speed:.2f}%")

    if cfg.get("avoid_middle_position", True) and middle_type == "中位":
        reasons.append("中位股风险")

    volume_risk, volume_msg = check_volume(row, cfg, "risk")
    if volume_risk:
        reasons.append(volume_msg)

    text = " ".join(_safe_str(row.get(c, "")) for c in ["买卖状态", "标准状态", "操作提示", "实时信号", "状态原因"] if c in row.index)
    if any(k in text for k in ["炸板", "失效", "风险", "回避", "卖出", "弱转强失败"]):
        reasons.append("状态文本风险")

    if reasons:
        return True, "；".join(reasons)
    return False, "未触发风险"


def build_rule_params(cfg: dict, bucket: str) -> str:
    if bucket == "half":
        keys = [
            "market_mode", "index_condition", "half_min_pct", "half_max_pct", "half_min_speed",
            "half_min_amount_yi", "half_min_board_strong_count", "half_min_board_limit_count",
            "half_min_turnover", "half_max_turnover", "half_min_volume_ratio", "half_min_volume_wan_shou",
            "half_min_volume_vs_yesterday", "require_board_front", "require_news_catalyst",
        ]
    elif bucket == "sweep":
        keys = [
            "market_mode", "sweep_min_pct", "sweep_min_speed", "sweep_min_amount_yi",
            "sweep_min_board_limit_count", "sweep_block_cold_phase", "board_min_turnover",
            "board_max_turnover", "board_min_volume_ratio", "board_min_volume_wan_shou",
            "board_min_volume_vs_yesterday",
        ]
    elif bucket == "queue":
        keys = [
            "market_mode", "queue_min_pct", "queue_allow_observe_cancel", "queue_require_seal_fund",
            "queue_min_seal_fund_wan", "board_min_turnover", "board_max_turnover",
            "board_min_volume_ratio", "board_min_volume_wan_shou", "board_min_volume_vs_yesterday",
        ]
    elif bucket == "reseal":
        keys = [
            "market_mode", "reseal_max_open_count", "reseal_latest_time", "reseal_max_amount_expansion",
            "reseal_min_seal_fund_wan", "board_min_turnover", "board_max_turnover",
            "board_min_volume_ratio", "board_min_volume_wan_shou", "board_min_volume_vs_yesterday",
        ]
    else:
        keys = [
            "market_mode", "risk_min_pct", "risk_min_speed", "risk_max_turnover",
            "risk_max_volume_vs_yesterday", "risk_low_volume_ratio", "risk_block_emotion_phases",
            "avoid_middle_position",
        ]
    return json.dumps({k: cfg.get(k) for k in keys}, ensure_ascii=False)


def assign_rule(row: pd.Series, cfg: dict, emotion: dict) -> dict:
    mode, mode_ok, mode_reason = infer_market_mode(cfg, emotion)
    middle_ok, middle_reason, middle_type = check_middle_filter(row, cfg)
    theme_ok, theme_reason = check_theme(row, cfg)
    pop_ok, pop_reason = check_popularity(row, cfg)
    risk_hit, risk_reason = check_risk(row, cfg, emotion, middle_ok, middle_type)

    # 先风控
    if risk_hit:
        return {
            "market_mode_effective": mode,
            "market_mode_pass": mode_ok,
            "market_mode_reason": mode_reason,
            "middle_position_type": middle_type,
            "middle_filter_pass": middle_ok,
            "middle_filter_reason": middle_reason,
            "theme_pass": theme_ok,
            "theme_reason": theme_reason,
            "popularity_pass": pop_ok,
            "popularity_reason": pop_reason,
            "pattern_signal": "风险",
            "pattern_pass": True,
            "pattern_reason": risk_reason,
            "rule_name": cfg.get("risk_rule_name", "风控-退潮/中位/量能异常"),
            "rule_type": cfg.get("risk_rule_type", "风控"),
            "rule_version": cfg.get("rule_version", "v8.2.1-kobe"),
            "rule_params": build_rule_params(cfg, "risk"),
            "signal_source": "92科比模式过滤+自定义规则",
            "trigger_reason": f"{mode_reason}；{middle_reason}；{theme_reason}；{pop_reason}；{risk_reason}",
            "rule_pass": True,
            "trade_allowed": False,
        }

    if not mode_ok:
        return {
            "market_mode_effective": mode,
            "market_mode_pass": mode_ok,
            "market_mode_reason": mode_reason,
            "middle_position_type": middle_type,
            "middle_filter_pass": middle_ok,
            "middle_filter_reason": middle_reason,
            "theme_pass": theme_ok,
            "theme_reason": theme_reason,
            "popularity_pass": pop_ok,
            "popularity_reason": pop_reason,
            "pattern_signal": "空仓/只观察",
            "pattern_pass": False,
            "pattern_reason": "市场模式不允许出手",
            "rule_name": "空仓/防守模式过滤",
            "rule_type": "风控",
            "rule_version": cfg.get("rule_version", "v8.2.1-kobe"),
            "rule_params": build_rule_params(cfg, "risk"),
            "signal_source": "92科比模式过滤+自定义规则",
            "trigger_reason": mode_reason,
            "rule_pass": False,
            "trade_allowed": False,
        }

    # 中位股不允许通过
    if cfg.get("avoid_middle_position", True) and not middle_ok:
        return {
            "market_mode_effective": mode,
            "market_mode_pass": mode_ok,
            "market_mode_reason": mode_reason,
            "middle_position_type": middle_type,
            "middle_filter_pass": middle_ok,
            "middle_filter_reason": middle_reason,
            "theme_pass": theme_ok,
            "theme_reason": theme_reason,
            "popularity_pass": pop_ok,
            "popularity_reason": pop_reason,
            "pattern_signal": "中位股过滤",
            "pattern_pass": False,
            "pattern_reason": middle_reason,
            "rule_name": "中位股过滤",
            "rule_type": "风控",
            "rule_version": cfg.get("rule_version", "v8.2.1-kobe"),
            "rule_params": build_rule_params(cfg, "risk"),
            "signal_source": "92科比模式过滤+自定义规则",
            "trigger_reason": f"{mode_reason}；{middle_reason}",
            "rule_pass": False,
            "trade_allowed": False,
        }

    # 题材/人气基础过滤
    base_ok = theme_ok and pop_ok
    base_reason = f"{mode_reason}；{middle_reason}；{theme_reason}；{pop_reason}"

    # 打板细分优先级：回封 > 扫板 > 排板 > 半路
    reseal_ok, reseal_reason = check_reseal(row, cfg)
    sweep_ok, sweep_reason = check_sweep(row, cfg, emotion)
    queue_ok, queue_reason = check_queue(row, cfg)
    half_ok, half_reason = check_half(row, cfg)

    if base_ok and reseal_ok:
        bucket = "reseal"
        rule_name, rule_type = cfg["reseal_rule_name"], cfg["reseal_rule_type"]
        pattern, pattern_reason = "回封确认", reseal_reason
    elif base_ok and sweep_ok:
        bucket = "sweep"
        rule_name, rule_type = cfg["sweep_rule_name"], cfg["sweep_rule_type"]
        pattern, pattern_reason = "扫板触发", sweep_reason
    elif base_ok and queue_ok:
        bucket = "queue"
        rule_name, rule_type = cfg["queue_rule_name"], cfg["queue_rule_type"]
        pattern, pattern_reason = "排板观察", queue_reason
    elif base_ok and half_ok:
        bucket = "half"
        rule_name, rule_type = cfg["half_rule_name"], cfg["half_rule_type"]
        pattern, pattern_reason = "半路买点", half_reason
    else:
        bucket = "none"
        rule_name, rule_type = "未触发", "观察"
        pattern = "无买点"
        detail = []
        if not base_ok:
            detail.append("基础过滤未过")
        detail += [f"半路:{half_reason}", f"扫板:{sweep_reason}", f"排板:{queue_reason}", f"回封:{reseal_reason}"]
        pattern_reason = "；".join(detail)

    rule_pass = bucket != "none"
    return {
        "market_mode_effective": mode,
        "market_mode_pass": mode_ok,
        "market_mode_reason": mode_reason,
        "middle_position_type": middle_type,
        "middle_filter_pass": middle_ok,
        "middle_filter_reason": middle_reason,
        "theme_pass": theme_ok,
        "theme_reason": theme_reason,
        "popularity_pass": pop_ok,
        "popularity_reason": pop_reason,
        "pattern_signal": pattern,
        "pattern_pass": rule_pass,
        "pattern_reason": pattern_reason,
        "rule_name": rule_name,
        "rule_type": rule_type,
        "rule_version": cfg.get("rule_version", "v8.2.1-kobe"),
        "rule_params": build_rule_params(cfg, bucket),
        "signal_source": "92科比模式过滤+自定义规则",
        "trigger_reason": f"{base_reason}；{pattern_reason}",
        "rule_pass": rule_pass,
        "trade_allowed": rule_pass,
    }


# -------------------------
# 处理与归因
# -------------------------

def process_kobe_rule_snapshot_v8_2_1(globs: dict | None = None) -> tuple[pd.DataFrame, str]:
    cfg = load_config()
    if not cfg.get("enabled", True):
        return pd.DataFrame(), "v8.2.1 规则未启用。"

    raw = find_watch_df_from_globals(globs or {})
    if raw.empty:
        return pd.DataFrame(), "未找到盯盘股票池。"

    x = standardize_df(raw)
    if x.empty:
        return pd.DataFrame(), "盯盘股票池标准化后为空。"

    x = add_popularity_ranks(x)
    emotion = load_emotion()

    rows = []
    for _, row in x.iterrows():
        rows.append(assign_rule(row, cfg, emotion))

    attr = pd.DataFrame(rows)
    out = pd.concat([x.reset_index(drop=True), attr.reset_index(drop=True)], axis=1)

    # 便于排序
    if "trade_allowed" in out.columns:
        out["_sort_trade"] = out["trade_allowed"].astype(bool).astype(int)
    else:
        out["_sort_trade"] = 0
    if "涨跌幅" not in out.columns:
        out["涨跌幅"] = 0

    out = out.sort_values(["_sort_trade", "涨跌幅"], ascending=[False, False], na_position="last").drop(columns=["_sort_trade"])
    out.to_csv(SNAPSHOT_PATH, index=False, encoding="utf-8-sig")

    n_signal = int(out["trade_allowed"].astype(bool).sum()) if "trade_allowed" in out.columns else 0
    msg = f"v8.2.1 92科比规则完成：股票 {len(out)} 只，可交易/观察信号 {n_signal} 只。"
    return out, msg


def attribute_event_log_v8_2_1() -> tuple[pd.DataFrame, str]:
    events = read_csv_safe(EVENT_LOG_PATH)
    attrs = read_csv_safe(SNAPSHOT_PATH)

    if events.empty:
        return pd.DataFrame(), "未找到 reports/watch_signal_events.csv。"
    if attrs.empty:
        return events, "未找到 v8.2.1 归因快照。"

    e = events.copy()
    a = attrs.copy()

    if "代码" not in e.columns or "代码" not in a.columns:
        return e, "事件或快照缺少代码列。"

    e["代码"] = e["代码"].map(_norm_code)
    a["代码"] = a["代码"].map(_norm_code)

    attr_cols = [
        "代码", "rule_name", "rule_type", "rule_version", "rule_params", "signal_source",
        "trigger_reason", "market_mode_effective", "middle_position_type", "pattern_signal",
        "rule_pass", "trade_allowed", "换手率", "量比", "成交量_万手", "昨日成交量_万手",
        "成交量较昨日倍数", "板块内涨幅排名", "板块内成交额排名", "全市场涨速排名",
    ]
    attr_cols = [c for c in attr_cols if c in a.columns]
    a = a[attr_cols].drop_duplicates("代码", keep="first")

    for c in attr_cols:
        if c != "代码" and c in e.columns:
            e = e.drop(columns=[c])

    out = e.merge(a, on="代码", how="left")
    out.to_csv(ATTR_EVENT_PATH, index=False, encoding="utf-8-sig")

    # 同步写回主事件日志，让 v8.2 原统计也可以读到rule_name/rule_type
    try:
        out.to_csv(EVENT_LOG_PATH, index=False, encoding="utf-8-sig")
    except Exception:
        pass

    return out, f"事件日志归因完成：{len(out)} 条。"


def _win_rate(s: pd.Series) -> float:
    ss = pd.to_numeric(s, errors="coerce").dropna()
    if ss.empty:
        return float("nan")
    return round(float((ss > 0).mean() * 100), 2)


def summarize_effect(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()

    rows = []
    for name, g in df.groupby(group_col):
        row = {
            group_col: name,
            "样本数": int(len(g)),
        }
        for col, label in [
            ("ret_1m", "1分钟均值"),
            ("ret_5m", "5分钟均值"),
            ("ret_10m", "10分钟均值"),
            ("ret_30m", "30分钟均值"),
            ("ret_close", "收盘均值"),
            ("mfe_30m", "最大有利波动均值"),
            ("mae_30m", "最大回撤均值"),
        ]:
            row[label] = round(float(pd.to_numeric(g[col], errors="coerce").mean()), 4) if col in g.columns else float("nan")

        for col, label in [("ret_5m", "胜率_5分钟"), ("ret_10m", "胜率_10分钟"), ("ret_close", "胜率_收盘")]:
            row[label] = _win_rate(g[col]) if col in g.columns else float("nan")

        if row["样本数"] < 5:
            row["建议"] = "样本偏少，继续观察"
        elif row.get("5分钟均值", 0) > 0 and row.get("胜率_5分钟", 0) >= 55:
            row["建议"] = "短线有效，可保留/略放宽"
        elif row.get("最大回撤均值", 0) < -2:
            row["建议"] = "回撤偏大，收紧情绪/量能/板块前排过滤"
        else:
            row["建议"] = "效果一般，继续优化参数"
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["样本数", "5分钟均值"], ascending=[False, False])


def generate_rule_effect_stats_v8_2_1() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    # 先尽量调用原v8.2统计
    try:
        from signal_effect_stats_v8_2 import compute_and_save_signal_effects
        compute_and_save_signal_effects()
    except Exception:
        pass

    records = read_csv_safe(REPORT_DIR / "signal_effect_records_v8_2.csv")
    events = read_csv_safe(ATTR_EVENT_PATH)

    if records.empty:
        return pd.DataFrame(), pd.DataFrame(), "未找到 v8.2 信号效果明细。请先运行 v8.2 信号效果统计。"

    if events.empty:
        events, _ = attribute_event_log_v8_2_1()

    if events.empty:
        # 如果没有事件归因，就直接尝试records里已有rule_name
        merged = records.copy()
    else:
        r = records.copy()
        e = events.copy()
        if "timestamp" in r.columns:
            r["timestamp_key"] = pd.to_datetime(r["timestamp"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
        if "timestamp" in e.columns:
            e["timestamp_key"] = pd.to_datetime(e["timestamp"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
        for df in [r, e]:
            if "代码" in df.columns:
                df["代码"] = df["代码"].map(_norm_code)
            if "to_state" not in df.columns and "标准状态" in df.columns:
                df["to_state"] = df["标准状态"]

        join_cols = [c for c in ["timestamp_key", "代码", "to_state"] if c in r.columns and c in e.columns]
        attr_cols = [
            "rule_name", "rule_type", "rule_version", "rule_params", "signal_source", "trigger_reason",
            "market_mode_effective", "middle_position_type", "pattern_signal", "trade_allowed",
        ]
        attr_cols = [c for c in attr_cols if c in e.columns]
        if join_cols:
            ee = e[join_cols + attr_cols].drop_duplicates(join_cols, keep="last")
            merged = r.merge(ee, on=join_cols, how="left")
        elif "代码" in r.columns and "代码" in e.columns:
            ee = e[["代码"] + attr_cols].drop_duplicates("代码", keep="last")
            merged = r.merge(ee, on="代码", how="left")
        else:
            merged = r

    if "rule_name" not in merged.columns:
        merged["rule_name"] = "未归因"
    if "rule_type" not in merged.columns:
        merged["rule_type"] = "未归因"

    merged["rule_name"] = merged["rule_name"].fillna("未归因")
    merged["rule_type"] = merged["rule_type"].fillna("未归因")

    by_rule = summarize_effect(merged, "rule_name")
    by_type = summarize_effect(merged, "rule_type")

    by_rule.to_csv(RULE_STATS_PATH, index=False, encoding="utf-8-sig")
    by_type.to_csv(RULE_TYPE_STATS_PATH, index=False, encoding="utf-8-sig")
    write_suggestions(by_rule, by_type)

    return by_rule, by_type, f"按规则统计完成：rule_name {len(by_rule)} 个，rule_type {len(by_type)} 个。"


def write_suggestions(by_rule: pd.DataFrame, by_type: pd.DataFrame) -> None:
    lines = ["# v8.2.1 92科比模式规则归因统计建议", ""]
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 按 rule_name")
    if by_rule.empty:
        lines.append("- 暂无数据。")
    else:
        for _, r in by_rule.iterrows():
            lines.append(
                f"- {r.get('rule_name')}: 样本 {int(r.get('样本数', 0))}，"
                f"5分钟均值 {r.get('5分钟均值')}%，5分钟胜率 {r.get('胜率_5分钟')}%，"
                f"最大回撤 {r.get('最大回撤均值')}%。建议：{r.get('建议')}"
            )

    lines.append("")
    lines.append("## 按 rule_type")
    if by_type.empty:
        lines.append("- 暂无数据。")
    else:
        for _, r in by_type.iterrows():
            lines.append(
                f"- {r.get('rule_type')}: 样本 {int(r.get('样本数', 0))}，"
                f"5分钟均值 {r.get('5分钟均值')}%，5分钟胜率 {r.get('胜率_5分钟')}%。建议：{r.get('建议')}"
            )

    lines.append("")
    lines.append("## 优化方向")
    lines.append("- 龙头模式有效：可适当提高人气/板块前排权重，减少低位杂毛。")
    lines.append("- 补涨模式有效：可降低涨幅阈值，增加题材新鲜度与首板扩散过滤。")
    lines.append("- 扫板回撤大：禁止退潮/冰点扫板，提高板块涨停数和封单资金要求。")
    lines.append("- 排板效果弱：增加撤单观察，不做尾盘弱封。")
    lines.append("- 回封有效：保留回封确认，但限制炸板次数和成交额异常放大。")
    lines.append("- 半路无效：提高涨速、成交额、量比或板块前排排名要求。")
    SUGGEST_PATH.write_text("\n".join(lines), encoding="utf-8")


# -------------------------
# Streamlit UI
# -------------------------

def render_kobe_rule_panel_v8_2_1(globs: dict | None = None) -> None:
    import streamlit as st

    cfg = load_config()
    emotion = load_emotion()

    st.subheader("自定义交易规则 v8.2.1：92科比模式归因版")
    st.caption("新版不再横向堆指标，而是按 市场模式 → 半路 → 打板细分 → 题材人气 → 风险卖点 的五层逻辑过滤。信号会记录 rule_name / rule_type，用于后续胜率统计。")

    with st.expander("一、市场模式：龙头 / 补涨 / 切换 / 空仓", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cfg["enabled"] = st.checkbox("启用v8.2.1规则", value=bool(cfg.get("enabled", True)), key="kobe_enabled")
        with c2:
            cfg["rule_version"] = st.text_input("规则版本 rule_version", value=str(cfg.get("rule_version", "v8.2.1-kobe")), key="kobe_rule_version")
        with c3:
            cfg["market_mode"] = st.selectbox(
                "市场模式",
                ["自动判断", "龙头模式", "补涨模式", "切换模式", "空仓/防守模式", "混合模式"],
                index=["自动判断", "龙头模式", "补涨模式", "切换模式", "空仓/防守模式", "混合模式"].index(cfg.get("market_mode", "自动判断")) if cfg.get("market_mode", "自动判断") in ["自动判断", "龙头模式", "补涨模式", "切换模式", "空仓/防守模式", "混合模式"] else 0,
                key="kobe_market_mode",
            )
        with c4:
            cfg["index_condition"] = st.selectbox(
                "指数状态",
                ["自动/未知", "指数好", "指数弱"],
                index=["自动/未知", "指数好", "指数弱"].index(cfg.get("index_condition", "自动/未知")) if cfg.get("index_condition", "自动/未知") in ["自动/未知", "指数好", "指数弱"] else 0,
                key="kobe_index_condition",
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["allow_trade_in_cold"] = st.checkbox("冰点/退潮仍允许试错", value=bool(cfg.get("allow_trade_in_cold", False)), key="kobe_allow_cold")
        with c2:
            cfg["prefer_leader_when_strong"] = st.checkbox("情绪好优先龙头/人气核心", value=bool(cfg.get("prefer_leader_when_strong", True)), key="kobe_pref_leader")
        with c3:
            cfg["prefer_first_board_when_index_weak"] = st.checkbox("指数弱优先低位首板/补涨", value=bool(cfg.get("prefer_first_board_when_index_weak", True)), key="kobe_pref_first")

        mode, mode_ok, mode_reason = infer_market_mode(cfg, emotion)
        st.info(f"当前情绪：{emotion.get('emotion_phase', '未知')} / {emotion.get('emotion_score', '无')}；生效模式：{mode}；{mode_reason}")

    with st.expander("二、半路买点：涨幅 / 涨速 / 成交额 / 板块联动 / 人气 / 量能", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cfg["half_enabled"] = st.checkbox("启用半路买点", value=bool(cfg.get("half_enabled", True)), key="kobe_half_enabled")
            cfg["half_rule_name"] = st.text_input("半路 rule_name", value=str(cfg.get("half_rule_name", "半路买点-主线前排量能确认")), key="kobe_half_name")
            cfg["half_rule_type"] = st.selectbox("半路 rule_type", ["半路", "补涨", "切换"], index=["半路", "补涨", "切换"].index(cfg.get("half_rule_type", "半路")) if cfg.get("half_rule_type", "半路") in ["半路", "补涨", "切换"] else 0, key="kobe_half_type")
        with c2:
            cfg["half_min_pct"] = st.number_input("半路最低涨幅%", 0.0, 20.0, float(cfg.get("half_min_pct", 3.0)), 0.1, key="kobe_half_min_pct")
            cfg["half_max_pct"] = st.number_input("半路最高涨幅%", 0.0, 20.0, float(cfg.get("half_max_pct", 8.0)), 0.1, key="kobe_half_max_pct")
            cfg["half_min_speed"] = st.number_input("半路最低5分钟涨速%", -10.0, 20.0, float(cfg.get("half_min_speed", 0.5)), 0.1, key="kobe_half_speed")
            cfg["half_min_amount_yi"] = st.number_input("半路最低成交额 亿", 0.0, 500.0, float(cfg.get("half_min_amount_yi", 0.5)), 0.1, key="kobe_half_amount")
        with c3:
            cfg["half_min_board_strong_count"] = st.number_input("半路：板块强势股数量≥", 0, 1000, int(cfg.get("half_min_board_strong_count", 3)), 1, key="kobe_half_strong")
            cfg["half_min_board_limit_count"] = st.number_input("半路：板块涨停数≥", 0, 1000, int(cfg.get("half_min_board_limit_count", 0)), 1, key="kobe_half_limit")
            cfg["half_min_turnover"] = st.number_input("半路最低换手率%", 0.0, 100.0, float(cfg.get("half_min_turnover", 3.0)), 0.1, key="kobe_half_turn_min")
            cfg["half_max_turnover"] = st.number_input("半路最高换手率%", 0.0, 200.0, float(cfg.get("half_max_turnover", 30.0)), 0.1, key="kobe_half_turn_max")
            cfg["half_min_volume_ratio"] = st.number_input("半路最低量比", 0.0, 50.0, float(cfg.get("half_min_volume_ratio", 1.0)), 0.1, key="kobe_half_vr")
            cfg["half_min_volume_wan_shou"] = st.number_input("半路最低成交量 万手", 0.0, 100000.0, float(cfg.get("half_min_volume_wan_shou", 5.0)), 1.0, key="kobe_half_vol")
            cfg["half_min_volume_vs_yesterday"] = st.number_input("半路最低今日/昨日量", 0.0, 50.0, float(cfg.get("half_min_volume_vs_yesterday", 0.25)), 0.05, key="kobe_half_vy")

    with st.expander("三、打板细分：扫板 / 排板 / 回封", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("#### 扫板")
            cfg["sweep_enabled"] = st.checkbox("启用扫板规则", value=bool(cfg.get("sweep_enabled", True)), key="kobe_sweep_enabled")
            cfg["sweep_rule_name"] = st.text_input("扫板 rule_name", value=str(cfg.get("sweep_rule_name", "扫板-强情绪前排确认")), key="kobe_sweep_name")
            cfg["sweep_rule_type"] = "扫板"
            cfg["sweep_min_pct"] = st.number_input("扫板：涨幅≥%", 0.0, 20.0, float(cfg.get("sweep_min_pct", 9.3)), 0.1, key="kobe_sweep_pct")
            cfg["sweep_min_speed"] = st.number_input("扫板：5分钟涨速≥%", -10.0, 20.0, float(cfg.get("sweep_min_speed", 0.3)), 0.1, key="kobe_sweep_speed")
            cfg["sweep_min_amount_yi"] = st.number_input("扫板：成交额≥亿", 0.0, 500.0, float(cfg.get("sweep_min_amount_yi", 0.5)), 0.1, key="kobe_sweep_amount")
            cfg["sweep_min_board_limit_count"] = st.number_input("扫板：板块涨停数≥", 0, 1000, int(cfg.get("sweep_min_board_limit_count", 1)), 1, key="kobe_sweep_limit")
            cfg["sweep_block_cold_phase"] = st.checkbox("退潮/冰点禁止扫板", value=bool(cfg.get("sweep_block_cold_phase", True)), key="kobe_sweep_block_cold")

        with col2:
            st.markdown("#### 排板")
            cfg["queue_enabled"] = st.checkbox("启用排板规则", value=bool(cfg.get("queue_enabled", True)), key="kobe_queue_enabled")
            cfg["queue_rule_name"] = st.text_input("排板 rule_name", value=str(cfg.get("queue_rule_name", "排板-封单观察")), key="kobe_queue_name")
            cfg["queue_rule_type"] = "排板"
            cfg["queue_min_pct"] = st.number_input("排板：涨幅≥%", 0.0, 20.0, float(cfg.get("queue_min_pct", 9.7)), 0.1, key="kobe_queue_pct")
            cfg["queue_allow_observe_cancel"] = st.checkbox("允许排板观察/撤单观察", value=bool(cfg.get("queue_allow_observe_cancel", True)), key="kobe_queue_cancel")
            cfg["queue_require_seal_fund"] = st.checkbox("要求封单资金", value=bool(cfg.get("queue_require_seal_fund", False)), key="kobe_queue_require_fund")
            cfg["queue_min_seal_fund_wan"] = st.number_input("排板：封单资金≥万", 0.0, 10000000.0, float(cfg.get("queue_min_seal_fund_wan", 1000.0)), 100.0, key="kobe_queue_fund")

        with col3:
            st.markdown("#### 回封")
            cfg["reseal_enabled"] = st.checkbox("启用回封规则", value=bool(cfg.get("reseal_enabled", True)), key="kobe_reseal_enabled")
            cfg["reseal_rule_name"] = st.text_input("回封 rule_name", value=str(cfg.get("reseal_rule_name", "回封-承接确认")), key="kobe_reseal_name")
            cfg["reseal_rule_type"] = "回封"
            cfg["reseal_max_open_count"] = st.number_input("回封：炸板次数≤", 0, 20, int(cfg.get("reseal_max_open_count", 2)), 1, key="kobe_reseal_open")
            cfg["reseal_latest_time"] = st.text_input("回封：最晚时间 HH:MM", value=str(cfg.get("reseal_latest_time", "14:30")), key="kobe_reseal_time")
            cfg["reseal_max_amount_expansion"] = st.number_input("回封：成交额异常放大≤倍", 0.0, 50.0, float(cfg.get("reseal_max_amount_expansion", 3.0)), 0.1, key="kobe_reseal_expand")
            cfg["reseal_min_seal_fund_wan"] = st.number_input("回封后封单资金≥万", 0.0, 10000000.0, float(cfg.get("reseal_min_seal_fund_wan", 800.0)), 100.0, key="kobe_reseal_fund")

        st.markdown("#### 打板通用量能")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            cfg["board_min_turnover"] = st.number_input("打板最低换手率%", 0.0, 100.0, float(cfg.get("board_min_turnover", 5.0)), 0.1, key="kobe_board_turn_min")
        with c2:
            cfg["board_max_turnover"] = st.number_input("打板最高换手率%", 0.0, 200.0, float(cfg.get("board_max_turnover", 45.0)), 0.1, key="kobe_board_turn_max")
        with c3:
            cfg["board_min_volume_ratio"] = st.number_input("打板最低量比", 0.0, 50.0, float(cfg.get("board_min_volume_ratio", 1.2)), 0.1, key="kobe_board_vr")
        with c4:
            cfg["board_min_volume_wan_shou"] = st.number_input("打板最低成交量万手", 0.0, 100000.0, float(cfg.get("board_min_volume_wan_shou", 8.0)), 1.0, key="kobe_board_vol")
        with c5:
            cfg["board_min_volume_vs_yesterday"] = st.number_input("打板最低今日/昨日量", 0.0, 50.0, float(cfg.get("board_min_volume_vs_yesterday", 0.35)), 0.05, key="kobe_board_vy")

    with st.expander("四、题材与人气：新闻催化 / 题材阶段 / 前排 / 辨识度 / 股性", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 题材/新闻确认")
            cfg["theme_enabled"] = st.checkbox("启用题材过滤", value=bool(cfg.get("theme_enabled", True)), key="kobe_theme_enabled")
            cfg["require_news_catalyst"] = st.checkbox("要求当日新闻催化", value=bool(cfg.get("require_news_catalyst", False)), key="kobe_news")
            cfg["require_main_theme"] = st.checkbox("要求属于当前主线题材", value=bool(cfg.get("require_main_theme", False)), key="kobe_main_theme")
            cfg["require_first_ferment_or_divergence_to_consensus"] = st.checkbox("要求首日发酵/分歧转一致", value=bool(cfg.get("require_first_ferment_or_divergence_to_consensus", False)), key="kobe_first_ferment")
            cfg["exclude_retired_theme"] = st.checkbox("排除已淘汰/退潮题材", value=bool(cfg.get("exclude_retired_theme", True)), key="kobe_exclude_retired")
            cfg["theme_fresh_days"] = st.number_input("题材新鲜度 天", 1, 30, int(cfg.get("theme_fresh_days", 3)), 1, key="kobe_theme_days")
            cfg["news_strength"] = st.selectbox("新闻强度", ["不限", "政策", "订单", "业绩", "并购", "算力", "AI", "机器人", "低空经济"], index=["不限", "政策", "订单", "业绩", "并购", "算力", "AI", "机器人", "低空经济"].index(cfg.get("news_strength", "不限")) if cfg.get("news_strength", "不限") in ["不限", "政策", "订单", "业绩", "并购", "算力", "AI", "机器人", "低空经济"] else 0, key="kobe_news_strength")
            cfg["theme_stage"] = st.selectbox("题材阶段", ["不限", "首日发酵", "二日加强", "高潮", "分歧", "退潮", "分歧转一致"], index=["不限", "首日发酵", "二日加强", "高潮", "分歧", "退潮", "分歧转一致"].index(cfg.get("theme_stage", "不限")) if cfg.get("theme_stage", "不限") in ["不限", "首日发酵", "二日加强", "高潮", "分歧", "退潮", "分歧转一致"] else 0, key="kobe_theme_stage")
            cfg["allow_missing_news"] = st.checkbox("缺失新闻字段时允许通过", value=bool(cfg.get("allow_missing_news", True)), key="kobe_allow_news")

        with col2:
            st.markdown("#### 人气辨识度")
            cfg["popularity_enabled"] = st.checkbox("启用人气过滤", value=bool(cfg.get("popularity_enabled", True)), key="kobe_pop_enabled")
            cfg["require_board_front"] = st.checkbox("要求板块前排", value=bool(cfg.get("require_board_front", False)), key="kobe_board_front")
            cfg["industry_pct_rank_max"] = st.number_input("板块内涨幅排名≤", 1, 1000, int(cfg.get("industry_pct_rank_max", 3)), 1, key="kobe_pct_rank")
            cfg["industry_amount_rank_max"] = st.number_input("板块内成交额排名≤", 1, 1000, int(cfg.get("industry_amount_rank_max", 5)), 1, key="kobe_amount_rank")
            cfg["global_speed_rank_max"] = st.number_input("全市场涨速排名≤", 1, 10000, int(cfg.get("global_speed_rank_max", 100)), 1, key="kobe_speed_rank")
            cfg["recent_limit_days"] = st.number_input("近期统计天数N", 1, 250, int(cfg.get("recent_limit_days", 20)), 1, key="kobe_recent_days")
            cfg["min_recent_limit_count"] = st.number_input("近N日涨停次数≥", 0, 50, int(cfg.get("min_recent_limit_count", 0)), 1, key="kobe_recent_limit")
            cfg["max_recent_bomb_count"] = st.number_input("近N日炸板次数≤", 0, 50, int(cfg.get("max_recent_bomb_count", 2)), 1, key="kobe_recent_bomb")
            cfg["require_good_stock_character"] = st.checkbox("要求股性较好", value=bool(cfg.get("require_good_stock_character", False)), key="kobe_good_character")
            cfg["allow_missing_popularity"] = st.checkbox("缺失人气字段时允许通过", value=bool(cfg.get("allow_missing_popularity", True)), key="kobe_allow_pop")
            cfg["allow_missing_stock_character"] = st.checkbox("缺失股性字段时允许通过", value=bool(cfg.get("allow_missing_stock_character", True)), key="kobe_allow_character")

    with st.expander("五、风险与卖点：中位股 / 炸板 / 退潮 / 成交额异常 / 弱转强失败", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 中位股过滤")
            cfg["middle_filter_enabled"] = st.checkbox("启用中位股过滤", value=bool(cfg.get("middle_filter_enabled", True)), key="kobe_mid_enabled")
            cfg["avoid_middle_position"] = st.checkbox("排除中位股", value=bool(cfg.get("avoid_middle_position", True)), key="kobe_avoid_mid")
            cfg["low_chain_max"] = st.number_input("低位定义：连板数≤", 0, 20, int(cfg.get("low_chain_max", 1)), 1, key="kobe_low_chain")
            cfg["low_pct_max"] = st.number_input("低位定义：涨幅≤%", 0.0, 20.0, float(cfg.get("low_pct_max", 5.0)), 0.1, key="kobe_low_pct")
            cfg["high_chain_min"] = st.number_input("高位定义：连板数≥", 0, 20, int(cfg.get("high_chain_min", 3)), 1, key="kobe_high_chain")
            cfg["high_is_board_front"] = st.checkbox("高位可由板块核心/前排定义", value=bool(cfg.get("high_is_board_front", True)), key="kobe_high_front")

        with col2:
            st.markdown("#### 风险规则")
            cfg["risk_enabled"] = st.checkbox("启用风险/卖点提醒", value=bool(cfg.get("risk_enabled", True)), key="kobe_risk_enabled")
            cfg["risk_rule_name"] = st.text_input("风控 rule_name", value=str(cfg.get("risk_rule_name", "风控-退潮/中位/量能异常")), key="kobe_risk_name")
            cfg["risk_rule_type"] = "风控"
            cfg["risk_min_pct"] = st.number_input("风险：个股涨幅低于%", -30.0, 30.0, float(cfg.get("risk_min_pct", -3.0)), 0.1, key="kobe_risk_pct")
            cfg["risk_min_speed"] = st.number_input("风险：5分钟涨速低于%", -30.0, 30.0, float(cfg.get("risk_min_speed", -1.0)), 0.1, key="kobe_risk_speed")
            cfg["risk_max_turnover"] = st.number_input("风险：换手率高于%", 0.0, 300.0, float(cfg.get("risk_max_turnover", 55.0)), 0.1, key="kobe_risk_turn")
            cfg["risk_max_volume_vs_yesterday"] = st.number_input("风险：今日/昨日量高于", 0.0, 100.0, float(cfg.get("risk_max_volume_vs_yesterday", 3.5)), 0.1, key="kobe_risk_vy")
            cfg["risk_low_volume_ratio"] = st.number_input("风险：量比低于", 0.0, 50.0, float(cfg.get("risk_low_volume_ratio", 0.5)), 0.1, key="kobe_risk_vr")
            cfg["risk_weak_to_strong_fail"] = st.checkbox("弱转强失败提醒", value=bool(cfg.get("risk_weak_to_strong_fail", True)), key="kobe_weak_fail")
            cfg["allow_missing_volume"] = st.checkbox("缺失量能字段时允许通过", value=bool(cfg.get("allow_missing_volume", True)), key="kobe_allow_vol")

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("保存v8.2.1规则", type="primary", key="kobe_save"):
            save_config(cfg)
            st.success("已保存到 config/kobe_rule_attribution_v8_2_1.json。")
    with b2:
        if st.button("立即生成规则归因快照", key="kobe_apply"):
            save_config(cfg)
            out, msg = process_kobe_rule_snapshot_v8_2_1(globs or {})
            ev, msg2 = attribute_event_log_v8_2_1()
            st.success(msg + " " + msg2)
    with b3:
        if st.button("生成按规则胜率统计", key="kobe_stats"):
            by_rule, by_type, msg = generate_rule_effect_stats_v8_2_1()
            st.success(msg)

    out, msg = process_kobe_rule_snapshot_v8_2_1(globs or {})
    if out.empty:
        st.warning(msg)
        return

    show_cols = [c for c in [
        "代码", "名称", "最新价", "涨跌幅", "规则涨速", "成交额_亿", "换手率", "量比",
        "成交量_万手", "昨日成交量_万手", "成交量较昨日倍数", "所属行业", "最强概念",
        "market_mode_effective", "middle_position_type", "pattern_signal", "rule_name",
        "rule_type", "rule_version", "trade_allowed", "trigger_reason"
    ] if c in out.columns]

    st.info(msg)
    st.dataframe(out[show_cols].head(400), hide_index=True, use_container_width=True, height=460)

    if RULE_STATS_PATH.exists():
        st.markdown("#### 按 rule_name 胜率统计")
        st.dataframe(read_csv_safe(RULE_STATS_PATH), hide_index=True, use_container_width=True, height=260)

    if RULE_TYPE_STATS_PATH.exists():
        st.markdown("#### 按 rule_type 胜率统计")
        st.dataframe(read_csv_safe(RULE_TYPE_STATS_PATH), hide_index=True, use_container_width=True, height=220)

    if SUGGEST_PATH.exists():
        with st.expander("参数优化建议", expanded=True):
            st.markdown(SUGGEST_PATH.read_text(encoding="utf-8"))
