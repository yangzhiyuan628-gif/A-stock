# -*- coding: utf-8 -*-
"""
v6.2 实盘行情核心模块
- 东方财富直连：强制绕过系统代理
- 通达信 pytdx 备用：当东方财富接口被代理/网络拦截时使用
- 缓存兜底：接口失败时尽量读取上一次成功行情，避免 Streamlit 红屏
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Tuple

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
CONFIG_DIR = ROOT / "config"
REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

CACHE_PATH = REPORT_DIR / "realtime_a_spot_cache.csv"
LAST_SNAPSHOT_PATH = REPORT_DIR / "realtime_last_snapshot.csv"

PROXY_KEYS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]


def force_no_proxy_env() -> None:
    """
    只在当前 Python 进程内关闭代理环境变量。
    不会永久修改系统代理。
    """
    for key in PROXY_KEYS:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = (
        "localhost,127.0.0.1,"
        "eastmoney.com,.eastmoney.com,"
        "push2.eastmoney.com,.push2.eastmoney.com,"
        "82.push2.eastmoney.com,81.push2.eastmoney.com,90.push2.eastmoney.com"
    )


@contextmanager
def no_proxy_context():
    old_env = {k: os.environ.get(k) for k in PROXY_KEYS + ["NO_PROXY", "no_proxy"]}
    force_no_proxy_env()
    try:
        yield
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _request_get_no_proxy(url: str, params: dict, timeout: int = 8) -> requests.Response:
    """
    requests.Session(trust_env=False) 是关键：
    它会忽略 Windows / PowerShell / conda 中的代理环境变量。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "close",
    }
    session = requests.Session()
    session.trust_env = False
    return session.get(
        url,
        params=params,
        timeout=timeout,
        headers=headers,
        proxies={"http": None, "https": None},
        verify=True,
    )


def _to_num(s):
    return pd.to_numeric(s, errors="coerce")


def _standardize_code(code: str) -> str:
    code = str(code).strip()
    if "." in code:
        code = code.split(".")[0]
    return code.zfill(6)[-6:]


def _is_mainboard_code(code: str) -> bool:
    code = _standardize_code(code)
    return code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))


def _is_not_st_name(name: str) -> bool:
    name = str(name)
    bad_tokens = ["ST", "*ST", "退", "退市"]
    return not any(t in name.upper() for t in bad_tokens)


def fetch_eastmoney_spot() -> pd.DataFrame:
    """
    东方财富实时行情直连。
    如果你的代理拦截了 eastmoney，优先用这个函数，因为它会显式绕过代理。
    """
    fields = (
        "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,"
        "f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
    )
    params = {
        "pn": 1,
        "pz": 10000,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        # 沪深京 A 股，后续会过滤成沪深主板非 ST
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": fields,
    }

    urls = [
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://81.push2.eastmoney.com/api/qt/clist/get",
        "https://90.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
        "http://push2.eastmoney.com/api/qt/clist/get",
    ]

    errors = []
    with no_proxy_context():
        for url in urls:
            try:
                r = _request_get_no_proxy(url, params=params, timeout=8)
                r.raise_for_status()
                data = r.json()
                diff = (data.get("data") or {}).get("diff") or []
                if not diff:
                    errors.append(f"{url}: empty diff")
                    continue

                rows = []
                for item in diff:
                    rows.append({
                        "代码": _standardize_code(item.get("f12", "")),
                        "名称": item.get("f14", ""),
                        "最新价": item.get("f2"),
                        "涨跌幅": item.get("f3"),
                        "涨跌额": item.get("f4"),
                        "成交量": item.get("f5"),
                        "成交额": item.get("f6"),
                        "振幅": item.get("f7"),
                        "换手率": item.get("f8"),
                        "最高": item.get("f15"),
                        "最低": item.get("f16"),
                        "今开": item.get("f17"),
                        "昨收": item.get("f18"),
                        "总市值": item.get("f20"),
                        "流通市值": item.get("f21"),
                        "市净率": item.get("f23"),
                        "60日涨跌幅": item.get("f24"),
                        "年初至今涨跌幅": item.get("f25"),
                        "涨速": item.get("f22"),
                        "主力净流入": item.get("f62"),
                        "数据源": "eastmoney",
                    })
                df = pd.DataFrame(rows)
                return clean_numeric(df)
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")

    raise RuntimeError("东方财富直连失败：" + " | ".join(errors[-3:]))


