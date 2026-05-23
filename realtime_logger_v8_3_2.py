
# -*- coding: utf-8 -*-
from __future__ import annotations
import json,re
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd, streamlit as st
ROOT=Path(__file__).resolve().parent; LOG_DIR=ROOT/'logs'; CONFIG_DIR=ROOT/'config'; REPORT_DIR=ROOT/'reports'
for d in (LOG_DIR,CONFIG_DIR,REPORT_DIR): d.mkdir(exist_ok=True)
CONFIG_PATH=CONFIG_DIR/'realtime_logger_v8_3_2.json'; DEFAULT_CONFIG={'enabled':True,'log_all_ticks':True,'log_signals_only':True,'max_rows_per_write':1000,'dedup_same_timestamp_code':True}
def load_config():
    cfg=dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try: cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))
        except Exception: pass
    return cfg
def save_config(cfg): CONFIG_PATH.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
def _norm(x):
    d=''.join(re.findall(r'\d',str(x))); return d[-6:].zfill(6) if d else ''
def read_csv_safe(p):
    if not p.exists(): return pd.DataFrame()
    for enc in ['utf-8-sig','utf-8','gbk','gb18030']:
        try: return pd.read_csv(p,dtype={'代码':str},encoding=enc)
        except Exception: pass
    return pd.DataFrame()
def append_csv(path,df,dedup_cols=None):
    if df is None or df.empty: return
    out=pd.concat([read_csv_safe(path),df],ignore_index=True) if path.exists() else df.copy()
    if dedup_cols:
        cols=[c for c in dedup_cols if c in out.columns]
        if cols: out=out.drop_duplicates(cols,keep='last')
    out.to_csv(path,index=False,encoding='utf-8-sig')
def find_df(globs=None):
    globs=globs or {}; names=['df','main','main_df','data','watch_df','signal_df','rank_df','pool','today_pool']; cand=[]
    for n in names:
        o=globs.get(n)
        if isinstance(o,pd.DataFrame) and not o.empty and any(str(c) in ['代码','股票代码','证券代码','code','symbol'] for c in o.columns): cand.append((1000000+len(o),o))
    for n,o in globs.items():
        if isinstance(o,pd.DataFrame) and not o.empty and any(str(c) in ['代码','股票代码','证券代码','code','symbol'] for c in o.columns): cand.append((len(o),o))
    if cand: return sorted(cand,key=lambda x:x[0],reverse=True)[0][1].copy()
    for p in [REPORT_DIR/'latest_watch_signals_smallcap_v8_2_2.csv',REPORT_DIR/'latest_watch_signals_kobe_v8_2_1.csv',REPORT_DIR/'latest_watch_signals.csv',REPORT_DIR/'latest_watch_states_v7_9.csv']:
        df=read_csv_safe(p)
        if not df.empty: return df
    return pd.DataFrame()
def norm_df(df):
    if df is None or df.empty: return pd.DataFrame()
    x=df.copy(); x.columns=[str(c).strip() for c in x.columns]
    if '代码' not in x.columns:
        for c in ['股票代码','证券代码','code','symbol']:
            if c in x.columns: x['代码']=x[c]; break
    if '代码' in x.columns: x['代码']=x['代码'].map(_norm)
    x['log_time']=datetime.now().strftime('%F %T'); x['log_date']=datetime.now().strftime('%Y%m%d'); return x
def is_signal(df):
    texts=[]
    for c in ['trade_allowed','最终邮件触发','rule_pass','pattern_signal','买卖状态','标准状态','rule_type','rule_name']:
        if c in df.columns: texts.append(df[c].astype(str))
    if not texts: return pd.Series([False]*len(df),index=df.index)
    s=texts[0]
    for t in texts[1:]: s=s+' '+t
    return s.str.contains('True|true|1|买点|半路|扫板|排板|回封|风险|卖出|触发|允许',regex=True,na=False)
def log_current_snapshot_v8_3_2(globs=None):
    cfg=load_config()
    if not cfg.get('enabled',True): return False,'logger未启用'
    x=norm_df(find_df(globs))
    if x.empty: return False,'没有可记录数据'
    x=x.head(int(cfg.get('max_rows_per_write',1000))); date=datetime.now().strftime('%Y%m%d')
    if cfg.get('log_all_ticks',True): append_csv(LOG_DIR/f'realtime_ticks_{date}.csv',x,['log_time','代码'] if cfg.get('dedup_same_timestamp_code',True) else None)
    sig=x[is_signal(x)].copy()
    if cfg.get('log_signals_only',True) and not sig.empty: append_csv(LOG_DIR/f'signals_{date}.csv',sig,['log_time','代码','rule_name'] if 'rule_name' in sig.columns else ['log_time','代码'])
    return True,f'已记录行情{len(x)}条，信号{len(sig)}条'
def render_realtime_logger_panel():
    cfg=load_config(); st.subheader('v8.3.2 全天日志记录'); st.caption('记录8502每次刷新快照和信号，为盘后复盘/回测提供时间线。')
    with st.expander('日志设置',expanded=False):
        c1,c2,c3=st.columns(3)
        with c1: cfg['enabled']=st.checkbox('启用日志记录',value=bool(cfg.get('enabled',True)),key='rtlog_e')
        with c2: cfg['log_all_ticks']=st.checkbox('记录全量快照',value=bool(cfg.get('log_all_ticks',True)),key='rtlog_a')
        with c3: cfg['log_signals_only']=st.checkbox('记录信号日志',value=bool(cfg.get('log_signals_only',True)),key='rtlog_s')
        cfg['max_rows_per_write']=st.number_input('每次最多写入行数',10,10000,int(cfg.get('max_rows_per_write',1000)),10,key='rtlog_m')
        if st.button('保存日志设置',key='rtlog_save'): save_config(cfg); st.success('已保存')
    today=datetime.now().strftime('%Y%m%d')
    for p in [LOG_DIR/f'realtime_ticks_{today}.csv',LOG_DIR/f'signals_{today}.csv']:
        if p.exists(): st.write(f'{p.name}: {len(read_csv_safe(p))} 行')
