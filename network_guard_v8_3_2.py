
# -*- coding: utf-8 -*-
from __future__ import annotations
import os,json,time,traceback
from datetime import datetime
from pathlib import Path
import requests, streamlit as st
ROOT=Path(__file__).resolve().parent; CONFIG_DIR=ROOT/'config'; LOG_DIR=ROOT/'logs'; REPORT_DIR=ROOT/'reports'
for d in (CONFIG_DIR,LOG_DIR,REPORT_DIR): d.mkdir(exist_ok=True)
CONFIG_PATH=CONFIG_DIR/'network_guard_v8_3_2.json'; ERROR_LOG=LOG_DIR/'network_errors.log'; DIAG_REPORT=REPORT_DIR/'network_diagnose_v8_3_2.json'
DEFAULT_CONFIG={'enabled':True,'patch_requests':True,'retry_times':3,'retry_sleep_seconds':1.5,'timeout_seconds':90,'disable_proxy_for_ai_api':False,'deepseek_base_url':'https://api.deepseek.com','openai_base_url':'https://api.openai.com','search_test_url':'https://www.baidu.com','log_errors':True}
def load_env_files():
    for name in ['.env','.env.watch','.env.local']:
        p=ROOT/name
        if p.exists():
            for line in p.read_text(encoding='utf-8',errors='ignore').splitlines():
                line=line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
def load_config():
    cfg=dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try: cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))
        except Exception: pass
    load_env_files(); return cfg
def save_config(cfg): CONFIG_PATH.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
def log_error(where,exc,extra=None):
    if not load_config().get('log_errors',True): return
    rec={'time':datetime.now().strftime('%F %T'),'where':where,'error_type':type(exc).__name__,'error':str(exc),'extra':extra or {},'traceback':traceback.format_exc()}
    try:
        with ERROR_LOG.open('a',encoding='utf-8') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
    except Exception: pass
def proxy_env_snapshot():
    keys=['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy']
    return {k:os.environ.get(k,'') for k in keys if os.environ.get(k,'')}
def clear_proxy_env():
    for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']: os.environ.pop(k,None)
    os.environ['NO_PROXY']='localhost,127.0.0.1,api.deepseek.com,api.openai.com,82.push2.eastmoney.com'
def test_url(url,timeout=15,no_proxy=False):
    t=time.time()
    try:
        if no_proxy:
            s=requests.Session(); s.trust_env=False; r=s.get(url,timeout=timeout)
        else: r=requests.get(url,timeout=timeout)
        return {'url':url,'mode':'no_proxy' if no_proxy else 'normal','ok':True,'status_code':r.status_code,'elapsed':round(time.time()-t,3),'sample':getattr(r,'text','')[:120]}
    except Exception as e:
        log_error('test_url',e,{'url':url,'no_proxy':no_proxy}); return {'url':url,'mode':'no_proxy' if no_proxy else 'normal','ok':False,'elapsed':round(time.time()-t,3),'error':f'{type(e).__name__}: {e}'}
def run_network_diagnose():
    cfg=load_config(); res={'time':datetime.now().strftime('%F %T'),'proxy_env':proxy_env_snapshot(),'api_key_exists':{k:bool(os.getenv(k)) for k in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','AI_API_KEY']},'tests':[]}
    for url in [cfg.get('deepseek_base_url'),cfg.get('openai_base_url'),cfg.get('search_test_url')]:
        if url: res['tests'].append(test_url(str(url).rstrip('/'),15,False)); res['tests'].append(test_url(str(url).rstrip('/'),15,True))
    DIAG_REPORT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8'); return res
def _retry_url(url):
    s=str(url); return '/chat/completions' in s or 'api.deepseek.com' in s or 'api.openai.com' in s or 'backend-api' in s
def install_network_guard_patch():
    cfg=load_config()
    if not cfg.get('enabled',True) or not cfg.get('patch_requests',True) or getattr(requests,'_stock_robot_network_guard_v832',False): return
    old=requests.sessions.Session.request
    def patched(self,method,url,**kw):
        c=load_config()
        if _retry_url(url):
            kw.setdefault('timeout',int(c.get('timeout_seconds',90)))
            if c.get('disable_proxy_for_ai_api',False):
                try: self.trust_env=False
                except Exception: pass
            last=None
            for i in range(max(1,int(c.get('retry_times',3)))):
                try: return old(self,method,url,**kw)
                except Exception as e:
                    last=e; log_error('requests_retry',e,{'url':str(url),'attempt':i+1,'method':method})
                    if i<int(c.get('retry_times',3))-1: time.sleep(float(c.get('retry_sleep_seconds',1.5))*(i+1))
            raise last
        return old(self,method,url,**kw)
    requests.sessions.Session.request=patched; requests._stock_robot_network_guard_v832=True
def render_network_guard_panel(app_name='unknown'):
    cfg=load_config(); st.subheader(f'v8.3.2 网络/API稳定层（{app_name}）'); st.caption('诊断 DeepSeek/OpenAI、搜索接口、代理变量，并为API请求自动重试。')
    with st.expander('网络稳定层设置',expanded=False):
        c1,c2,c3,c4=st.columns(4)
        with c1: cfg['enabled']=st.checkbox('启用Network Guard',value=bool(cfg.get('enabled',True)),key=f'ng_e_{app_name}')
        with c2: cfg['patch_requests']=st.checkbox('API自动重试',value=bool(cfg.get('patch_requests',True)),key=f'ng_p_{app_name}')
        with c3: cfg['retry_times']=st.number_input('重试次数',1,10,int(cfg.get('retry_times',3)),1,key=f'ng_r_{app_name}')
        with c4: cfg['timeout_seconds']=st.number_input('超时秒',10,300,int(cfg.get('timeout_seconds',90)),5,key=f'ng_t_{app_name}')
        cfg['disable_proxy_for_ai_api']=st.checkbox('AI API不继承系统代理 trust_env=False',value=bool(cfg.get('disable_proxy_for_ai_api',False)),key=f'ng_np_{app_name}')
        cfg['deepseek_base_url']=st.text_input('DeepSeek Base URL',value=str(cfg.get('deepseek_base_url')),key=f'ng_ds_{app_name}')
        cfg['search_test_url']=st.text_input('搜索测试URL',value=str(cfg.get('search_test_url')),key=f'ng_s_{app_name}')
        a,b,c=st.columns(3)
        with a:
            if st.button('保存网络设置',key=f'ng_save_{app_name}'): save_config(cfg); install_network_guard_patch(); st.success('已保存')
        with b:
            if st.button('清理当前进程代理变量',key=f'ng_clear_{app_name}'): clear_proxy_env(); st.success('已清理代理变量')
        with c:
            if st.button('运行网络诊断',type='primary',key=f'ng_diag_{app_name}'):
                save_config(cfg); st.session_state[f'ng_res_{app_name}']=run_network_diagnose()
    res=st.session_state.get(f'ng_res_{app_name}')
    if res: st.json(res)
    elif proxy_env_snapshot(): st.warning('检测到代理变量：'+json.dumps(proxy_env_snapshot(),ensure_ascii=False))
    else: st.info('当前进程未检测到 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY。')
    if ERROR_LOG.exists():
        with st.expander('最近网络错误日志',expanded=False): st.code('\n'.join(ERROR_LOG.read_text(encoding='utf-8',errors='ignore').splitlines()[-50:]) or '暂无')
