# -*- coding: utf-8 -*-
"""
watch_ai_chat_v7_7.py

把 8502 的“大模型问股”Tab 改成类似 8501 机器人那种聊天方式：
- 无分析师勾选；
- 只有聊天窗口；
- 支持上传 PDF；
- 支持导入网页/本地网址；
- 支持读取当前盯盘股票池；
- 支持本地/联网搜索。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

try:
    from watch_pdf_kb_v7_7 import (
        init_db as init_pdf_kb,
        add_pdf_bytes,
        add_text_document,
        list_documents,
        kb_context,
    )
except Exception:
    init_pdf_kb = add_pdf_bytes = add_text_document = list_documents = kb_context = None

try:
    from watch_web_researcher_v7_7 import fetch_url_text, search_web_context
except Exception:
    fetch_url_text = search_web_context = None


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"

CODE_COLS = ["代码", "股票代码", "证券代码", "A股代码", "stock_code", "code", "symbol", "ts_code"]
NAME_COLS = ["名称", "股票名称", "证券简称", "股票简称", "简称", "name", "stock_name", "security_name"]


def load_project_env() -> None:
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


def _norm_code(x: Any) -> str:
    s = str(x).strip()
    d = "".join(re.findall(r"\d", s))
    return d[-6:] if len(d) >= 6 else (d.zfill(6) if d else "")


def _find_col(df: pd.DataFrame, names: list[str]):
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


def _read_csv(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030"]:
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except Exception:
            pass
    try:
        return pd.read_csv(path, dtype=str)
    except Exception:
        return pd.DataFrame()


def _to_numeric_unit(v):
    if pd.isna(v):
        return pd.NA
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    s = s.replace("－", "-").replace("—", "-")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return pd.NA
    try:
        x = float(m.group(0))
    except Exception:
        return pd.NA
    if "万" in s:
        return x / 10000
    if "亿" in s:
        return x
    if "元" in s:
        return x / 1e8
    return x


def _std(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()

    x = df.copy()
    x.columns = [str(c).strip() for c in x.columns]
    cc = _find_col(x, CODE_COLS)
    nc = _find_col(x, NAME_COLS)

    if cc is None and len(x.columns) > 0:
        c0 = x.columns[0]
        if any(re.search(r"\d{6}", s) for s in x[c0].dropna().astype(str).head(30)):
            cc = c0

    if cc is None:
        return pd.DataFrame()

    x["代码"] = x[cc].map(_norm_code)
    x = x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    if x.empty:
        return pd.DataFrame()

    if nc is not None:
        x["名称"] = x[nc].astype(str)
    elif "名称" not in x.columns:
        x["名称"] = x["代码"]

    ren = {}
    if "涨幅" in x.columns and "涨跌幅" not in x.columns:
        ren["涨幅"] = "涨跌幅"
    if "现价" in x.columns and "最新价" not in x.columns:
        ren["现价"] = "最新价"
    if ren:
        x = x.rename(columns=ren)

    for col in list(x.columns):
        name = str(col)
        if any(k in name for k in ["涨跌幅", "涨幅", "涨速", "换手率", "行业涨幅", "概念涨幅", "距涨停幅度"]):
            x[col] = x[col].map(_to_numeric_unit)
        elif any(k in name for k in ["成交额", "市值", "封板资金", "净流入"]) and "成交量" not in name:
            x[col] = x[col].map(_to_numeric_unit)

    if "成交额_亿" not in x.columns and "成交额" in x.columns:
        x["成交额_亿"] = x["成交额"]

    x["来源文件"] = source
    return x


def _scan_report_files() -> tuple[list[pd.DataFrame], list[dict]]:
    dfs = []
    dbg = []

    paths = []
    for name in ["latest_watch_signals.csv", "latest_industry_board.csv", "latest_concept_board.csv"]:
        p = REPORT_DIR / name
        if p.exists():
            paths.append(p)

    for folder in [REPORT_DIR, ROOT]:
        if folder.exists():
            for p in folder.glob("*.csv"):
                if p not in paths:
                    paths.append(p)

    seen = set()
    for p in paths:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)

        raw = _read_csv(p)
        rel = str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
        std = _std(raw, rel)
        dbg.append({
            "文件": rel,
            "行数": len(raw),
            "列名": ", ".join(map(str, raw.columns[:18])) if not raw.empty else "",
            "识别股票池": not std.empty,
            "识别股票数": len(std),
        })
        if not std.empty:
            dfs.append(std)

    return dfs, dbg


def _merge_data(data_candidates=None) -> tuple[pd.DataFrame, list[dict]]:
    dfs = []
    dbg = []

    for i, obj in enumerate(data_candidates or []):
        if isinstance(obj, pd.DataFrame) and not obj.empty:
            s = _std(obj, f"页面变量_{i}")
            if not s.empty:
                dfs.append(s)
                dbg.append({
                    "文件": f"页面变量_{i}",
                    "行数": len(obj),
                    "列名": ", ".join(map(str, obj.columns[:18])),
                    "识别股票池": True,
                    "识别股票数": len(s),
                })

    fdfs, fdbg = _scan_report_files()
    dfs += fdfs
    dbg += fdbg

    if not dfs:
        return pd.DataFrame(), dbg

    m = pd.concat(dfs, ignore_index=True)
    m["代码"] = m["代码"].map(_norm_code)
    m = m[m["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    m["_nn"] = m.notna().sum(axis=1)
    m = m.sort_values("_nn", ascending=False).drop_duplicates("代码", keep="first").drop(columns=["_nn"], errors="ignore")
    return m, dbg


def _score(df: pd.DataFrame, mode: str = "general") -> pd.Series:
    score = pd.Series(0.0, index=df.index)
    pct = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0) if "涨跌幅" in df.columns else pd.Series(0, index=df.index)
    speed_col = "规则涨速" if "规则涨速" in df.columns else ("涨速" if "涨速" in df.columns else None)
    speed = pd.to_numeric(df[speed_col], errors="coerce").fillna(0) if speed_col else pd.Series(0, index=df.index)
    amount = pd.to_numeric(df["成交额_亿"], errors="coerce").fillna(0) if "成交额_亿" in df.columns else pd.Series(0, index=df.index)

    score += pct.clip(lower=0) * 12 + speed.clip(lower=0) * 18 + amount.clip(upper=30) * 2

    for c, w in [("行业涨幅", 12), ("概念涨幅", 12), ("个股板块联动分", 1)]:
        if c in df.columns:
            score += pd.to_numeric(df[c], errors="coerce").fillna(0).clip(lower=0) * w

    if "买卖状态" in df.columns:
        s = df["买卖状态"].astype(str)
        score += s.str.contains("打板|排板|接近涨停", regex=True).astype(int) * 70
        score += s.str.contains("半路|低位异动|买点", regex=True).astype(int) * 45
        score -= s.str.contains("孤立|风险|卖出|回避", regex=True).astype(int) * 80

    if mode == "tomorrow":
        score += ((pct >= 2) & (pct <= 7)).astype(int) * 80
        score -= (pct >= 9).astype(int) * 60

    return score


def _is_tomorrow(q: str) -> bool:
    return any(w in q for w in ["明日首板", "明天首板", "明日一板", "明天一板", "次日首板"])


def _find_stock(q: str, df: pd.DataFrame):
    m = re.search(r"(?<!\d)(\d{6})(?!\d)", q)
    if m:
        hit = df[df["代码"].astype(str).str.zfill(6).eq(m.group(1))]
        if not hit.empty:
            return hit.iloc[0]

    if "名称" in df.columns:
        for name in df["名称"].dropna().astype(str).unique():
            if name and name in q:
                hit = df[df["名称"].astype(str).eq(name)]
                if not hit.empty:
                    return hit.iloc[0]

    for part in re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", q):
        if "名称" in df.columns:
            hit = df[df["名称"].astype(str).str.contains(part, regex=False, na=False)]
            if not hit.empty:
                return hit.iloc[0]

    return None


def _row_context(row: pd.Series) -> str:
    fields = [
        "代码", "名称", "最新价", "涨跌幅", "涨速", "规则涨速", "5分钟涨速",
        "成交额_亿", "换手率", "所属行业", "行业涨幅", "最强概念", "概念涨幅",
        "所属概念", "买卖状态", "操作提示", "个股板块联动分", "距涨停幅度",
        "是否涨停", "接近涨停", "来源文件",
    ]
    return "\n".join(f"{f}: {row.get(f)}" for f in fields if f in row.index)


def _pool_context(df: pd.DataFrame, q: str, limit: int = 35) -> str:
    if df.empty:
        return "候选池为空。"

    mode = "tomorrow" if _is_tomorrow(q) else "general"
    tmp = df.copy()
    tmp["_ai_score"] = _score(tmp, mode=mode)
    tmp = tmp.sort_values("_ai_score", ascending=False, na_position="last").head(limit)

    cols = [c for c in [
        "代码", "名称", "最新价", "涨跌幅", "规则涨速", "涨速", "成交额_亿",
        "所属行业", "最强概念", "买卖状态", "个股板块联动分", "_ai_score",
    ] if c in tmp.columns]

    lines = [f"候选池模式: {'明日首板候选' if mode == 'tomorrow' else '盯盘问股候选'}"]
    for _, r in tmp[cols].iterrows():
        lines.append(" | ".join(f"{c}:{r.get(c)}" for c in cols))
    return "\n".join(lines)


def _market_context(df: pd.DataFrame) -> str:
    if df.empty:
        return "股票池为空。"

    lines = [f"股票池样本数: {len(df)}"]

    if "涨跌幅" in df.columns:
        p = pd.to_numeric(df["涨跌幅"], errors="coerce")
        lines += [
            f"平均涨幅: {p.mean():.2f}%",
            f"涨幅>7%数量: {int((p > 7).sum())}",
            f"涨幅>3%数量: {int((p > 3).sum())}",
        ]

    for c in ["所属行业", "最强概念"]:
        if c in df.columns and "涨跌幅" in df.columns:
            try:
                g = (
                    df[df[c].astype(str).str.len() > 0]
                    .groupby(c)["涨跌幅"]
                    .agg(["count", "mean"])
                    .sort_values(["mean", "count"], ascending=False)
                    .head(8)
                )
                if not g.empty:
                    lines.append(("行业" if c == "所属行业" else "概念") + "强度Top:")
                    for name, r in g.iterrows():
                        lines.append(f"- {name}: 数量{int(r['count'])}, 平均涨幅{r['mean']:.2f}%")
            except Exception:
                pass

    return "\n".join(lines)


def _api_config():
    load_project_env()

    key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("AI_API_KEY")
        or ""
    )
    base = (os.getenv("AI_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = os.getenv("AI_MODEL") or os.getenv("DEFAULT_AI_MODEL") or "deepseek-chat"

    try:
        if st.session_state.get("watch_ai_api_key"):
            key = st.session_state["watch_ai_api_key"]
        if st.session_state.get("watch_ai_base_url"):
            base = st.session_state["watch_ai_base_url"].rstrip("/")
        if st.session_state.get("watch_ai_model"):
            model = st.session_state["watch_ai_model"]
    except Exception:
        pass

    return key, base, model


def _ask_model(q: str, market_text: str, stock_text: str, kb_text: str, web_text: str) -> tuple[bool, str]:
    key, base, model = _api_config()
    if not key:
        return False, "没有读取到 API Key。请在 .env 设置 DEEPSEEK_API_KEY，或在 API 设置里临时填入。"

    system = """你是8502实盘盯盘系统里的短线问股机器人。你不负责自动下单，只做盯盘、解释、买点推演和风险提示。
