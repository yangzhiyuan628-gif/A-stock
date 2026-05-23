
# -*- coding: utf-8 -*-
"""v8.3 Skills 技能系统：skills库、LLM自动注入、8502信号绑定、skill统计。"""
from __future__ import annotations
import copy, json, os, re, time
from pathlib import Path
from typing import Any
import pandas as pd
import requests
import streamlit as st

ROOT=Path(__file__).resolve().parent
SKILLS_DIR=ROOT/'skills'; EXAMPLES_DIR=SKILLS_DIR/'examples'; UPLOADS_DIR=SKILLS_DIR/'uploads'
REPORT_DIR=ROOT/'reports'; CONFIG_DIR=ROOT/'config'
for p in [SKILLS_DIR, EXAMPLES_DIR, UPLOADS_DIR, REPORT_DIR, CONFIG_DIR]: p.mkdir(parents=True, exist_ok=True)
REGISTRY_PATH=SKILLS_DIR/'registry.json'; SKILL_STATS_PATH=SKILLS_DIR/'skill_stats.csv'; PERFORMANCE_MD=SKILLS_DIR/'performance_summary.md'
CONFIG_PATH=CONFIG_DIR/'skills_system_v8_3.json'
SKILL_SIGNAL_PATH=REPORT_DIR/'latest_watch_signals_skills_v8_3.csv'; SKILL_EVENT_PATH=REPORT_DIR/'watch_signal_events_skills_v8_3.csv'
DEFAULT_CONFIG={'enabled':True,'auto_inject_to_llm':True,'max_skill_context_chars':8000,'top_k_skills':5,'auto_enrich_8502_signals':True,'auto_update_skill_stats':True,'default_skill_priority':50}
DEFAULT_SKILLS={
'emotion_cycle.md':'# 情绪周期 Skill\n\n主升/强修复可看龙头、人气核心、回封；混沌偏强看板块前排和低位补涨；弱修复轻仓试错；退潮/冰点空仓防守。风险：炸板扩散、高位大面、昨日涨停溢价差、主线混乱。',
'kobe_first_board.md':'# 92科比首板 Skill\n\n适用题材首日发酵、低位扩散、补涨启动。条件：低位、新闻催化、板块扩散、中军不弱、个股前排。避免中位股和退潮题材。',
'half_way_buy.md':'# 半路买点 Skill\n\n适用板块发酵且个股未涨停时。条件：涨幅3%-8%、5分钟涨速增强、成交额达标、换手和量比合理、板块前排或低位补涨。',
'sweep_board.md':'# 扫板 Skill\n\n适用强修复/主升，板块前排接近涨停。条件：涨幅约9.3%以上、涨速不弱、板块涨停支撑、成交额/换手/量比通过。退潮冰点禁止扫板。',
'queue_board.md':'# 排板 Skill\n\n适用接近涨停或已封板但需观察封单。条件：涨幅约9.7%以上、封单出现、允许排板和撤单观察。风险：尾盘弱封、反复炸板、虚封。',
'reseal_board.md':'# 回封 Skill\n\n适用炸板后重新回封。条件：炸板次数少、回封不太晚、成交额不过度异常、封单恢复、板块仍强。',
'smallcap_growth.md':'# 小市值高弹性 Skill\n\n优先未来估值弹性高的小市值：总市值较小、流通市值不大、题材/新闻催化、板块前排、成交活跃、涨速靠前、有涨停记忆。中军作为参考，大市值只在强情绪核心前排时例外。',
'medium_reference.md':'# 中军参考 Skill\n\n中军用于判断板块强度和资金锚点，不默认作为买点。中军强则小市值补涨更有持续性；中军弱则板块持续性下降。',
'risk_control.md':'# 风险控制 Skill\n\n先判断能不能出手，再判断买什么。风险：退潮冰点、高位大面、炸板扩散、中位股亏钱、放量滞涨、弱转强失败、板块中军转弱。'
}
DEFAULT_REGISTRY={'version':'v8.3','updated_at':'','skills':[
{'name':'情绪周期','type':'market_mode','file':'emotion_cycle.md','enabled':True,'priority':100,'aliases':['情绪','周期','主升','退潮','冰点','修复','市场模式'],'rule_types':['风控','观察']},
{'name':'92科比首板','type':'buy_signal','file':'kobe_first_board.md','enabled':True,'priority':90,'aliases':['92科比','首板','补涨','低位','一板','1进2'],'rule_types':['补涨','切换','半路']},
{'name':'半路买点','type':'buy_signal','file':'half_way_buy.md','enabled':True,'priority':85,'aliases':['半路','半路买点','低位异动','涨速','承接'],'rule_types':['半路']},
{'name':'扫板','type':'buy_signal','file':'sweep_board.md','enabled':True,'priority':80,'aliases':['扫板','打板','接近涨停','强情绪'],'rule_types':['扫板']},
{'name':'排板','type':'buy_signal','file':'queue_board.md','enabled':True,'priority':78,'aliases':['排板','封单','封板观察','撤单观察'],'rule_types':['排板']},
{'name':'回封','type':'buy_signal','file':'reseal_board.md','enabled':True,'priority':82,'aliases':['回封','炸板','承接','重新封板'],'rule_types':['回封']},
{'name':'小市值高弹性','type':'stock_selection','file':'smallcap_growth.md','enabled':True,'priority':95,'aliases':['小市值','高弹性','未来估值','弹性分','补涨','题材弹性'],'rule_types':['半路','补涨','切换']},
{'name':'中军参考','type':'market_reference','file':'medium_reference.md','enabled':True,'priority':75,'aliases':['中军','大市值','板块强度','方向参考','资金锚点'],'rule_types':['观察']},
{'name':'风险控制','type':'risk_control','file':'risk_control.md','enabled':True,'priority':100,'aliases':['风控','风险','卖点','退潮','炸板','中位股','弱转强失败'],'rule_types':['风控']}
]}

