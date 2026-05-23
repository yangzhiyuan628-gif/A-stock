"""
数据源模块：所有 AKShare 调用都放在这里。
设计目标：接口失败不影响主程序，字段变化时尽量兼容。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import akshare as ak
import pandas as pd


def _safe_call(name: str, func: Callable, *args, **kwargs) -> pd.DataFrame:
    try:
        df = func(*args, **kwargs)
        if df is None or getattr(df, "empty", True):
            print(f"[WARN] {name} 返回空数据")
            return pd.DataFrame()
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception as exc:
        print(f"[ERROR] {name} 获取失败: {exc}")
        return pd.DataFrame()


def get_spot() -> pd.DataFrame:
    """全市场实时行情。"""
    return _safe_call("全市场实时行情", ak.stock_zh_a_spot_em)


def get_zt_pool(date: str) -> pd.DataFrame:
    """今日涨停池。"""
    return _safe_call("今日涨停池", ak.stock_zt_pool_em, date=date)


def get_zt_pool_previous(date: str) -> pd.DataFrame:
    """昨日涨停池。"""
    return _safe_call("昨日涨停池", ak.stock_zt_pool_previous_em, date=date)


def get_zt_pool_strong(date: str) -> pd.DataFrame:
    """强势股池。"""
    return _safe_call("强势股池", ak.stock_zt_pool_strong_em, date=date)


def get_zt_pool_sub_new(date: str) -> pd.DataFrame:
    """次新股池。"""
    return _safe_call("次新股池", ak.stock_zt_pool_sub_new_em, date=date)


def get_zt_pool_zbgc(date: str) -> pd.DataFrame:
    """炸板股池。"""
    return _safe_call("炸板股池", ak.stock_zt_pool_zbgc_em, date=date)


def get_zt_pool_dtgc(date: str) -> pd.DataFrame:
    """跌停股池。"""
    return _safe_call("跌停股池", ak.stock_zt_pool_dtgc_em, date=date)


def read_watchlist_txt(path: str | Path = "config/watchlist.txt") -> pd.DataFrame:
    """
    读取手工自选股列表。
    支持：
      601991 大唐发电
      601991
      sh601991
      sz000001
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["代码", "自选名称"])

    rows: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"(?<!\d)(\d{6})(?!\d)", line)
        if not m:
            continue
        code = m.group(1)
        name = line.replace(code, "").replace("sh", "").replace("sz", "").strip(" |,，\t")
        rows.append({"代码": code, "自选名称": name})
    return pd.DataFrame(rows).drop_duplicates(subset=["代码"]) if rows else pd.DataFrame(columns=["代码", "自选名称"])


def read_tdx_watchlist(path: str | Path) -> pd.DataFrame:
    """
    尝试读取通达信自选股 .blk 文件。
    常见路径示例：
      C:\\new_tdx\\T0002\\blocknew\\ZXG.blk
      C:\\new_tdx\\T0002\\blocknew\\block_zxg.blk

    不同版本通达信格式可能不同，这里采用宽松正则提取 6 位代码。
    """
    if not path:
        return pd.DataFrame(columns=["代码", "来源"])
    path = Path(path)
    if not path.exists():
        print(f"[WARN] 通达信自选股文件不存在: {path}")
        return pd.DataFrame(columns=["代码", "来源"])

    raw = path.read_bytes()
    text = ""
    for enc in ("gbk", "utf-8", "latin1"):
        try:
            text = raw.decode(enc, errors="ignore")
            if text:
                break
        except Exception:
            pass

    codes = re.findall(r"(?<!\d)(\d{6})(?!\d)", text)
    rows = [{"代码": c, "来源": "通达信"} for c in codes]
    return pd.DataFrame(rows).drop_duplicates(subset=["代码"]) if rows else pd.DataFrame(columns=["代码", "来源"])


def merge_watchlists(txt_path: str | Path = "config/watchlist.txt", tdx_path: Optional[str | Path] = None) -> pd.DataFrame:
    txt_df = read_watchlist_txt(txt_path)
    tdx_df = read_tdx_watchlist(tdx_path) if tdx_path else pd.DataFrame(columns=["代码", "来源"])

    dfs = []
    if not txt_df.empty:
        txt_df = txt_df.copy()
        txt_df["来源"] = "手工"
        dfs.append(txt_df[["代码", "自选名称", "来源"]])
    if not tdx_df.empty:
        tdx_df = tdx_df.copy()
        tdx_df["自选名称"] = ""
        dfs.append(tdx_df[["代码", "自选名称", "来源"]])
    if not dfs:
        return pd.DataFrame(columns=["代码", "自选名称", "来源"])

    out = pd.concat(dfs, ignore_index=True)
    out = out.drop_duplicates(subset=["代码"], keep="first")
    return out