分析风格：短线、首板、半路、回封、打板、题材情绪、板块联动、涨速、成交额、新闻和基本面催化。
你必须优先使用用户上传的PDF/网页资料、本地知识库、搜索结果和当前盯盘股票池。
不要使用分析师勾选模式；你需要直接以聊天方式回答。
如果资料显示公司业务发生变化，要修正旧认知。例如不能只按传统主营看，要结合公告/新闻/PDF识别算力租赁、AI、智算、重组、订单等新题材。
输出结构：
1. 当前结论：可以激进试错/可以轻仓试错/只适合半路观察/只适合打板或回封确认/等回踩确认/暂不出手/风险偏高回避
2. 题材与新闻/资料依据
3. 当前盯盘信号：涨幅、涨速、成交额、板块联动、买卖状态
4. 买点设计：激进买点、稳健买点、打板/回封确认点
5. 失效条件和止损逻辑
6. 明日预期或后续观察点
不得承诺收益；不得建议重仓、融资或借钱；不得编造新闻、公告、财务、龙虎榜或盘口。"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"【用户问题】\n{q}\n\n"
                    f"【市场情绪/板块强度】\n{market_text}\n\n"
                    f"【盯盘股票池/目标个股】\n{stock_text}\n\n"
                    f"【PDF/网页资料库检索】\n{kb_text}\n\n"
                    f"【联网/本地搜索上下文】\n{web_text}"
                ),
            },
        ],
        "temperature": 0.35,
        "max_tokens": 3200,
    }

    try:
        r = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=100,
        )
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return False, f"大模型调用失败：{type(exc).__name__}: {exc}"