def load_config():
    cfg=dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try: cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))
        except Exception: pass
    return cfg

def save_config(cfg): CONFIG_PATH.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')

def ensure_default_skills():
    for fn,txt in DEFAULT_SKILLS.items():
        p=SKILLS_DIR/fn
        if not p.exists(): p.write_text(txt+'\n',encoding='utf-8')
    if not REGISTRY_PATH.exists():
        reg=copy.deepcopy(DEFAULT_REGISTRY); reg['updated_at']=time.strftime('%Y-%m-%d %H:%M:%S')
        REGISTRY_PATH.write_text(json.dumps(reg,ensure_ascii=False,indent=2),encoding='utf-8')
    for rel,txt in {'success_cases.csv':'date,code,name,skill_name,rule_name,ret_5m,ret_close,notes\n','failed_cases.csv':'date,code,name,skill_name,rule_name,ret_5m,ret_close,notes\n','daily_review_notes.md':'# 每日复盘记录\n\n'}.items():
        p=EXAMPLES_DIR/rel
        if not p.exists(): p.write_text(txt,encoding='utf-8')

def load_registry():
    ensure_default_skills()
    try: return json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))
    except Exception: return copy.deepcopy(DEFAULT_REGISTRY)

def save_registry(reg):
    reg['updated_at']=time.strftime('%Y-%m-%d %H:%M:%S')
    REGISTRY_PATH.write_text(json.dumps(reg,ensure_ascii=False,indent=2),encoding='utf-8')

def skill_file_text(skill):
    p=SKILLS_DIR/str(skill.get('file',''))
    return p.read_text(encoding='utf-8',errors='ignore') if p.exists() else ''

def enabled_skills():
    ss=[s for s in load_registry().get('skills',[]) if s.get('enabled',True)]
    return sorted(ss,key=lambda s:int(s.get('priority',0)),reverse=True)