def fetch_pytdx_spot() -> pd.DataFrame:
    """
    通达信行情备用源。
    需要安装：
        pip install pytdx
    注意：pytdx 不一定提供完整市值/换手率，涨速会用缓存快照估算。
    """
    try:
        from pytdx.hq import TdxHq_API
    except Exception as exc:
        raise RuntimeError("未安装 pytdx，请先运行：pip install pytdx") from exc

    servers = [
        ("119.147.212.81", 7709),
        ("47.103.48.45", 7709),
        ("106.14.95.149", 7709),
        ("114.80.63.12", 7709),
        ("180.153.18.170", 7709),
        ("218.75.126.9", 7709),
        ("115.238.56.198", 7709),
    ]

    last_error = None
    for host, port in servers:
        api = TdxHq_API(heartbeat=True, auto_retry=True)
        try:
            if not api.connect(host, port, time_out=6):
                last_error = RuntimeError(f"连接失败 {host}:{port}")
                continue

            securities = []
            # 0 深圳, 1 上海
            for market in [0, 1]:
                count = api.get_security_count(market)
                for start in range(0, count, 1000):
                    part = api.get_security_list(market, start)
                    if part:
                        for x in part:
                            code = _standardize_code(x.get("code", ""))
                            name = str(x.get("name", "")).strip()
                            if _is_mainboard_code(code) and _is_not_st_name(name):
                                securities.append((market, code, name))

            if not securities:
                raise RuntimeError("pytdx 未读取到主板股票列表")

            name_map = {code: name for _, code, name in securities}
            quote_keys = [(market, code) for market, code, _ in securities]
            quote_rows = []
            batch_size = 80

            for i in range(0, len(quote_keys), batch_size):
                batch = quote_keys[i:i + batch_size]
                quotes = api.get_security_quotes(batch)
                if not quotes:
                    continue
                quote_rows.extend(quotes)
                time.sleep(0.02)

            if not quote_rows:
                raise RuntimeError("pytdx 未读取到行情报价")

            df = pd.DataFrame(quote_rows)
            if "code" not in df.columns:
                raise RuntimeError(f"pytdx 返回字段异常：{list(df.columns)}")

            out = pd.DataFrame()
            out["代码"] = df["code"].map(_standardize_code)
            out["名称"] = out["代码"].map(name_map).fillna("")
            out["最新价"] = _to_num(df.get("price"))
            out["昨收"] = _to_num(df.get("last_close"))
            out["今开"] = _to_num(df.get("open"))
            out["最高"] = _to_num(df.get("high"))
            out["最低"] = _to_num(df.get("low"))
            out["成交量"] = _to_num(df.get("vol"))
            out["成交额"] = _to_num(df.get("amount"))
            out["涨跌额"] = out["最新价"] - out["昨收"]
            out["涨跌幅"] = (out["最新价"] / out["昨收"] - 1) * 100
            out["振幅"] = ((out["最高"] - out["最低"]) / out["昨收"]) * 100
            out["换手率"] = None
            out["流通市值"] = None
            out["总市值"] = None
            out["主力净流入"] = None
            out["数据源"] = "pytdx"

            api.disconnect()
            return clean_numeric(out)

        except Exception as exc:
            last_error = exc
            try:
                api.disconnect()
            except Exception:
                pass
            continue

    raise RuntimeError(f"通达信 pytdx 备用源失败：{last_error}")


