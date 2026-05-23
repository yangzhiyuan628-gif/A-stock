
# -*- coding: utf-8 -*-
from __future__ import annotations
import json,os,re,time
from datetime import datetime,timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus,urlparse
import pandas as pd, requests, streamlit as st
ROOT=Path(__file__).resolve().parent; CONFIG_DIR=ROOT/'config'; REPORT_DIR=ROOT/'reports'; LOG_DIR=ROOT/'logs'
for d in (CONFIG_DIR,REPORT_DIR,LOG_DIR): d.mkdir(exist_ok=True)
CONFIG_PATH=CONFIG_DIR/'web_research_v8_3_2.json'; CACHE_PATH=REPORT_DIR/'web_research_cache_v8_3_2.csv'; ERROR_LOG=LOG_DIR/'web_research_errors.log'
DEFAULT_CONFIG={'enabled':True,'auto_inject_to_llm':True,'max_results':5,'cache_hours':12,'timeout_seconds':20,'duckduckgo_url':'https://duckduckgo.com/html/?q={query}','user_agent':'Mozilla/5.0','max_context_chars':5000,'queries_template':['{keyword} 公司 主营业务','{keyword} 最新消息 公告','{keyword} 算力 AI 机器人 低空经济','{keyword} 证券 互动易 投资者关系']}
def load_config():
    cfg=dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try: cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))
        except Exception: pass
    return cfg
def save_config(cfg): CONFIG_PATH.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
def log_error(where,exc,extra=None):
    try:
        with ERROR_LOG.open('a',encoding='utf-8') as f: f.write(json.dumps({'time':datetime.now().strftime('%F %T'),'where':where,'error':str(exc),'extra':extra or {}},ensure_ascii=False)+'\n')
    except Exception: pass
def _s(x): return '' if x is None else str(x).replace('\n',' ').replace('\r',' ').strip()
def normalize_keyword(text):
    text=_s(text); m=re.search(r'\b\d{6}\b',text)
    if m: return m.group(0)
    text=re.sub(r'(分析|推荐|能买吗|能不能|现在|适合|买入|股票|这只|一下|请|帮我|是否|看看)',' ',text)
    ws=re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{2,}',text); return ws[0] if ws else text[:20]
def read_cache():
    if not CACHE_PATH.exists(): return pd.DataFrame()
    for enc in ['utf-8-sig','utf-8','gbk']:
        try: return pd.read_csv(CACHE_PATH,dtype=str,encoding=enc)
        except Exception: pass
    return pd.DataFrame()
def write_cache(df): df.to_csv(CACHE_PATH,index=False,encoding='utf-8-sig')
def cache_hit(keyword,hours):
    df=read_cache()
    if df.empty or 'keyword' not in df.columns or 'timestamp' not in df.columns: return pd.DataFrame()
    sub=df[df['keyword'].astype(str)==str(keyword)].copy(); ts=pd.to_datetime(sub['timestamp'],errors='coerce')
    return sub[(ts>=(datetime.now()-timedelta(hours=hours))).fillna(False)].copy()
def append_cache(rows):
    if not rows: return
    old=read_cache(); new=pd.DataFrame(rows); out=pd.concat([old,new],ignore_index=True) if not old.empty else new
    out=out.drop_duplicates(['keyword','title','url'],keep='last'); write_cache(out)
def strip_html(h):
    h=re.sub(r'(?is)<script.*?</script>|<style.*?</style>',' ',h); t=re.sub(r'(?s)<.*?>',' ',h); return re.sub(r'\s+',' ',t).strip()