def _safe(x): return '' if x is None else str(x).replace('\n',' ').replace('\r',' ').strip()
def _norm_code(x):
    d=''.join(re.findall(r'\d',str(x))); return d[-6:].zfill(6) if d else ''

def score_skill(skill,query):
    q=query.lower(); score=float(skill.get('priority',0))/100
    if str(skill.get('name','')).lower() in q: score+=5
    for a in skill.get('aliases',[]) or []:
        if str(a).lower() in q: score+=3
    for rt in skill.get('rule_types',[]) or []:
        if str(rt).lower() in q: score+=2
    text=skill_file_text(skill).lower()
    for t in re.findall(r'[\u4e00-\u9fa5A-Za-z0-9_]{2,}',q):
        if t in text: score+=0.2
    return score

def retrieve_skills(query,top_k=None):
    cfg=load_config(); top_k=int(top_k or cfg.get('top_k_skills',5))
    arr=[(score_skill(s,query),s) for s in enabled_skills()]
    arr=[x for x in arr if x[0]>0.5]; arr.sort(key=lambda x:x[0],reverse=True)
    return [s for _,s in arr[:top_k]]

def build_skills_context(query,max_chars=None):
    cfg=load_config()
    if not cfg.get('enabled',True): return ''
    max_chars=int(max_chars or cfg.get('max_skill_context_chars',8000))
    parts=['【v8.3 Skills技能库】回答/复盘时优先参考以下技能，但不能承诺收益。']
    for s in retrieve_skills(query,cfg.get('top_k_skills',5)):
        txt=skill_file_text(s).strip()
        if txt: parts.append(f"\n---\nSkill: {s.get('name')} | type={s.get('type')} | priority={s.get('priority')}\n{txt}")
    ctx='\n'.join(parts)
    return ctx[:max_chars]+'\n【Skills上下文截断】' if len(ctx)>max_chars else ctx

def inject_skill_context_into_messages(messages,query_hint=''):
    cfg=load_config()
    if not (cfg.get('enabled',True) and cfg.get('auto_inject_to_llm',True)) or not isinstance(messages,list): return messages
    q=query_hint
    for msg in reversed(messages):
        if isinstance(msg,dict) and msg.get('role')=='user':
            c=msg.get('content','')
            if isinstance(c,str): q+='\n'+c
            elif isinstance(c,list):
                for it in c:
                    if isinstance(it,dict) and it.get('type')=='text': q+='\n'+str(it.get('text',''))
            break
    ctx=build_skills_context(q)
    if not ctx: return messages
    new=copy.deepcopy(messages); target=None
    for msg in reversed(new):
        if isinstance(msg,dict) and msg.get('role')=='user': target=msg; break
    if target is None: return new
    c=target.get('content','')
    if isinstance(c,str): target['content']=ctx+'\n\n'+c
    elif isinstance(c,list):
        done=False
        for it in c:
            if isinstance(it,dict) and it.get('type')=='text': it['text']=ctx+'\n\n'+str(it.get('text','')); done=True; break
        if not done: c.insert(0,{'type':'text','text':ctx})
    return new

def install_skill_context_patch():
    if getattr(requests,'_stock_robot_skills_v83_patch',False): return
    old=requests.post
    def patched_post(url,*args,**kwargs):
        try:
            payload=kwargs.get('json')
            if isinstance(payload,dict) and 'messages' in payload and ('/chat/completions' in str(url) or 'model' in payload):
                p=copy.deepcopy(payload); p['messages']=inject_skill_context_into_messages(p.get('messages'),str(p.get('model',''))); kwargs['json']=p
        except Exception: pass
        return old(url,*args,**kwargs)
    requests.post=patched_post; requests._stock_robot_skills_v83_patch=True

def pdf_to_text(data):
    try:
        import pypdf, io
        r=pypdf.PdfReader(io.BytesIO(data)); out=[]
        for i,p in enumerate(r.pages): out.append(f'\n\n## Page {i+1}\n'+(p.extract_text() or ''))
        return '\n'.join(out).strip()
    except Exception as e: return f'PDF解析失败：{type(e).__name__}: {e}'