def fetch_a_spot(source: str = "auto") -> pd.DataFrame:
    """
    source:
    - auto: 先东财，失败后 pytdx，最后缓存
    - eastmoney: 只用东财
    - pytdx: 只用通达信
    - cache: 只读缓存
    """
    errors = []
    source = (source or "auto").lower()

    if source == "cache":
        cached = load_cache()
        if not cached.empty:
            return cached
        raise RuntimeError("没有可用缓存 reports/realtime_a_spot_cache.csv")

    if source in ["auto", "eastmoney"]:
        try:
            df = fetch_eastmoney_spot()
            save_cache(df)
            return df
        except Exception as exc:
            errors.append(str(exc))
            if source == "eastmoney":
                cached = load_cache()
                if not cached.empty:
                    cached["数据源"] = "cache_after_eastmoney_fail"
                    return cached
                raise RuntimeError("实时行情获取失败：" + "；".join(errors))

    if source in ["auto", "pytdx"]:
        try:
            df = fetch_pytdx_spot()
            save_cache(df)
            return df
        except Exception as exc:
            errors.append(str(exc))
            if source == "pytdx":
                cached = load_cache()
                if not cached.empty:
                    cached["数据源"] = "cache_after_pytdx_fail"
                    return cached
                raise RuntimeError("实时行情获取失败：" + "；".join(errors))

    cached = load_cache()
    if not cached.empty:
        cached["数据源"] = "cache_after_all_fail"
        return cached

    raise RuntimeError("实时行情获取失败：" + "；".join(errors))


