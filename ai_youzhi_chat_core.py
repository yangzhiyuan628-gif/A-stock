# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re
from pathlib import Path
from typing import Any
import pandas as pd
import requests
import streamlit as st

try:
    from strategy_kb import init_db, list_strategies, search_strategies, strategies_to_context, add_strategy
except Exception:
    init_db = list_strategies = search_strategies = strategies_to_context = add_strategy = None

try:
    from company_kb import init_db as init_company_db, add_or_update_company
except Exception:
    init_company_db = add_or_update_company = None

try:
    from fundamental_news_fetcher import fetch_fundamental_news_context, fetch_market_news_context
except Exception:
    fetch_fundamental_news_context = fetch_market_news_context = None

try:
    from pdf_kb import init_db as init_pdf_kb, add_pdf_bytes, add_text_document, list_documents, kb_context
except Exception:
    init_pdf_kb = add_pdf_bytes = add_text_document = list_documents = kb_context = None

try:
    from web_researcher import fetch_url_text, search_web_context
except Exception:
    fetch_url_text = search_web_context = None

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
CODE_COLS = ["代码","股票代码","证券代码","A股代码","stock_code","code","symbol","ts_code"]
NAME_COLS = ["名称","股票名称","证券简称","股票简称","简称","name","stock_name","security_name"]