def _render_knowledge_panel():
    if init_pdf_kb is None:
        st.info("未加载 watch_pdf_kb_v7_7.py，PDF/网页资料库不可用。")
        return

    init_pdf_kb()

    with st.expander("PDF / 网页资料库 / 搜索设置", expanded=False):
        st.caption("上传 PDF 或导入网页后，问股时会自动检索相关片段。扫描版 PDF 不做 OCR。")

        uploaded = st.file_uploader(
            "上传 PDF 供问股检索",
            type=["pdf"],
            accept_multiple_files=True,
            key="watch_ai_pdf_uploader_v77",
        )

        if st.button("导入上传的 PDF", key="watch_ai_import_pdf_v77"):
            if not uploaded:
                st.warning("请先选择 PDF。")
            else:
                for f in uploaded:
                    ok, msg = add_pdf_bytes(f.name, f.getvalue())
                    st.write(("✅ " if ok else "❌ ") + msg)

        urls = st.text_area(
            "导入网页/本地网址，每行一个",
            placeholder="https://example.com/news\nhttp://127.0.0.1:8000/article/xxx",
            height=90,
            key="watch_ai_urls_v77",
        )

        if st.button("抓取并导入网页", key="watch_ai_import_url_v77"):
            if not urls.strip():
                st.warning("请先输入 URL。")
            elif fetch_url_text is None:
                st.error("未加载 watch_web_researcher_v7_7.py。")
            else:
                for url in [u.strip() for u in urls.splitlines() if u.strip()]:
                    ok, title, text = fetch_url_text(url)
                    if ok:
                        ok2, msg = add_text_document(title=title, text=text, source_type="url", source_path=url)
                        st.write(("✅ " if ok2 else "❌ ") + msg)
                    else:
                        st.write(f"❌ {url}: {text}")

        c1, c2 = st.columns(2)
        with c1:
            st.session_state["watch_ai_use_kb"] = st.checkbox(
                "回答时检索 PDF/网页资料库",
                value=st.session_state.get("watch_ai_use_kb", True),
                key="watch_ai_use_kb_checkbox_v77",
            )
        with c2:
            default_web = bool(os.getenv("LOCAL_SEARCH_ENDPOINT") or os.getenv("TAVILY_API_KEY"))
            st.session_state["watch_ai_use_web"] = st.checkbox(
                "回答时允许联网/本地搜索",
                value=st.session_state.get("watch_ai_use_web", default_web),
                key="watch_ai_use_web_checkbox_v77",
            )

        docs = list_documents() if list_documents else []
        if docs:
            show = pd.DataFrame(docs)
            cols = [c for c in ["title", "source_type", "source_path", "chunk_count", "created_at"] if c in show.columns]
            st.markdown("**已导入资料**")
            st.dataframe(show[cols], hide_index=True, use_container_width=True, height=180)