def add_skill_from_upload(file_obj,skill_name,skill_type='knowledge',priority=50,aliases=''):
    ensure_default_skills()
    if file_obj is None: return False,'没有文件。'
    raw=getattr(file_obj,'name','uploaded_skill'); suf=Path(raw).suffix.lower(); data=file_obj.getvalue()
    if suf=='.pdf': text=pdf_to_text(data)
    else:
        try: text=data.decode('utf-8')
        except Exception: text=data.decode('gb18030',errors='ignore')
    if not text.strip(): return False,'文件内容为空或无法解析。'
    safe=re.sub(r'[\\/:*?"<>|\s]+','_',skill_name or Path(raw).stem).strip('_') or 'custom_skill'
    md=f'{safe}.md'; (SKILLS_DIR/md).write_text(f'# {skill_name or Path(raw).stem}\n\n## 来源\n{raw}\n\n## 内容\n\n{text.strip()}\n',encoding='utf-8')
    reg=load_registry(); reg['skills'].append({'name':skill_name or Path(raw).stem,'type':skill_type,'file':md,'enabled':True,'priority':int(priority),'aliases':[a.strip() for a in re.split(r'[,，;；\s]+',aliases or '') if a.strip()],'rule_types':[]}); save_registry(reg)
    return True,f'已新增 Skill：{skill_name or Path(raw).stem} -> skills/{md}'

def read_csv_safe(path):
    if not Path(path).exists(): return pd.DataFrame()
    for enc in ['utf-8-sig','utf-8','gbk','gb18030']:
        try: return pd.read_csv(path,dtype={'代码':str},encoding=enc)
        except Exception: pass
    try: return pd.read_csv(path,dtype={'代码':str})
    except Exception: return pd.DataFrame()

def find_watch_df_from_globals(globs=None):
    globs=globs or {}; pref=['signal_df','watch_df','df','main','main_df','data','rank_df','pool','today_pool','limit_pool']
    cand=[]
    for name in pref:
        obj=globs.get(name)
        if isinstance(obj,pd.DataFrame) and not obj.empty and any(c in set(map(str,obj.columns)) for c in ['代码','股票代码','证券代码','code','symbol']): cand.append((1000000+len(obj),name,obj))
    for name,obj in globs.items():
        if isinstance(obj,pd.DataFrame) and not obj.empty and any(c in set(map(str,obj.columns)) for c in ['代码','股票代码','证券代码','code','symbol']): cand.append((len(obj),name,obj))
    if cand:
        cand.sort(key=lambda x:x[0],reverse=True); return cand[0][2].copy()
    for p in [REPORT_DIR/'latest_watch_signals_smallcap_v8_2_2.csv',REPORT_DIR/'latest_watch_signals_kobe_v8_2_1.csv',REPORT_DIR/'latest_watch_signals_rule_attribution_v8_2_1.csv',REPORT_DIR/'latest_watch_states_v7_9.csv',REPORT_DIR/'latest_watch_signals.csv']:
        df=read_csv_safe(p)
        if not df.empty: return df
    return pd.DataFrame()

def assign_skill_to_row(row):
    text=' '.join(_safe(row.get(c,'')) for c in ['rule_name','rule_type','pattern_signal','买卖状态','标准状态','trigger_reason','市值角色','market_mode_effective'] if c in row.index)
    s=retrieve_skills(text,1)
    return (str(s[0].get('name','')),str(s[0].get('type',''))) if s else ('','')