def parse_results(html,keyword,limit):
    blocks=re.findall(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',html) or re.findall(r'(?is)<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',html)
    rows=[]; seen=set()
    for url,title_html in blocks:
        title=strip_html(title_html); url=url.replace('&amp;','&')
        if 'uddg=' in url:
            try:
                import urllib.parse; qs=urllib.parse.parse_qs(urllib.parse.urlparse(url).query); url=qs.get('uddg',[url])[0]
            except Exception: pass
        if not title or not url or url in seen: continue
        seen.add(url); rows.append({'timestamp':datetime.now().strftime('%F %T'),'keyword':keyword,'title':title[:200],'url':url[:500],'domain':urlparse(url).netloc,'snippet':'','source':'duckduckgo_html'})
        if len(rows)>=limit: break
    return rows
def search_web(keyword,force_refresh=False):
    cfg=load_config(); keyword=normalize_keyword(keyword)
    if not force_refresh:
        hit=cache_hit(keyword,int(cfg.get('cache_hours',12)))
        if not hit.empty: return hit.head(int(cfg.get('max_results',5)))
    rows=[]; headers={'User-Agent':cfg.get('user_agent','Mozilla/5.0')}
    for tmpl in cfg.get('queries_template') or DEFAULT_CONFIG['queries_template']:
        q=tmpl.format(keyword=keyword); url=cfg.get('duckduckgo_url').format(query=quote_plus(q))
        try:
            r=requests.get(url,headers=headers,timeout=int(cfg.get('timeout_seconds',20))); r.raise_for_status()
            for item in parse_results(r.text,keyword,int(cfg.get('max_results',5))): item['query']=q; rows.append(item)
            time.sleep(0.2)
        except Exception as e: log_error('search_web',e,{'query':q,'url':url})
    uniq=[]; seen=set()
    for r in rows:
        if r['url'] in seen: continue
        seen.add(r['url']); uniq.append(r)
    append_cache(uniq); return pd.DataFrame(uniq).head(int(cfg.get('max_results',5)))
def build_research_context(query):
    cfg=load_config()
    if not cfg.get('enabled',True): return ''
    kw=normalize_keyword(query); df=search_web(kw,False)
    if df.empty: return ''
    lines=[f'【联网检索摘要 v8.3.2】关键词：{kw}','以下结果来自网页搜索，仅作辅助，信息可能滞后。']
    for i,(_,r) in enumerate(df.iterrows(),1): lines += [f'{i}. {r.get("title","")}',f'   来源：{r.get("domain","")}',f'   URL：{r.get("url","")}']
    return '\n'.join(lines)[:int(cfg.get('max_context_chars',5000))]
def inject_web_context_into_messages(messages,query_hint=''):
    cfg=load_config()
    if not (cfg.get('enabled',True) and cfg.get('auto_inject_to_llm',True)) or not isinstance(messages,list): return messages
    q=query_hint
    for m in reversed(messages):
        if isinstance(m,dict) and m.get('role')=='user': q+='\n'+_s(m.get('content','')); break
    ctx=build_research_context(q)
    if not ctx: return messages
    new=[dict(m) if isinstance(m,dict) else m for m in messages]
    for m in reversed(new):
        if isinstance(m,dict) and m.get('role')=='user': m['content']=ctx+'\n\n'+_s(m.get('content','')); break
    return new
def install_web_research_patch():
    if getattr(requests,'_stock_robot_web_research_v832',False): return
    old=requests.post
    def patched(url,*args,**kw):
        try:
            payload=kw.get('json')
            if isinstance(payload,dict) and 'messages' in payload and ('/chat/completions' in str(url) or 'model' in payload):
                p=dict(payload); p['messages']=inject_web_context_into_messages(p.get('messages'),str(p.get('model',''))); kw['json']=p
        except Exception as e: log_error('patch',e)
        return old(url,*args,**kw)
    requests.post=patched; requests._stock_robot_web_research_v832=True
def render_web_research_panel(app_name='unknown'):
    cfg=load_config(); st.subheader(f'v8.3.2 联网检索增强（{app_name}）'); st.caption('检索公司主营、新闻、公告、题材，辅助大模型问股。')
    with st.expander('联网检索设置',expanded=False):
        c1,c2,c3,c4=st.columns(4)
        with c1: cfg['enabled']=st.checkbox('启用联网检索',value=bool(cfg.get('enabled',True)),key=f'wr_e_{app_name}')
        with c2: cfg['auto_inject_to_llm']=st.checkbox('自动注入大模型',value=bool(cfg.get('auto_inject_to_llm',True)),key=f'wr_i_{app_name}')
        with c3: cfg['max_results']=st.number_input('最大结果数',1,20,int(cfg.get('max_results',5)),1,key=f'wr_m_{app_name}')
        with c4: cfg['cache_hours']=st.number_input('缓存小时',1,240,int(cfg.get('cache_hours',12)),1,key=f'wr_c_{app_name}')
        cfg['duckduckgo_url']=st.text_input('搜索URL模板',value=str(cfg.get('duckduckgo_url')),key=f'wr_url_{app_name}')
        if st.button('保存联网检索设置',key=f'wr_save_{app_name}'): save_config(cfg); install_web_research_patch(); st.success('已保存')
    q=st.text_input('测试检索关键词/股票名/代码',value='',placeholder='例如：莲花控股 算力租赁',key=f'wr_q_{app_name}')
    force=st.checkbox('强制刷新',value=False,key=f'wr_force_{app_name}')
    if st.button('运行联网检索',type='primary',key=f'wr_search_{app_name}') and q:
        df=search_web(q,force); st.dataframe(df,hide_index=True,use_container_width=True,height=260) if not df.empty else st.warning('未搜索到结果')
        st.text_area('将注入大模型的摘要',value=build_research_context(q),height=220,key=f'wr_ctx_{app_name}')
    df=read_cache()
    if not df.empty:
        with st.expander('最近联网检索缓存',expanded=False): st.dataframe(df.tail(100).sort_index(ascending=False),hide_index=True,use_container_width=True,height=260)
