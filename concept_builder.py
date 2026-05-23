# -*- coding: utf-8 -*-
"""
v6.7 concept_builder.py
东方财富直连版行业/概念映射构建器

解决：
- AKShare 在某些代理/网络环境下请求东方财富会 RemoteDisconnected；
- 旧 concept_builder.py 生成了空的 code_to_industry.json / code_to_concepts.json；
- 这里改用 requests.Session(trust_env=False) 直连东方财富，尽量绕过系统代理。

运行：
    cd D:\csa\git\robote
    python concept_builder.py

生成：
    config\code_to_industry.json
    config\code_to_concepts.json
    config\industry_pct.json
    config\concept_pct.json
    config\board_build_report.json
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
CONFIG_DIR.mkdir(exist_ok=True)

PROXY_KEYS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
]


def disable_proxy_for_process() -> None:
    for k in PROXY_KEYS:
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = (
        "localhost,127.0.0.1,"
        "eastmoney.com,.eastmoney.com,"
        "push2.eastmoney.com,.push2.eastmoney.com,"
        "82.push2.eastmoney.com,81.push2.eastmoney.com,90.push2.eastmoney.com"
    )


def em_get(params: dict, timeout: int = 10) -> dict:
    """
    东方财富 push2 接口直连。
    trust_env=False 是关键：忽略系统/PowerShell 代理变量。
    """
    urls = [
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://81.push2.eastmoney.com/api/qt/clist/get",
        "https://90.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
        "http://push2.eastmoney.com/api/qt/clist/get",
    ]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "close",
    }
    last_error = None
    for url in urls:
        try:
            session = requests.Session()
            session.trust_env = False
            r = session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
                proxies={"http": None, "https": None},
            )
            r.raise_for_status()
            data = r.json()
            if data and data.get("data") is not None:
                return data
            last_error = RuntimeError(f"{url}: empty data")
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"东方财富直连失败: {last_error}")


def norm_code(x) -> str:
    s = str(x).strip()
    if "." in s:
        s = s.split(".")[0]
    return s.zfill(6)[-6:]


def save_json(obj, name: str) -> None:
    path = CONFIG_DIR / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] saved {path} ({len(obj) if hasattr(obj, '__len__') else 'n/a'})")


def fetch_board_list(kind: str) -> pd.DataFrame:
    """
    kind:
      industry: 东方财富行业板块，fs=m:90+t:2+f:!50
      concept : 东方财富概念板块，fs=m:90+t:3+f:!50

    返回列：
      板块代码, 板块名称, 板块涨跌幅
    """
    if kind == "industry":
        fs = "m:90+t:2+f:!50"
    elif kind == "concept":
        fs = "m:90+t:3+f:!50"
    else:
        raise ValueError(kind)

    params = {
        "pn": 1,
        "pz": 5000,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": fs,
        "fields": "f12,f14,f3,f20,f62,f128,f136,f152",
    }
    data = em_get(params)
    diff = (data.get("data") or {}).get("diff") or []
    rows = []
    for item in diff:
        rows.append({
            "板块代码": str(item.get("f12", "")).strip(),
            "板块名称": str(item.get("f14", "")).strip(),
            "板块涨跌幅": item.get("f3"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"{kind} board list empty")
    df["板块涨跌幅"] = pd.to_numeric(df["板块涨跌幅"], errors="coerce")
    return df


def fetch_board_cons(board_code: str) -> pd.DataFrame:
    """
    东方财富板块成分股：
      fs=b:BKxxxx+f:!50
    返回列：
      代码, 名称
    """
    params = {
        "pn": 1,
        "pz": 5000,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": f"b:{board_code}+f:!50",
        "fields": "f12,f14,f3,f2,f6,f8,f20,f21,f152",
    }
    data = em_get(params)
    diff = (data.get("data") or {}).get("diff") or []
    rows = []
    for item in diff:
        code = norm_code(item.get("f12", ""))
        name = str(item.get("f14", "")).strip()
        if code and name:
            rows.append({"代码": code, "名称": name})
    return pd.DataFrame(rows)


def build_mapping(kind: str) -> Tuple[Dict[str, str] | Dict[str, List[str]], Dict[str, float], dict]:
    board_df = fetch_board_list(kind)
    print(f"[INFO] {kind} boards: {len(board_df)}")

    pct_map: Dict[str, float] = {}
    if kind == "industry":
        code_map: Dict[str, str] = {}
    else:
        code_map: Dict[str, List[str]] = {}

    success = 0
    failed = 0

    for i, row in board_df.iterrows():
        board_code = str(row["板块代码"]).strip()
        board_name = str(row["板块名称"]).strip()
        pct = row.get("板块涨跌幅")

        if not board_code or not board_name:
            continue

        if pd.notna(pct):
            try:
                pct_map[board_name] = float(pct)
            except Exception:
                pass

        print(f"[{kind.upper()}] {i+1}/{len(board_df)} {board_code} {board_name}")

        try:
            cons = fetch_board_cons(board_code)
            if cons.empty:
                failed += 1
                print(f"  [WARN] empty constituents")
                continue

            if kind == "industry":
                for code in cons["代码"].astype(str):
                    code_map[norm_code(code)] = board_name
            else:
                for code in cons["代码"].astype(str):
                    c = norm_code(code)
                    code_map.setdefault(c, [])
                    if board_name not in code_map[c]:
                        code_map[c].append(board_name)
            success += 1
            time.sleep(0.05)
        except Exception as exc:
            failed += 1
            print(f"  [WARN] failed: {exc}")
            time.sleep(0.1)

    if kind == "concept":
        for code in list(code_map.keys()):
            code_map[code] = code_map[code][:40]

    report = {
        "kind": kind,
        "board_count": int(len(board_df)),
        "success_boards": int(success),
        "failed_boards": int(failed),
        "mapped_codes": int(len(code_map)),
    }
    return code_map, pct_map, report


def main():
    disable_proxy_for_process()
    report = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": "eastmoney_direct_no_proxy",
    }

    print("[START] build industry/concept mapping by EastMoney direct API")

    industry_map = {}
    industry_pct = {}
    try:
        industry_map, industry_pct, rep = build_mapping("industry")
        report["industry"] = rep
    except Exception as exc:
        print(f"[ERROR] industry build failed: {exc}")
        report["industry_error"] = str(exc)

    concept_map = {}
    concept_pct = {}
    try:
        concept_map, concept_pct, rep = build_mapping("concept")
        report["concept"] = rep
    except Exception as exc:
        print(f"[ERROR] concept build failed: {exc}")
        report["concept_error"] = str(exc)

    save_json(industry_map, "code_to_industry.json")
    save_json(concept_map, "code_to_concepts.json")
    save_json(industry_pct, "industry_pct.json")
    save_json(concept_pct, "concept_pct.json")
    save_json(report, "board_build_report.json")

    print("[DONE]")
    print(f"industry mapped codes: {len(industry_map)}")
    print(f"concept mapped codes: {len(concept_map)}")
    print("Now restart streamlit_realtime.py")


if __name__ == "__main__":
    main()