def enrich_latest_signals_with_skills_v8_3(globs=None):
    cfg=load_config()
    if not (cfg.get('enabled',True) and cfg.get('auto_enrich_8502_signals',True)): return pd.DataFrame(),'Skills信号绑定未启用。'
    df=find_watch_df_from_globals(globs)
    if df.empty: return pd.DataFrame(),'未找到可绑定Skills的盯盘数据。'
    x=df.copy()
    if '代码' not in x.columns:
        for c in ['股票代码','证券代码','code','symbol']:
            if c in x.columns: x['代码']=x[c]; break
    if '代码' in x.columns: x['代码']=x['代码'].map(_norm_code)
    pairs=[assign_skill_to_row(r) for _,r in x.iterrows()]
    x['skill_name']=[p[0] for p in pairs]; x['skill_type']=[p[1] for p in pairs]; x['skill_version']='v8.3'
    x.to_csv(SKILL_SIGNAL_PATH,index=False,encoding='utf-8-sig')
    events=read_csv_safe(REPORT_DIR/'watch_signal_events.csv')
    if not events.empty and '代码' in events.columns and '代码' in x.columns:
        e=events.copy(); e['代码']=e['代码'].map(_norm_code); m=x[['代码','skill_name','skill_type','skill_version']].drop_duplicates('代码',keep='first')
        for c in ['skill_name','skill_type','skill_version']:
            if c in e.columns: e=e.drop(columns=[c])
        e=e.merge(m,on='代码',how='left'); e.to_csv(SKILL_EVENT_PATH,index=False,encoding='utf-8-sig')
        try: e.to_csv(REPORT_DIR/'watch_signal_events.csv',index=False,encoding='utf-8-sig')
        except Exception: pass
    return x,f'已给 {len(x)} 条盯盘记录绑定 skill_name。'

def update_skill_stats_v8_3():
    ensure_default_skills(); dfs=[]
    for p in [REPORT_DIR/'signal_effect_stats_by_rule_kobe_v8_2_1.csv',REPORT_DIR/'signal_effect_stats_by_rule_v8_2_1.csv',REPORT_DIR/'signal_effect_stats_v8_2.csv']:
        df=read_csv_safe(p)
        if not df.empty: df['_source_file']=p.name; dfs.append(df)
    if not dfs:
        empty=pd.DataFrame(columns=['skill_name','skill_type','样本数','5分钟均值','胜率_5分钟','收盘均值','胜率_收盘','建议','source']); empty.to_csv(SKILL_STATS_PATH,index=False,encoding='utf-8-sig'); PERFORMANCE_MD.write_text('# Skill表现统计\n\n暂无 v8.2/v8.2.1 信号效果统计数据。\n',encoding='utf-8'); return empty,'未找到信号效果统计文件。'
    rows=[]
    for df in dfs:
        for _,r in df.iterrows():
            rn=_safe(r.get('rule_name',r.get('to_state',r.get('规则名称','')))); rt=_safe(r.get('rule_type',r.get('to_state',r.get('规则类型','')))); matched=retrieve_skills(rn+' '+rt,1)
            sn=matched[0].get('name','') if matched else '未归因'; st=matched[0].get('type','') if matched else 'unknown'
            rows.append({'skill_name':sn,'skill_type':st,'rule_name':rn,'rule_type':rt,'样本数':r.get('样本数',''),'1分钟均值':r.get('1分钟均值',''),'5分钟均值':r.get('5分钟均值',''),'10分钟均值':r.get('10分钟均值',''),'收盘均值':r.get('收盘均值',''),'胜率_5分钟':r.get('胜率_5分钟',''),'胜率_10分钟':r.get('胜率_10分钟',''),'胜率_收盘':r.get('胜率_收盘',''),'最大回撤均值':r.get('最大回撤均值',''),'建议':r.get('建议',''),'source':r.get('_source_file','')})
    out=pd.DataFrame(rows); out.to_csv(SKILL_STATS_PATH,index=False,encoding='utf-8-sig'); write_performance_summary(out); return out,f'已更新 Skill 统计：{len(out)} 条。'

