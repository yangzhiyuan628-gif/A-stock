# -*- coding: utf-8 -*-
"""
custom_rule_volume_v8_2_2.py

v8.2.2：自定义交易规则增加量能过滤字段：
- 换手率 %
- 量比
- 成交量 万手
- 昨日成交量 万手
- 今日成交量 / 昨日成交量 倍数

用途：
1. 给“半路买点”“接近涨停/打板”“卖出/风险提醒”增加量能条件；
2. 自动给当前盯盘股票池补充量能判断列；
3. 输出 reports/latest_watch_signals_volume_v8_2_2.csv；
4. 后续 v8.2 信号效果统计可基于这些列继续做规则归因。

注意：
- 如果行情源没有“量比”或“昨日成交量”，该字段会显示为空；
- 可在设置里选择“缺失量能字段时仍允许通过”或“不允许通过”。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
REPORT_DIR = ROOT / "reports"
CONFIG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

CONFIG_PATH = CONFIG_DIR / "custom_rule_volume_v8_2_2.json"
OUT_PATH = REPORT_DIR / "latest_watch_signals_volume_v8_2_2.csv"

DEFAULT_CONFIG = {
    "enabled": True,
    "allow_missing_volume_fields": True,

    "half_enabled": True,
    "half_min_turnover": 3.0,
    "half_max_turnover": 30.0,
    "half_min_volume_ratio": 1.0,
    "half_min_volume_wan_shou": 5.0,
    "half_min_volume_vs_yesterday": 0.25,

    "board_enabled": True,
    "board_min_turnover": 5.0,
    "board_max_turnover": 45.0,
    "board_min_volume_ratio": 1.2,
    "board_min_volume_wan_shou": 8.0,
    "board_min_volume_vs_yesterday": 0.35,

    "risk_enabled": True,
    "risk_max_turnover": 55.0,
    "risk_max_volume_vs_yesterday": 3.5,
    "risk_low_volume_ratio": 0.5,
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

    # 注意：金额和成交量都可能出现“万/亿”，这里只负责数值标准化。
    if "亿" in s:
        return val * 10000.0  # 对成交量统一为“万手”时，亿手 -> 万手
    if "万" in s:
        return val
    return val


def _to_percent(x: Any, default: float = float("nan")) -> float:
    return _to_float(x, default=default)


def parse_volume_to_wan_shou(x: Any) -> float:
    """
    尽量把成交量转换成“万手”。

    常见情况：
    - 已经是 12.3万手 -> 12.3
    - 123000手 -> 12.3
    - 12300000股 -> 12.3万手，因为1手=100股
    - 如果原始字段没有单位，A股行情的“成交量”常见是“手”，按手处理。
    """
    if x is None:
        return float("nan")
    try:
        if pd.isna(x):
            return float("nan")
    except Exception:
        pass

    if isinstance(x, (int, float)):
        # 默认无单位按“手”处理
        return float(x) / 10000.0

    s = str(x).strip().replace(",", "")
    if not s or s in {"-", "--", "None", "nan", "NaN"}:
        return float("nan")

    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return float("nan")

    val = float(m.group(0))

    if "亿手" in s:
        return val * 10000.0
    if "万手" in s:
        return val
    if "手" in s:
        return val / 10000.0

    if "亿股" in s:
        return val * 10000.0 / 100.0
    if "万股" in s:
        return val / 100.0
    if "股" in s:
        return val / 100.0 / 10000.0

    # 无单位默认按“手”
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


def standardize_volume_columns(df: pd.DataFrame) -> pd.DataFrame:
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

    turnover_col = find_col(x, ["换手率", "换手", "turnover", "turnover_rate"])
    volume_ratio_col = find_col(x, ["量比", "volume_ratio", "vol_ratio"])
    volume_col = find_col(x, ["成交量", "成交量_手", "volume", "vol"])
    y_volume_col = find_col(x, ["昨日成交量", "昨成交量", "昨日量", "昨量", "pre_volume", "yesterday_volume"])

    if turnover_col:
        x["换手率"] = x[turnover_col].map(_to_percent)
    elif "换手率" not in x.columns:
        x["换手率"] = pd.NA

    if volume_ratio_col:
        x["量比"] = x[volume_ratio_col].map(lambda v: _to_float(v))
    elif "量比" not in x.columns:
        x["量比"] = pd.NA

    if volume_col:
        x["成交量_万手"] = x[volume_col].map(parse_volume_to_wan_shou)
    elif "成交量_万手" not in x.columns:
        x["成交量_万手"] = pd.NA

    if y_volume_col:
        x["昨日成交量_万手"] = x[y_volume_col].map(parse_volume_to_wan_shou)
    elif "昨日成交量_万手" not in x.columns:
        x["昨日成交量_万手"] = pd.NA

    cur = pd.to_numeric(x["成交量_万手"], errors="coerce")
    pre = pd.to_numeric(x["昨日成交量_万手"], errors="coerce")
    x["成交量较昨日倍数"] = cur / pre.replace(0, pd.NA)

    return x


def _missing(v: Any) -> bool:
    try:
        return pd.isna(v)
    except Exception:
        return v is None


def _between_or_missing(value: Any, lo: float | None, hi: float | None, allow_missing: bool) -> tuple[bool, str]:
    if _missing(value):
        return allow_missing, "缺失"
    v = float(value)
    if lo is not None and v < lo:
        return False, f"{v:.2f} < {lo:.2f}"
    if hi is not None and v > hi:
        return False, f"{v:.2f} > {hi:.2f}"
    return True, f"{v:.2f}"


def _ge_or_missing(value: Any, lo: float, allow_missing: bool) -> tuple[bool, str]:
    if _missing(value):
        return allow_missing, "缺失"
    v = float(value)
    if v < lo:
        return False, f"{v:.2f} < {lo:.2f}"
    return True, f"{v:.2f}"


def evaluate_volume_rule(row: pd.Series, rule_type: str, cfg: dict | None = None) -> tuple[bool, str]:
    """
    rule_type:
    - half：半路
    - board：接近涨停/打板
    - risk：风险提醒
    """
    cfg = {**DEFAULT_CONFIG, **(cfg or load_config())}
    allow_missing = bool(cfg.get("allow_missing_volume_fields", True))

    turnover = row.get("换手率", pd.NA)
    vol_ratio = row.get("量比", pd.NA)
    vol = row.get("成交量_万手", pd.NA)
    vol_vs_y = row.get("成交量较昨日倍数", pd.NA)

    checks = []

    if rule_type == "half":
        if not cfg.get("half_enabled", True):
            return True, "半路量能过滤未启用"

        ok, msg = _between_or_missing(turnover, float(cfg["half_min_turnover"]), float(cfg["half_max_turnover"]), allow_missing)
        checks.append(("换手率", ok, msg))
        ok, msg = _ge_or_missing(vol_ratio, float(cfg["half_min_volume_ratio"]), allow_missing)
        checks.append(("量比", ok, msg))
        ok, msg = _ge_or_missing(vol, float(cfg["half_min_volume_wan_shou"]), allow_missing)
        checks.append(("成交量_万手", ok, msg))
        ok, msg = _ge_or_missing(vol_vs_y, float(cfg["half_min_volume_vs_yesterday"]), allow_missing)
        checks.append(("较昨日量", ok, msg))

    elif rule_type == "board":
        if not cfg.get("board_enabled", True):
            return True, "打板量能过滤未启用"

        ok, msg = _between_or_missing(turnover, float(cfg["board_min_turnover"]), float(cfg["board_max_turnover"]), allow_missing)
        checks.append(("换手率", ok, msg))
        ok, msg = _ge_or_missing(vol_ratio, float(cfg["board_min_volume_ratio"]), allow_missing)
        checks.append(("量比", ok, msg))
        ok, msg = _ge_or_missing(vol, float(cfg["board_min_volume_wan_shou"]), allow_missing)
        checks.append(("成交量_万手", ok, msg))
        ok, msg = _ge_or_missing(vol_vs_y, float(cfg["board_min_volume_vs_yesterday"]), allow_missing)
        checks.append(("较昨日量", ok, msg))

    elif rule_type == "risk":
        if not cfg.get("risk_enabled", True):
            return False, "风险量能过滤未启用"

        risk_flags = []
        if not _missing(turnover) and float(turnover) >= float(cfg["risk_max_turnover"]):
            risk_flags.append(f"换手过高{float(turnover):.2f}%")
        if not _missing(vol_vs_y) and float(vol_vs_y) >= float(cfg["risk_max_volume_vs_yesterday"]):
            risk_flags.append(f"放量过猛{float(vol_vs_y):.2f}倍")
        if not _missing(vol_ratio) and float(vol_ratio) <= float(cfg["risk_low_volume_ratio"]):
            risk_flags.append(f"量比过低{float(vol_ratio):.2f}")

        if risk_flags:
            return True, "；".join(risk_flags)
        return False, "未触发量能风险"

    else:
        return True, "未知规则类型，默认通过"

    passed = all(x[1] for x in checks)
    reason = "；".join(f"{name}:{msg}" for name, ok, msg in checks)
    if passed:
        return True, "量能通过：" + reason
    return False, "量能不足：" + reason


def infer_rule_type(row: pd.Series) -> str:
    text = " ".join(
        _safe_str(row.get(c, ""))
        for c in ["买卖状态", "多空状态", "实时信号", "操作提示", "信号", "买点规则", "标准状态"]
        if c in row.index
    )

    if any(k in text for k in ["风险", "卖出", "回避", "破位", "炸板"]):
        return "risk"
    if any(k in text for k in ["打板", "排板", "封板", "接近涨停", "回封"]):
        return "board"
    if any(k in text for k in ["半路", "买点", "低位异动"]):
        return "half"

    # 按涨幅兜底
    pct = row.get("涨跌幅", row.get("涨幅", pd.NA))
    try:
        pct = float(pct)
        if pct >= 8:
            return "board"
        if 3 <= pct <= 8:
            return "half"
    except Exception:
        pass

    return "half"


def enhance_rules_with_volume(df: pd.DataFrame, cfg: dict | None = None) -> pd.DataFrame:
    cfg = {**DEFAULT_CONFIG, **(cfg or load_config())}
    if df is None or df.empty:
        return pd.DataFrame()

    x = standardize_volume_columns(df)

    passes = []
    reasons = []
    rule_types = []

    for _, row in x.iterrows():
        rule_type = infer_rule_type(row)
        ok, reason = evaluate_volume_rule(row, rule_type, cfg)
        passes.append(ok)
        reasons.append(reason)
        rule_types.append(rule_type)

    x["量能规则类型"] = rule_types
    x["量能规则通过"] = passes
    x["量能规则原因"] = reasons

    # 给旧买卖状态附加量能提示，不强行覆盖原状态
    if "买卖状态" in x.columns:
        x["买卖状态_含量能"] = x["买卖状态"].astype(str) + " | " + x["量能规则原因"].astype(str)
    elif "标准状态" in x.columns:
        x["买卖状态_含量能"] = x["标准状态"].astype(str) + " | " + x["量能规则原因"].astype(str)
    else:
        x["买卖状态_含量能"] = x["量能规则原因"].astype(str)

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
        REPORT_DIR / "realtime_last_snapshot.csv",
    ]:
        if p.exists():
            try:
                return pd.read_csv(p, dtype={"代码": str})
            except Exception:
                pass

    return pd.DataFrame()


def process_volume_rule_snapshot_v8_2_2(globs: dict | None = None) -> tuple[pd.DataFrame, str]:
    cfg = load_config()
    if not cfg.get("enabled", True):
        return pd.DataFrame(), "v8.2.2 量能规则未启用。"

    df = find_watch_df_from_globals(globs or {})
    if df.empty:
        return pd.DataFrame(), "未找到盯盘股票池。"

    out = enhance_rules_with_volume(df, cfg)
    if not out.empty:
        out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    passed = int(out["量能规则通过"].sum()) if "量能规则通过" in out.columns else 0
    msg = f"v8.2.2 量能规则完成：股票 {len(out)} 只，量能通过 {passed} 只。"
    return out, msg


def render_volume_rule_panel_v8_2_2(globs: dict | None = None) -> None:
    import streamlit as st

    cfg = load_config()

    st.markdown("### 量能过滤 v8.2.2")
    st.caption("新增换手率、量比、成交量、昨日成交量。单位：换手率%，成交量=万手，昨日成交量=万手。")

    c0, c1 = st.columns([1, 2])
    with c0:
        cfg["enabled"] = st.checkbox("启用量能过滤", value=bool(cfg.get("enabled", True)), key="v822_enabled")
    with c1:
        cfg["allow_missing_volume_fields"] = st.checkbox(
            "缺失量比/昨日成交量时仍允许通过",
            value=bool(cfg.get("allow_missing_volume_fields", True)),
            key="v822_allow_missing",
            help="有些行情源没有量比或昨日成交量。若取消勾选，缺失字段会导致量能过滤不通过。",
        )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 半路买点量能")
        cfg["half_enabled"] = st.checkbox("启用半路量能过滤", value=bool(cfg.get("half_enabled", True)), key="v822_half_enabled")
        cfg["half_min_turnover"] = st.number_input("半路：最低换手率 %", 0.0, 100.0, float(cfg.get("half_min_turnover", 3.0)), 0.1, key="v822_half_min_turnover")
        cfg["half_max_turnover"] = st.number_input("半路：最高换手率 %", 0.0, 200.0, float(cfg.get("half_max_turnover", 30.0)), 0.1, key="v822_half_max_turnover")
        cfg["half_min_volume_ratio"] = st.number_input("半路：最低量比", 0.0, 20.0, float(cfg.get("half_min_volume_ratio", 1.0)), 0.1, key="v822_half_min_vr")
        cfg["half_min_volume_wan_shou"] = st.number_input("半路：最低成交量 万手", 0.0, 10000.0, float(cfg.get("half_min_volume_wan_shou", 5.0)), 1.0, key="v822_half_min_vol")
        cfg["half_min_volume_vs_yesterday"] = st.number_input("半路：最低今日/昨日量", 0.0, 20.0, float(cfg.get("half_min_volume_vs_yesterday", 0.25)), 0.05, key="v822_half_min_y")

    with col2:
        st.markdown("#### 接近涨停/打板量能")
        cfg["board_enabled"] = st.checkbox("启用打板量能过滤", value=bool(cfg.get("board_enabled", True)), key="v822_board_enabled")
        cfg["board_min_turnover"] = st.number_input("打板：最低换手率 %", 0.0, 100.0, float(cfg.get("board_min_turnover", 5.0)), 0.1, key="v822_board_min_turnover")
        cfg["board_max_turnover"] = st.number_input("打板：最高换手率 %", 0.0, 200.0, float(cfg.get("board_max_turnover", 45.0)), 0.1, key="v822_board_max_turnover")
        cfg["board_min_volume_ratio"] = st.number_input("打板：最低量比", 0.0, 20.0, float(cfg.get("board_min_volume_ratio", 1.2)), 0.1, key="v822_board_min_vr")
        cfg["board_min_volume_wan_shou"] = st.number_input("打板：最低成交量 万手", 0.0, 10000.0, float(cfg.get("board_min_volume_wan_shou", 8.0)), 1.0, key="v822_board_min_vol")
        cfg["board_min_volume_vs_yesterday"] = st.number_input("打板：最低今日/昨日量", 0.0, 20.0, float(cfg.get("board_min_volume_vs_yesterday", 0.35)), 0.05, key="v822_board_min_y")

    with col3:
        st.markdown("#### 卖出/风险量能")
        cfg["risk_enabled"] = st.checkbox("启用风险量能过滤", value=bool(cfg.get("risk_enabled", True)), key="v822_risk_enabled")
        cfg["risk_max_turnover"] = st.number_input("风险：换手率高于 %", 0.0, 200.0, float(cfg.get("risk_max_turnover", 55.0)), 0.1, key="v822_risk_turnover")
        cfg["risk_max_volume_vs_yesterday"] = st.number_input("风险：今日/昨日量高于", 0.0, 50.0, float(cfg.get("risk_max_volume_vs_yesterday", 3.5)), 0.1, key="v822_risk_y")
        cfg["risk_low_volume_ratio"] = st.number_input("风险：量比低于", 0.0, 20.0, float(cfg.get("risk_low_volume_ratio", 0.5)), 0.1, key="v822_risk_vr")

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("保存量能规则", type="primary", key="v822_save"):
            save_config(cfg)
            st.success("已保存到 config/custom_rule_volume_v8_2_2.json。")
    with b2:
        if st.button("立即应用量能规则", key="v822_apply"):
            save_config(cfg)
            out, msg = process_volume_rule_snapshot_v8_2_2(globs or {})
            st.success(msg)

    out, msg = process_volume_rule_snapshot_v8_2_2(globs or {})
    if out.empty:
        st.warning(msg)
    else:
        show_cols = [c for c in [
            "代码", "名称", "最新价", "涨跌幅", "换手率", "量比", "成交量_万手", "昨日成交量_万手",
            "成交量较昨日倍数", "成交额_亿", "所属行业", "最强概念", "标准状态", "买卖状态",
            "量能规则类型", "量能规则通过", "量能规则原因"
        ] if c in out.columns]
        st.info(msg)
        st.dataframe(out[show_cols].head(300), hide_index=True, use_container_width=True, height=360)