def clean_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "代码" in df.columns:
        df["代码"] = df["代码"].map(_standardize_code)
    numeric_cols = [
        "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "换手率",
        "最高", "最低", "今开", "昨收", "总市值", "流通市值",
        "市净率", "60日涨跌幅", "年初至今涨跌幅", "涨速", "主力净流入",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = _to_num(df[col])
    return df


def save_cache(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    df.to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")


def load_cache() -> pd.DataFrame:
    if CACHE_PATH.exists():
        try:
            return pd.read_csv(CACHE_PATH, dtype={"代码": str})
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def filter_mainboard_non_st(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["代码"] = df["代码"].map(_standardize_code)
    df["名称"] = df["名称"].astype(str)
    mask = df["代码"].map(_is_mainboard_code) & df["名称"].map(_is_not_st_name)
    return df.loc[mask].reset_index(drop=True)


def add_speed_by_cache(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    now_ts = time.time()

    if "涨速" not in df.columns:
        df["涨速"] = pd.NA

    prev = pd.DataFrame()
    if LAST_SNAPSHOT_PATH.exists():
        try:
            prev = pd.read_csv(LAST_SNAPSHOT_PATH, dtype={"代码": str})
        except Exception:
            prev = pd.DataFrame()

    if not prev.empty and {"代码", "最新价", "_ts"}.issubset(prev.columns):
        prev = prev[["代码", "最新价", "_ts"]].rename(columns={"最新价": "_prev_price", "_ts": "_prev_ts"})
        merged = df.merge(prev, on="代码", how="left")
        dt = (now_ts - _to_num(merged["_prev_ts"])).clip(lower=1)
        speed = ((_to_num(merged["最新价"]) / _to_num(merged["_prev_price"]) - 1) * 100) * (60 / dt)
        df["涨速"] = _to_num(df["涨速"]).fillna(speed).round(2)

    snap = df[["代码", "最新价"]].copy()
    snap["_ts"] = now_ts
    snap.to_csv(LAST_SNAPSHOT_PATH, index=False, encoding="utf-8-sig")
    return df


def add_limit_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["涨停价估算"] = (df["昨收"] * 1.10).round(2)
    df["距涨停幅度"] = ((df["涨停价估算"] / df["最新价"] - 1) * 100).round(2)
    df["是否涨停"] = (df["最新价"] >= df["涨停价估算"] - 0.011) | (df["涨跌幅"] >= 9.85)
    df["接近涨停"] = (~df["是否涨停"]) & (df["涨跌幅"] >= 8.0)
    df["强势异动"] = (df["涨跌幅"] >= 5.0) | (df.get("涨速", 0).fillna(0) >= 1.2)
    return df


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def attach_boards(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    code_to_industry = load_json(CONFIG_DIR / "code_to_industry.json", {})
    code_to_concepts = load_json(CONFIG_DIR / "code_to_concepts.json", {})

    df["行业"] = df["代码"].map(lambda x: code_to_industry.get(str(x).zfill(6), "未知"))
    df["概念"] = df["代码"].map(lambda x: "、".join(code_to_concepts.get(str(x).zfill(6), [])[:5]))

    def main_board(row):
        if row.get("概念"):
            return str(row["概念"]).split("、")[0]
        return row.get("行业", "未知")

    df["主板块"] = df.apply(main_board, axis=1)
    return df


def calc_board_strength(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "主板块" not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    work["成交额"] = _to_num(work.get("成交额", 0)).fillna(0)
    work["涨跌幅"] = _to_num(work.get("涨跌幅", 0)).fillna(0)
    work["涨速"] = _to_num(work.get("涨速", 0)).fillna(0)

    grouped = work.groupby("主板块", dropna=False).agg(
        股票数=("代码", "count"),
        平均涨幅=("涨跌幅", "mean"),
        板块成交额=("成交额", "sum"),
        涨停数=("是否涨停", "sum"),
        接近涨停数=("接近涨停", "sum"),
        强势股数=("强势异动", "sum"),
        平均涨速=("涨速", "mean"),
    ).reset_index()

    grouped["板块联动分"] = (
        grouped["涨停数"] * 30
        + grouped["接近涨停数"] * 15
        + grouped["强势股数"] * 5
        + grouped["平均涨幅"].clip(lower=0) * 2
        + grouped["平均涨速"].clip(lower=0) * 3
        + (grouped["板块成交额"].rank(pct=True).fillna(0) * 10)
    ).round(1)

    return grouped.sort_values("板块联动分", ascending=False)


def attach_board_score(df: pd.DataFrame, board: pd.DataFrame) -> pd.DataFrame:
    if df.empty or board.empty:
        df = df.copy()
        df["板块联动分"] = 0
        return df
    return df.merge(board[["主板块", "板块联动分", "涨停数", "强势股数"]], on="主板块", how="left")


def add_buy_signals(df: pd.DataFrame, min_amount_yi: float = 0.3) -> pd.DataFrame:
    df = df.copy()
    amount = _to_num(df.get("成交额", 0)).fillna(0)
    pct = _to_num(df.get("涨跌幅", 0)).fillna(0)
    speed = _to_num(df.get("涨速", 0)).fillna(0)
    board_score = _to_num(df.get("板块联动分", 0)).fillna(0)

    df["成交额_亿"] = amount / 1e8

    score = (
        pct.clip(lower=0) * 4
        + speed.clip(lower=0) * 8
        + board_score * 0.6
        + df["是否涨停"].astype(int) * 30
        + df["接近涨停"].astype(int) * 15
        + (df["成交额_亿"].rank(pct=True).fillna(0) * 10)
    )
    score -= (df["成交额_亿"] < min_amount_yi).astype(int) * 30
    df["实时信号分"] = score.round(1)

    def signal(row):
        if row["成交额_亿"] < min_amount_yi:
            return "过滤：成交额不足"
        if row.get("是否涨停", False):
            return "打板/排板观察"
        if row.get("接近涨停", False) and row.get("板块联动分", 0) >= 30:
            return "接近涨停观察"
        if 4 <= row.get("涨跌幅", 0) < 8 and row.get("涨速", 0) > 0.5 and row.get("板块联动分", 0) >= 25:
            return "半路启动观察"
        if row.get("涨跌幅", 0) >= 5 and row.get("板块联动分", 0) < 15:
            return "谨慎：孤立拉升"
        if row.get("涨跌幅", 0) >= 3:
            return "低位异动观察"
        return "观察"

    df["实时信号"] = df.apply(signal, axis=1)
    return df.sort_values("实时信号分", ascending=False)


def get_realtime_universe(source: str = "auto", min_amount_yi: float = 0.3) -> Tuple[pd.DataFrame, pd.DataFrame]:
    raw = fetch_a_spot(source=source)
    main = filter_mainboard_non_st(raw)
    main = add_speed_by_cache(main)
    main = add_limit_flags(main)
    main = attach_boards(main)
    board = calc_board_strength(main)
    main = attach_board_score(main, board)
    main = add_buy_signals(main, min_amount_yi=min_amount_yi)
    return main, board