def write_performance_summary(df):
    lines=['# Skill表现统计','',f"更新时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",'']
    if df.empty: lines.append('暂无数据。')
    else:
        for skill,g in df.groupby('skill_name'):
            samples=pd.to_numeric(g.get('样本数'),errors='coerce').sum(); ret5=pd.to_numeric(g.get('5分钟均值'),errors='coerce').mean(); win5=pd.to_numeric(g.get('胜率_5分钟'),errors='coerce').mean(); close=pd.to_numeric(g.get('收盘均值'),errors='coerce').mean()
            lines += [f'## {skill}', f'- 样本数合计：{samples:.0f}' if pd.notna(samples) else '- 样本数：未知', f'- 5分钟均值：{ret5:.3f}%' if pd.notna(ret5) else '- 5分钟均值：未知', f'- 5分钟胜率：{win5:.2f}%' if pd.notna(win5) else '- 5分钟胜率：未知', f'- 收盘均值：{close:.3f}%' if pd.notna(close) else '- 收盘均值：未知','']
    PERFORMANCE_MD.write_text('\n'.join(lines),encoding='utf-8')

def render_registry_editor():
    reg=load_registry(); skills=reg.get('skills',[]); edited=[]
    for i,s in enumerate(skills):
        with st.expander(f"{'✅' if s.get('enabled',True) else '⛔'} {s.get('name')} | {s.get('type')} | priority={s.get('priority')}", expanded=False):
            c1,c2,c3,c4=st.columns([1,1.2,1,1])
            with c1: enabled=st.checkbox('启用',value=bool(s.get('enabled',True)),key=f'skill_enabled_{i}_{s.get("name")}')
            with c2: name=st.text_input('名称',value=str(s.get('name','')),key=f'skill_name_{i}')
            with c3: typ=st.text_input('类型',value=str(s.get('type','')),key=f'skill_type_{i}')
            with c4: priority=st.number_input('优先级',0,200,int(s.get('priority',50)),1,key=f'skill_priority_{i}')
            file_name=st.text_input('文件',value=str(s.get('file','')),key=f'skill_file_{i}')
            aliases=st.text_area('关键词/别名',value=', '.join(map(str,s.get('aliases',[]))),height=70,key=f'skill_alias_{i}')
            rule_types=st.text_input('绑定 rule_type',value=', '.join(map(str,s.get('rule_types',[]))),key=f'skill_ruletypes_{i}')
            txt=skill_file_text(s); new_txt=st.text_area('Skill 内容',value=txt,height=230,key=f'skill_content_{i}')
            if st.button('保存该 Skill 文档',key=f'skill_save_doc_{i}'):
                (SKILLS_DIR/file_name).write_text(new_txt,encoding='utf-8'); st.success(f'已保存 skills/{file_name}')
            edited.append({'name':name,'type':typ,'file':file_name,'enabled':enabled,'priority':int(priority),'aliases':[a.strip() for a in re.split(r'[,，;；\n]+',aliases) if a.strip()],'rule_types':[a.strip() for a in re.split(r'[,，;；\n]+',rule_types) if a.strip()]})
    if st.button('保存 registry.json',type='primary',key='skills_save_registry'):
        reg['skills']=edited; save_registry(reg); st.success('已保存 skills/registry.json。')

def render_upload_skill_panel():
    cfg=load_config(); uploaded=st.file_uploader('上传 PDF / Markdown / TXT 转成 Skill',type=['pdf','md','txt'],accept_multiple_files=False,key='skill_upload_file')
    c1,c2,c3=st.columns([1.5,1,1])
    with c1: skill_name=st.text_input('Skill 名称',value='',placeholder='例如：92科比语录补充',key='skill_upload_name')
    with c2: skill_type=st.selectbox('Skill 类型',['knowledge','buy_signal','risk_control','market_mode','stock_selection','market_reference'],key='skill_upload_type')
    with c3: priority=st.number_input('优先级',0,200,int(cfg.get('default_skill_priority',50)),1,key='skill_upload_priority')
    aliases=st.text_input('关键词/别名',value='',placeholder='例如：92科比, 首板, 补涨',key='skill_upload_alias')
    if st.button('导入为 Skill',key='skill_import_btn'):
        ok,msg=add_skill_from_upload(uploaded,skill_name,skill_type,priority,aliases); st.success(msg) if ok else st.error(msg)

