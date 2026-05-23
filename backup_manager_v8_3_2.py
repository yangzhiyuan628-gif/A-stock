
# -*- coding: utf-8 -*-
from __future__ import annotations
import json,zipfile
from datetime import datetime
from pathlib import Path
import streamlit as st
ROOT=Path(__file__).resolve().parent; BACKUP_DIR=ROOT/'backups'; BACKUP_DIR.mkdir(exist_ok=True); HISTORY_PATH=BACKUP_DIR/'backup_history.json'
INCLUDE_SUFFIX={'.py','.json','.md','.txt','.csv','.toml','.yaml','.yml'}; INCLUDE_DIRS={'config','skills','reports'}; EXCLUDE={'__pycache__','.venv','venv','site-packages','backups'}
def should_include(p):
    rel=p.relative_to(ROOT)
    if p.is_dir() or p.suffix.lower() not in INCLUDE_SUFFIX or set(rel.parts)&EXCLUDE: return False
    return (len(rel.parts)==1 and p.suffix.lower()=='.py') or (rel.parts and rel.parts[0] in INCLUDE_DIRS)
def load_history():
    if not HISTORY_PATH.exists(): return []
    try:
        x=json.loads(HISTORY_PATH.read_text(encoding='utf-8')); return x if isinstance(x,list) else []
    except Exception: return []
def save_history(h): HISTORY_PATH.write_text(json.dumps(h,ensure_ascii=False,indent=2),encoding='utf-8')
def create_backup(label=''):
    ts=datetime.now().strftime('%Y%m%d_%H%M%S'); safe=''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in label.strip())[:40]
    out=BACKUP_DIR/(f'backup_{ts}'+(f'_{safe}' if safe else '')+'.zip')
    files=[p for p in ROOT.rglob('*') if should_include(p)]
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as zf:
        for p in files: zf.write(p,arcname=str(p.relative_to(ROOT)))
    hist=load_history(); hist.append({'time':datetime.now().strftime('%F %T'),'file':str(out.relative_to(ROOT)),'label':label,'file_count':len(files),'size_mb':round(out.stat().st_size/1024/1024,3)})
    save_history(hist[-200:]); return out
def restore_backup(zip_path):
    zip_path=Path(zip_path)
    if not zip_path.exists(): return False,f'备份不存在：{zip_path}'
    safety=create_backup('before_restore')
    try:
        with zipfile.ZipFile(zip_path,'r') as zf: zf.extractall(ROOT)
        return True,f'已恢复 {zip_path.name}；恢复前安全备份：{safety.name}'
    except Exception as e: return False,f'恢复失败：{type(e).__name__}: {e}'
def cleanup_bak_files():
    n=0
    for p in ROOT.rglob('*.bak*'):
        if 'backups' in p.parts: continue
        try: p.unlink(); n+=1
        except Exception: pass
    return n
_auto=False
def auto_backup_once_v8_3_2(label='auto_before_v832'):
    global _auto
    if _auto: return
    try: create_backup(label); _auto=True
    except Exception: pass
def render_backup_manager_panel():
    st.subheader('v8.3.2 一键备份 / 回滚'); st.caption('每次大改前先备份，避免误删和补丁写坏。')
    label=st.text_input('备份备注',value='manual',key='backup_label_v832'); c1,c2,c3=st.columns(3)
    with c1:
        if st.button('立即备份',type='primary',key='backup_now_v832'): st.success(f'备份完成：{create_backup(label).name}')
    with c2:
        if st.button('清理散落 .bak 文件',key='backup_clean_v832'): st.success(f'已清理 {cleanup_bak_files()} 个 .bak 文件')
    with c3:
        if st.button('刷新备份列表',key='backup_refresh_v832'): st.rerun()
    hist=load_history()
    if hist:
        st.dataframe(hist[::-1],hide_index=True,use_container_width=True,height=260); files=[h['file'] for h in hist if (ROOT/h['file']).exists()]
        if files:
            sel=st.selectbox('选择要恢复的备份',files[::-1],key='backup_restore_sel_v832'); st.warning('恢复会覆盖当前 py/config/skills/reports 文件。恢复前会自动再做一次安全备份。')
            if st.button('恢复所选备份',key='backup_restore_btn_v832'):
                ok,msg=restore_backup(ROOT/sel); st.success(msg) if ok else st.error(msg)
    else: st.info('暂无备份历史。')