def _render_api_panel():
    with st.expander("API 设置", expanded=False):
        load_project_env()
        c1, c2, c3 = st.columns([1.2, 1, 1.4])
        with c1:
            st.text_input(
                "Base URL",
                value=st.session_state.get("watch_ai_base_url", os.getenv("AI_BASE_URL", "https://api.deepseek.com")),
                key="watch_ai_base_url",
            )
        with c2:
            st.text_input(
                "模型",
                value=st.session_state.get("watch_ai_model", os.getenv("AI_MODEL", "deepseek-chat")),
                key="watch_ai_model",
            )
        with c3:
            st.text_input(
                "API Key",
                value=st.session_state.get("watch_ai_api_key", ""),
                type="password",
                key="watch_ai_api_key",
                placeholder="可留空，优先读取 .env",
            )


def render_watch_ai_chat_v7_7(data_candidates=None, market_context=None):
    st.subheader("💡 大模型问股")
    st.caption("参考 8501 机器人对话方式：不再使用分析师勾选，只保留聊天窗口；支持 PDF、网页资料库、搜索和当前盯盘股票池。")

    df, debug = _merge_data(data_candidates)

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("➕ 新对话", use_container_width=True, key="watch_ai_new_chat_v77"):
            st.session_state["watch_ai_messages_v77"] = []
            st.rerun()
    with c2:
        export = "\n\n".join(
            [f"{m['role']}: {m['content']}" for m in st.session_state.get("watch_ai_messages_v77", [])]
        )
        st.download_button(
            "⬇ 导出会话",
            data=export,
            file_name="watch_ai_chat.md",
            mime="text/markdown",
            use_container_width=True,
            key="watch_ai_export_v77",
        )
    with c3:
        if st.button("清空", use_container_width=True, key="watch_ai_clear_v77"):
            st.session_state["watch_ai_messages_v77"] = []
            st.rerun()

    _render_api_panel()
    _render_knowledge_panel()

    if df.empty:
        st.warning("当前未识别到盯盘股票池。系统会尝试读取 reports/latest_watch_signals.csv；若仍为空，请先刷新行情。")
        with st.expander("数据扫描诊断", expanded=False):
            st.dataframe(pd.DataFrame(debug), hide_index=True, use_container_width=True)
    else:
        st.success(f"已识别盯盘股票池：{len(df)} 只。问股时会自动读取当前涨幅、涨速、成交额、行业/概念和买卖状态。")
        with st.expander("当前问股候选 Top 30", expanded=False):
            show = df.copy()
            show["_ai_score"] = _score(show)
            show = show.sort_values("_ai_score", ascending=False, na_position="last").head(30)
            cols = [c for c in [
                "代码", "名称", "最新价", "涨跌幅", "规则涨速", "涨速", "成交额_亿",
                "所属行业", "最强概念", "买卖状态", "个股板块联动分", "_ai_score"
            ] if c in show.columns]
            st.dataframe(show[cols], hide_index=True, use_container_width=True, height=260)

    if "watch_ai_messages_v77" not in st.session_state:
        st.session_state["watch_ai_messages_v77"] = []

    chat_box = st.container(height=520)
    with chat_box:
        if not st.session_state["watch_ai_messages_v77"]:
            st.info("示例：分析莲花控股，结合PDF资料和新闻看是不是算力租赁题材；推荐一支当前符合半路买点的股票。")
        for msg in st.session_state["watch_ai_messages_v77"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    q = st.chat_input(
        "例如：分析600519；莲花控股现在能不能出手；推荐一支当前符合半路买点的股票。",
        key="watch_ai_chat_input_v77",
    )

    if not q:
        return

    st.session_state["watch_ai_messages_v77"].append({"role": "user", "content": q})

    row = _find_stock(q, df)
    if row is not None:
        stock_text = "【目标个股】\n" + _row_context(row) + "\n\n【候选池参考】\n" + _pool_context(df, q, limit=25)
        search_query = f"{row.get('名称', '')} {row.get('代码', '')} {q}"
    else:
        stock_text = "【开放候选池】\n" + _pool_context(df, q, limit=40)
        search_query = q

    market_text = _market_context(df)

    if st.session_state.get("watch_ai_use_kb", True) and kb_context is not None:
        kb_text = kb_context(search_query, top_k=8)
    else:
        kb_text = "本次未启用 PDF/网页资料库检索。"

    if st.session_state.get("watch_ai_use_web", False) and search_web_context is not None:
        web_text = search_web_context(search_query, limit=6)
    else:
        web_text = "本次未启用联网/本地搜索。"

    with st.spinner("大模型正在结合盯盘数据、PDF资料和搜索信息分析..."):
        ok, ans = _ask_model(q, market_text, stock_text, kb_text, web_text)

    if not ok:
        ans = "❌ " + ans

    st.session_state["watch_ai_messages_v77"].append({"role": "assistant", "content": ans})
    st.rerun()