def render_skills_system_panel(app_name='8501'):
    ensure_default_skills(); cfg=load_config()
    st.subheader(f'v8.3 Skills 技能系统（{app_name}）')
    st.caption('把PDF、战法、规则、胜率、复盘结论沉淀成可调用技能；8501用于复盘，8502用于盯盘归因和大模型问股。')
    with st.expander('Skills 总开关',expanded=False):
        c1,c2,c3,c4=st.columns(4)
        with c1: cfg['enabled']=st.checkbox('启用Skills系统',value=bool(cfg.get('enabled',True)),key=f'skills_enabled_{app_name}')
        with c2: cfg['auto_inject_to_llm']=st.checkbox('自动注入大模型上下文',value=bool(cfg.get('auto_inject_to_llm',True)),key=f'skills_inject_{app_name}')
        with c3: cfg['top_k_skills']=st.number_input('每次最多调用Skills',1,20,int(cfg.get('top_k_skills',5)),1,key=f'skills_topk_{app_name}')
        with c4: cfg['max_skill_context_chars']=st.number_input('上下文最大字符',1000,50000,int(cfg.get('max_skill_context_chars',8000)),500,key=f'skills_chars_{app_name}')
        if app_name=='8502': cfg['auto_enrich_8502_signals']=st.checkbox('8502自动绑定skill_name',value=bool(cfg.get('auto_enrich_8502_signals',True)),key='skills_enrich_8502')
        cfg['auto_update_skill_stats']=st.checkbox('自动更新Skill统计',value=bool(cfg.get('auto_update_skill_stats',True)),key=f'skills_stats_auto_{app_name}')
        if st.button('保存Skills设置',key=f'skills_save_config_{app_name}'):
            save_config(cfg); st.success('已保存 config/skills_system_v8_3.json。')
    tab1,tab2,tab3,tab4=st.tabs(['技能库','上传Skill','信号绑定','表现统计'])
    with tab1: render_registry_editor()
    with tab2: render_upload_skill_panel()
    with tab3:
        if app_name=='8502':
            if st.button('立即给8502信号绑定skill_name',type='primary',key='skills_enrich_now'):
                df,msg=enrich_latest_signals_with_skills_v8_3(globals()); st.success(msg)
            df=read_csv_safe(SKILL_SIGNAL_PATH)
            if df.empty: st.info('暂无 skills 绑定快照。')
            else:
                cols=[c for c in ['代码','名称','rule_name','rule_type','pattern_signal','skill_name','skill_type','涨跌幅','成交额_亿','市值角色'] if c in df.columns]
                st.dataframe(df[cols].head(300),hide_index=True,use_container_width=True,height=360)
        else:
            st.info('8501主要使用 Skills 做复盘和大模型上下文。')
            q=st.text_input('测试检索相关Skills',value='小市值 半路 补涨 情绪修复',key='skills_test_query_8501')
            st.text_area('检索到的Skills上下文',value=build_skills_context(q),height=330)
    with tab4:
        if st.button('更新Skill表现统计',type='primary',key=f'skills_update_stats_{app_name}'):
            df,msg=update_skill_stats_v8_3(); st.success(msg)
        stats=read_csv_safe(SKILL_STATS_PATH)
        if not stats.empty: st.dataframe(stats,hide_index=True,use_container_width=True,height=360)
        else: st.info('暂无Skill统计。先运行 v8.2 / v8.2.1 信号效果统计。')
        if PERFORMANCE_MD.exists():
            with st.expander('Skill表现摘要',expanded=True): st.markdown(PERFORMANCE_MD.read_text(encoding='utf-8'))

ensure_default_skills()