def load_project_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k,v=line.split("=",1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def _norm_code(x):
    s=str(x).strip()
    if not s or s.lower()=="nan":
        return ""
    d="".join(re.findall(r"\d", s))
    return d[-6:] if len(d)>=6 else (d.zfill(6) if d else "")

def _find_col(df, names):
    lower={str(c).lower().strip(): c for c in df.columns}
    for n in names:
        if n in df.columns: return n
        if n.lower() in lower: return lower[n.lower()]
    for c in df.columns:
        cs=str(c).lower()
        for n in names:
            if n.lower() in cs: return c
    return None

def _read_csv(path):
    for enc in ["utf-8-sig","utf-8","gbk","gb18030"]:
        try: return pd.read_csv(path, dtype=str, encoding=enc)
        except Exception: pass
    try: return pd.read_csv(path, dtype=str)
    except Exception: return pd.DataFrame()

def _std(df, source=""):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    x=df.copy()
    x.columns=[str(c).strip() for c in x.columns]
    cc=_find_col(x, CODE_COLS)
    nc=_find_col(x, NAME_COLS)
    if cc is None and len(x.columns)>0:
        c0=x.columns[0]
        if any(re.search(r"\d{6}", s) for s in x[c0].dropna().astype(str).head(30)):
            cc=c0
    if cc is None:
        return pd.DataFrame()
    x["代码"]=x[cc].map(_norm_code)
    x=x[x["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    if x.empty: return pd.DataFrame()
    x["名称"]=x[nc].astype(str) if nc is not None else x.get("名称", x["代码"]).astype(str)
    ren={}
    if "涨幅" in x.columns and "涨跌幅" not in x.columns: ren["涨幅"]="涨跌幅"
    if "现价" in x.columns and "最新价" not in x.columns: ren["现价"]="最新价"
    if "收盘价" in x.columns and "最新价" not in x.columns: ren["收盘价"]="最新价"
    if ren: x=x.rename(columns=ren)
    for col in ["最新价","涨跌幅","涨速","规则涨速","涨速5分钟","成交额","成交额_亿","换手率","连板数","行业涨幅","概念涨幅","个股板块联动分","行业强势数","行业涨停数","概念强势数","概念涨停数","距涨停幅度"]:
        if col in x.columns: x[col]=pd.to_numeric(x[col].astype(str).str.replace("%","",regex=False), errors="coerce")
    if "成交额_亿" not in x.columns and "成交额" in x.columns:
        a=pd.to_numeric(x["成交额"], errors="coerce")
        med=a.dropna().median() if not a.dropna().empty else 0
        x["成交额_亿"]=a/1e8 if med>10000 else a
    x["来源文件"]=source
    return x

def _scan_files():
    dfs=[]; dbg=[]; seen=set()
    for folder in [REPORT_DIR, DATA_DIR, ROOT]:
        if not folder.exists(): continue
        for p in folder.glob("*.csv"):
            rp=p.resolve()
            if rp in seen: continue
            seen.add(rp)
            raw=_read_csv(p)
            rel=str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
            std=_std(raw, rel)
            dbg.append({"文件":rel, "行数":len(raw), "列名":", ".join(map(str, raw.columns[:20])) if not raw.empty else "", "识别为股票池":not std.empty, "识别股票数":len(std)})
            if not std.empty: dfs.append(std)
    return dfs, dbg

def _merge(data_candidates=None):
    dfs=[]; dbg=[]
    for i,obj in enumerate(data_candidates or []):
        if isinstance(obj, pd.DataFrame) and not obj.empty:
            s=_std(obj, f"页面变量_{i}")
            if not s.empty:
                dfs.append(s); dbg.append({"文件":f"页面变量_{i}","行数":len(obj),"列名":", ".join(map(str,obj.columns[:20])),"识别为股票池":True,"识别股票数":len(s)})
    fdfs,fdbg=_scan_files(); dfs+=fdfs; dbg+=fdbg
    if not dfs: return pd.DataFrame(), dbg
    m=pd.concat(dfs, ignore_index=True)
    m["代码"]=m["代码"].map(_norm_code)
    m=m[m["代码"].astype(str).str.match(r"^\d{6}$", na=False)].copy()
    m["_nn"]=m.notna().sum(axis=1)
    m=m.sort_values("_nn", ascending=False).drop_duplicates("代码", keep="first").drop(columns=["_nn"], errors="ignore")
    return m, dbg

def _score(df, mode="general"):
    score=pd.Series(0.0, index=df.index)
    pct=pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0) if "涨跌幅" in df.columns else pd.Series(0,index=df.index)
    sp=pd.to_numeric(df["规则涨速"] if "规则涨速" in df.columns else df["涨速"], errors="coerce").fillna(0) if ("规则涨速" in df.columns or "涨速" in df.columns) else pd.Series(0,index=df.index)
    amt=pd.to_numeric(df["成交额_亿"], errors="coerce").fillna(0) if "成交额_亿" in df.columns else pd.Series(0,index=df.index)
    score += pct.clip(lower=0)*12 + sp.clip(lower=0)*12 + amt.clip(upper=30)*2
    if "个股板块联动分" in df.columns: score += pd.to_numeric(df["个股板块联动分"], errors="coerce").fillna(0)
    for c,w in [("行业强势数",4),("概念强势数",4),("行业涨停数",10),("概念涨停数",10)]:
        if c in df.columns: score += pd.to_numeric(df[c], errors="coerce").fillna(0)*w
    if "买卖状态" in df.columns:
        s=df["买卖状态"].astype(str)
        score += s.str.contains("打板|排板|接近涨停", regex=True).astype(int)*70
        score += s.str.contains("半路|低位异动", regex=True).astype(int)*45
        score -= s.str.contains("孤立|风险|卖出|回避", regex=True).astype(int)*80
    if mode=="tomorrow":
        score += ((pct>=2)&(pct<=7)).astype(int)*80
        score -= (pct>=9).astype(int)*60
        if "是否涨停" in df.columns: score -= df["是否涨停"].fillna(False).astype(bool).astype(int)*30
        if "连板数" in df.columns: score -= (pd.to_numeric(df["连板数"], errors="coerce").fillna(0)>=1).astype(int)*40
    return score

def _is_tomorrow(q):
    return any(w in q for w in ["明日首板","明天首板","明日一板","明天一板","次日首板"])

def _find_stock(q, df):
    m=re.search(r"(?<!\d)(\d{6})(?!\d)", q)
    if m:
        hit=df[df["代码"].astype(str).str.zfill(6).eq(m.group(1))]
        if not hit.empty: return hit.iloc[0]
    for name in df.get("名称", pd.Series(dtype=str)).dropna().astype(str):
        if name and name in q:
            hit=df[df["名称"].astype(str).eq(name)]
            if not hit.empty: return hit.iloc[0]
    for part in re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", q):
        hit=df[df.get("名称", pd.Series(dtype=str)).astype(str).str.contains(part, regex=False, na=False)]
        if not hit.empty: return hit.iloc[0]
    return None

def _market(df):
    if df.empty: return "股票池为空。"
    lines=[f"股票池样本数: {len(df)}"]
    if "涨跌幅" in df.columns:
        p=pd.to_numeric(df["涨跌幅"], errors="coerce")
        lines += [f"平均涨幅: {p.mean():.2f}%", f"涨幅>7%数量: {int((p>7).sum())}", f"涨幅>3%数量: {int((p>3).sum())}"]
    for c in ["所属行业","最强概念"]:
        if c in df.columns and "涨跌幅" in df.columns:
            try:
                g=df[df[c].astype(str).str.len()>0].groupby(c)["涨跌幅"].agg(["count","mean"]).sort_values(["mean","count"], ascending=False).head(8)
                if not g.empty:
                    lines.append(("行业" if c=="所属行业" else "概念")+"强度Top:")
                    for name,r in g.iterrows(): lines.append(f"- {name}: 数量{int(r['count'])}, 平均涨幅{r['mean']:.2f}%")
            except Exception: pass
    return "\n".join(lines)

def _row(row):
    fields=["代码","名称","最新价","涨跌幅","涨速","规则涨速","涨速5分钟","成交额_亿","换手率","连板数","所属行业","行业涨幅","最强概念","概念涨幅","所属概念","行业强势数","行业涨停数","概念强势数","概念涨停数","买卖状态","操作提示","个股板块联动分","距涨停幅度","是否涨停","接近涨停","来源文件"]
    return "\n".join(f"{f}: {row.get(f)}" for f in fields if f in row.index)

def _pool(df, q, limit=40):
    if df.empty: return "候选池为空。"
    mode="tomorrow" if _is_tomorrow(q) else "general"
    tmp=df.copy(); tmp["_ai_score"]=_score(tmp, mode)
    tmp=tmp.sort_values("_ai_score", ascending=False, na_position="last").head(limit)
    cols=[c for c in ["代码","名称","最新价","涨跌幅","涨速","规则涨速","成交额_亿","所属行业","最强概念","买卖状态","个股板块联动分","来源文件","_ai_score"] if c in tmp.columns]
    lines=[f"候选池模式: {'明日首板候选' if mode=='tomorrow' else '通用短线候选'}"]
    for _,r in tmp[cols].iterrows():
        lines.append(" | ".join(f"{c}:{r.get(c)}" for c in cols))
    return "\n".join(lines)

def _api():
    load_project_env()
    key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY") or ""
    try:
        for k,v in st.session_state.items():
            if not key and "api" in str(k).lower() and "key" in str(k).lower() and isinstance(v,str) and len(v)>10:
                key=v
    except Exception: pass
    return key, (os.getenv("AI_BASE_URL") or "https://api.deepseek.com").rstrip("/"), os.getenv("AI_MODEL") or os.getenv("DEFAULT_AI_MODEL") or "deepseek-chat"

def _ask(q, context, strategy, fundamental_text, kb_text, web_text):
    key, base, model = _api()
    if not key: return False, "没有读取到 API Key。请在 .env 设置 DEEPSEEK_API_KEY，或在左侧 API Key 输入框填入。"
    system = """你是短线打板机器人，但你必须先读公司基本面、主营变化、新闻公告、PDF资料库和网页检索信息。不要参考龙虎榜，不要编造席位。短线逻辑：先看市场情绪和题材新闻，再看公司真实业务/转型方向，再看板块联动和个股地位，最后看买点。你可以分析指定个股，也可以基于候选池主动推荐明日首板/首板/半路/打板方向。若资料库或网页显示公司业务发生变化，必须优先修正自己的旧认知。比如莲花控股不能只按调味品理解，还要核验其算力租赁/智算中心/AI算力属性。输出必须包含：A新闻与题材催化；B公司基本面与业务变化；C本地PDF/网页资料依据；D候选/个股地位与板块联动；E战法库匹配；F买入点位：激进买点、稳健买点、打板/回封确认点、止损/失效点；G现在是否可以出手。结论只能选：可以激进试错/可以轻仓试错/只适合半路观察/只适合打板或回封确认/等回踩确认/暂不出手/风险偏高回避。不得承诺收益；不得建议重仓、融资或借钱；不得编造新闻、公告、财务、龙虎榜或Level-2盘口。"""
    payload={"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":f"【用户问题】\n{q}\n\n【战法库】\n{strategy}\n\n【公司基本面/新闻/公告上下文】\n{fundamental_text}\n\n【本地PDF/网页知识库检索】\n{kb_text}\n\n【联网/本地搜索上下文】\n{web_text}\n\n【行情/股票池】\n{context}"}],"temperature":0.35,"max_tokens":3600}
    try:
        r=requests.post(base+"/chat/completions", headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"}, json=payload, timeout=100)
        r.raise_for_status()
        return True, r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return False, f"大模型调用失败：{type(e).__name__}: {e}"

def _strategy_panel():
    if init_db is None:
        return
    init_db(seed=True)
    with st.expander("短线打板战法库 / 来源", expanded=False):
        rows=list_strategies() if list_strategies else []
        if rows:
            show=pd.DataFrame(rows)
            cols=[c for c in ["id","name","category","tags","source","setup","buy_trigger","sell_risk"] if c in show.columns]
            st.dataframe(show[cols], width="stretch", height=220, hide_index=True)

def _knowledge_panel():
    if init_pdf_kb is None:
        st.info("未加载 pdf_kb.py，PDF/网页知识库不可用。")
        return
    init_pdf_kb()
    with st.expander("PDF / 网页资料库与联网搜索设置", expanded=False):
        st.caption("这不是训练模型，而是把PDF/网页切块存入本地知识库，回答时检索相关片段。")
        files = st.file_uploader("上传PDF供机器人学习/检索", type=["pdf"], accept_multiple_files=True)
        if st.button("导入上传的PDF"):
            if not files:
                st.warning("请先选择PDF。")
            else:
                for f in files:
                    ok, msg = add_pdf_bytes(f.name, f.getvalue())
                    st.write(("✅ " if ok else "❌ ") + msg)

        urls = st.text_area("导入网页/本地网址，每行一个", placeholder="https://example.com/news\nhttp://127.0.0.1:8000/article/xxx", height=90)
        if st.button("抓取并导入网页"):
            if not urls.strip():
                st.warning("请先输入URL。")
            elif fetch_url_text is None:
                st.error("未加载 web_researcher.py。")
            else:
                for url in [u.strip() for u in urls.splitlines() if u.strip()]:
                    ok, title, text = fetch_url_text(url)
                    if ok:
                        ok2, msg = add_text_document(title=title, text=text, source_type="url", source_path=url)
                        st.write(("✅ " if ok2 else "❌ ") + msg)
                    else:
                        st.write(f"❌ {url}: {text}")

        enable_web = st.checkbox("回答时允许联网/本地搜索", value=bool(os.getenv("LOCAL_SEARCH_ENDPOINT") or os.getenv("TAVILY_API_KEY")), help="可配置 LOCAL_SEARCH_ENDPOINT 或 TAVILY_API_KEY。")
        st.session_state["ai_enable_web_research"] = enable_web

        docs = list_documents() if list_documents else []
        if docs:
            st.markdown("**已导入资料**")
            show = pd.DataFrame(docs)
            cols = [c for c in ["title","source_type","source_path","chunk_count","created_at"] if c in show.columns]
            st.dataframe(show[cols], width="stretch", height=200, hide_index=True)

def _company_panel():
    if init_company_db is None:
        return
    init_company_db(seed=True)
    with st.expander("公司基本面/题材知识库", expanded=False):
        st.caption("用于修正模型对公司业务的认知，例如莲花控股=调味品+算力租赁/智算中心转型。")
        c1,c2=st.columns(2)
        with c1:
            code=st.text_input("代码", key="ck_code", placeholder="600186")
            name=st.text_input("名称", key="ck_name", placeholder="莲花控股")
            themes=st.text_input("题材标签", key="ck_themes", placeholder="算力租赁,AI算力")
        with c2:
            main=st.text_area("主营业务", key="ck_main", height=70)
            new=st.text_area("新业务/转型方向", key="ck_new", height=70)
            risk=st.text_area("风险提示", key="ck_risk", height=70)
        logic=st.text_area("短线理解", key="ck_logic", height=70)
        source=st.text_input("来源", key="ck_source", value="用户手动添加")
        if st.button("保存到公司知识库"):
            if code and name:
                add_or_update_company(code, name, main, new, themes, logic, risk, source)
                st.success("已保存到公司知识库。")
                st.rerun()
            else:
                st.warning("请填写代码和名称。")

def render_ai_youzhi_chat(data_candidates=None, market_context=None):
    st.subheader("AI游资复盘")
    st.caption("保留游资复盘按钮；不看龙虎榜；重点读取公司基本面、新闻公告、PDF资料库和网页搜索。")
    if init_db is not None: init_db(seed=True)
    if init_company_db is not None: init_company_db(seed=True)
    if init_pdf_kb is not None: init_pdf_kb()
    df, debug = _merge(data_candidates)
    b1,b2,b3,b4=st.columns([1,1,1,1])
    with b1:
        youzhi_clicked = st.button("游资复盘", use_container_width=True, type="primary")
    with b2:
        if st.button("重新分析/重读股票池", use_container_width=True):
            st.cache_data.clear(); st.rerun()
    with b3:
        if st.button("新对话", use_container_width=True):
            st.session_state.ai_youzhi_chat=[]; st.rerun()
    with b4:
        export="\n\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.get("ai_youzhi_chat",[])])
        st.download_button("导出会话", data=export, file_name="ai_youzhi_review.md", mime="text/markdown", use_container_width=True)

    if df.empty:
        st.warning("当前没有识别到股票池数据。请先生成涨停池/复盘池，或查看扫描诊断。")
        with st.expander("股票池扫描诊断", expanded=True):
            st.dataframe(pd.DataFrame(debug), width="stretch", hide_index=True) if debug else st.info("未扫描到 CSV 文件。")
    else:
        st.success(f"已识别股票池：{len(df)} 只股票。可结合公司基本面、新闻、PDF资料和网页搜索做开放式复盘。")
        with st.expander("当前股票池 Top 30", expanded=False):
            show=df.copy(); show["_ai_score"]=_score(show)
            show=show.sort_values("_ai_score", ascending=False, na_position="last").head(30)
            cols=[c for c in ["代码","名称","最新价","涨跌幅","涨速","规则涨速","成交额_亿","所属行业","最强概念","买卖状态","个股板块联动分","来源文件","_ai_score"] if c in show.columns]
            st.dataframe(show[cols], width="stretch", hide_index=True)

    _strategy_panel()
    _company_panel()
    _knowledge_panel()

    if "ai_youzhi_chat" not in st.session_state:
        st.session_state.ai_youzhi_chat=[]

    if youzhi_clicked:
        preset = "请进行游资复盘：不看龙虎榜，重点结合当前股票池、公司基本面、主营变化、新闻公告、PDF资料库、网页搜索信息和战法库，找出最值得关注的短线方向、明日首板候选、可能连板/回封机会，并给出激进买点、稳健买点和风险失效条件。"
        st.session_state.ai_youzhi_chat.append({"role":"user","content":preset})
        q = preset
    else:
        q = None

    box=st.container(height=520)
    with box:
        if not st.session_state.ai_youzhi_chat:
            st.info("示例：点击“游资复盘”；或输入：分析莲花控股，重点看算力租赁业务；推荐明日首板。")
        for msg in st.session_state.ai_youzhi_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    user_q=st.chat_input("例如：分析莲花控股；推荐明日首板；这个票基本面和题材是不是支持激进买点？")
    if user_q:
        q = user_q
        st.session_state.ai_youzhi_chat.append({"role":"user","content":q})

    if q:
        row=_find_stock(q, df)
        if row is not None:
            main="【目标个股】\n"+_row(row)+"\n\n【候选池参考】\n"+_pool(df,q,25)
            if fetch_fundamental_news_context is not None:
                fundamental_text = fetch_fundamental_news_context(code=row.get("代码",""), name=row.get("名称",""), question=q, limit=8)
            else:
                fundamental_text = "未加载 fundamental_news_fetcher.py，无法读取公司基本面/新闻。"
            search_query = f"{row.get('名称','')} {row.get('代码','')} {q}"
        else:
            main="【开放候选池】\n"+_pool(df,q,40)
            if fetch_market_news_context is not None:
                fundamental_text = fetch_market_news_context(limit=12)
            else:
                fundamental_text = "未加载 fundamental_news_fetcher.py，无法读取市场新闻。"
            search_query = q

        strat_rows=search_strategies(q,8) if search_strategies else []
        strat=strategies_to_context(strat_rows) if strategies_to_context else "战法库不可用。"
        kb_text = kb_context(search_query, top_k=8) if kb_context else "未加载PDF/网页知识库。"
        if st.session_state.get("ai_enable_web_research", False) and search_web_context is not None:
            web_text = search_web_context(search_query, limit=6)
        else:
            web_text = "本次未启用联网/本地搜索。可在“PDF / 网页资料库与联网搜索设置”中开启。"
        context="【市场情绪】\n"+_market(df)+"\n\n"+main
        with st.spinner("短线打板机器人正在读取公司基本面、PDF资料和网页信息..."):
            ok, ans = _ask(q, context, strat, fundamental_text, kb_text, web_text)
        if not ok: ans="❌ "+ans
        st.session_state.ai_youzhi_chat.append({"role":"assistant","content":ans})
        st.rerun()
