from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from network_guard_v8_3_2 import install_network_guard_patch, render_network_guard_panel
from web_research_v8_3_2 import install_web_research_patch, render_web_research_panel
from realtime_logger_v8_3_2 import log_current_snapshot_v8_3_2, render_realtime_logger_panel
from backup_manager_v8_3_2 import auto_backup_once_v8_3_2, render_backup_manager_panel
from always_online_ai_chat_8501_v8_3_1 import install_always_online_patch_8501, force_online_switches_8501, render_always_online_status_panel_8501
from skill_manager_v8_3 import ensure_default_skills, install_skill_context_patch, render_skills_system_panel, enrich_latest_signals_with_skills_v8_3
from smallcap_review_8501_v8_2_2 import render_smallcap_review_8501_panel
from after_review_v8_1 import render_after_review_panel_v8_1
from shared_image_vision import install_shared_vision_patch, render_shared_image_panel
from numeric_sort_display_utils import install_numeric_sort_display_patch
from ai_youzhi_chat_core import render_ai_youzhi_chat

from formatters import format_for_display, preview_unit_examples

install_numeric_sort_display_patch()

install_shared_vision_patch(app_name="8501")

ensure_default_skills()
install_skill_context_patch()

install_always_online_patch_8501()
force_online_switches_8501()

auto_backup_once_v8_3_2('auto_before_v832_8501')
install_network_guard_patch()
install_web_research_patch()

st.set_page_config(page_title="短线打板机器人 8501", layout="wide")

REPORT_DIR = Path("reports")
CONFIG_DIR = Path("config")
CONFIG_DIR.mkdir(exist_ok=True)
TODAY = datetime.now().strftime("%Y%m%d")


def load_csv(name: str) -> pd.DataFrame:
    path = REPORT_DIR / f"{name}_{TODAY}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_json(name: str) -> dict:
    path = REPORT_DIR / f"{name}_{TODAY}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_settings() -> dict:
    path = CONFIG_DIR / "settings.json"
    default = {
        "tdx_watchlist_path": "",
        "refresh_seconds": 60,
        "alert_gain_pct": 7.0,
        "alert_loss_pct": -5.0,
        "near_limit_pct": 8.0,
        "max_table_rows": 200,
        "ai_provider": os.getenv("AI_PROVIDER", "deepseek"),
        "ai_model": os.getenv("AI_MODEL", "deepseek-v4-flash"),
        "ai_base_url": os.getenv("AI_BASE_URL", "https://api.deepseek.com"),
        "ai_report_top_n": 25,
        "ai_report_style": "短线游资复盘，重点看情绪、主线、连板、首板、风险，不给确定性承诺。",
    }
    if path.exists():
        try:
            default.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return default


def save_settings(settings: dict) -> None:
    path = CONFIG_DIR / "settings.json"
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cmd(args: list[str], label: str) -> None:
    with st.spinner(label):
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=os.environ.copy())
        if result.returncode != 0:
            st.error("运行失败")
            st.code(result.stderr or result.stdout)
        else:
            st.success("完成")
            if result.stdout:
                with st.expander("运行日志"):
                    st.code(result.stdout[-4000:])


def run_main() -> None:
    run_cmd([sys.executable, "main.py"], "正在抓取行情并生成报告...")


def run_ai_report() -> None:
    run_cmd([sys.executable, "ai_report.py"], "正在生成 AI 游资复盘...")


def show_table(df: pd.DataFrame, title: str, sort_col: str | None = None, height: int = 520, rows: int | None = None) -> None:
    st.subheader(title)
    if df.empty:
        st.info("暂无数据")
        return
    show_df = df.copy()
    if sort_col and sort_col in show_df.columns:
        show_df = show_df.sort_values(sort_col, ascending=False)
    if rows:
        show_df = show_df.head(rows)
    st.dataframe(format_for_display(show_df), width="stretch", height=height)


settings = load_settings()

with st.sidebar:
    st.title("短线打板机器人 8501｜AI游资复盘")
    if st.button("刷新行情数据", type="primary"):
        run_main()
        st.rerun()

    st.divider()
    st.caption("通达信自选股文件路径，可留空。")
    tdx_path = st.text_input("TDX 自选股 .blk 路径", value=settings.get("tdx_watchlist_path", ""))
    near_limit_pct = st.number_input("接近涨停阈值 %", value=float(settings.get("near_limit_pct", 8.0)), step=0.5)
    alert_gain_pct = st.number_input("强异动阈值 %", value=float(settings.get("alert_gain_pct", 7.0)), step=0.5)
    alert_loss_pct = st.number_input("风险跌幅阈值 %", value=float(settings.get("alert_loss_pct", -5.0)), step=0.5)

    st.divider()
    st.caption("AI 复盘设置。API Key 不会写入 settings.json，仅在本次 Streamlit 会话中传给子进程。")
    provider_options = ["deepseek", "openai"]
    current_provider = str(settings.get("ai_provider", "deepseek")).lower()
    provider_index = provider_options.index(current_provider) if current_provider in provider_options else 0
    ai_provider = st.selectbox("AI 供应商", provider_options, index=provider_index)
    default_model = "deepseek-v4-flash" if ai_provider == "deepseek" else "gpt-5.5"
    saved_model = str(settings.get("ai_model", default_model))
    if ai_provider == "deepseek" and saved_model.startswith("gpt"):
        saved_model = default_model
    ai_model = st.text_input("AI 模型", value=saved_model)
    default_base_url = "https://api.deepseek.com" if ai_provider == "deepseek" else ""
    ai_base_url = st.text_input("AI Base URL", value=str(settings.get("ai_base_url", default_base_url) or default_base_url))
    key_label = "DEEPSEEK_API_KEY" if ai_provider == "deepseek" else "OPENAI_API_KEY"
    api_key_input = st.text_input(key_label, value="", type="password")
    os.environ["AI_PROVIDER"] = ai_provider
    os.environ["AI_MODEL"] = ai_model.strip()
    os.environ["AI_BASE_URL"] = ai_base_url.strip()
    if api_key_input:
        os.environ["AI_API_KEY"] = api_key_input.strip()
        if ai_provider == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = api_key_input.strip()
        else:
            os.environ["OPENAI_API_KEY"] = api_key_input.strip()
    ai_top_n = st.number_input("AI 报告读取 Top N", value=int(settings.get("ai_report_top_n", 25)), min_value=5, max_value=80, step=5)
    ai_style = st.text_area("AI 复盘风格", value=str(settings.get("ai_report_style", "")), height=80)

    if st.button("保存设置"):
        settings.update({
            "tdx_watchlist_path": tdx_path,
            "near_limit_pct": near_limit_pct,
            "alert_gain_pct": alert_gain_pct,
            "alert_loss_pct": alert_loss_pct,
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "ai_base_url": ai_base_url,
            "ai_report_top_n": int(ai_top_n),
            "ai_report_style": ai_style,
        })
        save_settings(settings)
        st.success("设置已保存，点击刷新行情数据后生效")

st.title("短线打板机器人 v5.1+Stable+Online+Stable+Skills+Online+SmallCap+Review+Vision")
st.caption("盘后复盘、AI游资问股、小市值高弹性候选池、Skills技能库。仅做复盘与观察，不做自动交易。")

emotion = load_json("market_emotion")
zt_df = load_csv("zt_pool")
prev_df = load_csv("prev_pool")
sector_df = load_csv("sector_strength")
watch_df = load_csv("watchlist_monitor")
zb_df = load_csv("zbgc_pool")
dt_df = load_csv("dtgc_pool")
strong_df = load_csv("strong_pool")
sub_new_df = load_csv("sub_new_pool")

if not emotion and zt_df.empty:
    st.warning("还没有今日数据。请点击左侧“刷新行情数据”，或在 PowerShell 运行：python main.py")

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("涨停", emotion.get("total_zt", len(zt_df) if not zt_df.empty else 0))
m2.metric("炸板", emotion.get("total_zb", len(zb_df) if not zb_df.empty else 0))
m3.metric("跌停", emotion.get("total_dt", len(dt_df) if not dt_df.empty else 0))
m4.metric("封板率", f"{emotion.get('seal_rate', 0)}%")
m5.metric("连板数", emotion.get("limit_up_chains", 0))
m6.metric("最高板", emotion.get("max_board", 0))

st.info(f"机器人情绪：{emotion.get('mood', '暂无')}｜生成时间：{emotion.get('generated_at', '暂无')}")

tabs = st.tabs([
    "市场总览",
    "今日涨停池",
    "明日连板观察",
    "首板观察池",
    "自选股监控",
    "炸板/跌停",
    "昨日涨停/强势股",
    "AI游资复盘",
    "复盘报告",
    "自选股编辑",
    "单位示例",
])

with tabs[0]:
    show_table(sector_df, "板块强度", height=420)
    st.subheader("明日盘前检查")
    st.markdown(
        """
- 最高板不能出现明显核按钮。
- 主线板块需要继续有批量助攻，不能只剩孤板。
- 炸板数量不能快速扩大，封板率最好维持在 60% 以上。
- 昨日涨停红盘率越高，越适合做首板和一进二；红盘率低则减少接力。
        """
    )

with tabs[1]:
    show_table(zt_df, "今日涨停池", sort_col="机器人评分")

with tabs[2]:
    if not zt_df.empty:
        cols = [c for c in ["代码", "名称", "所属行业", "行业", "连板高度", "首次封板时间", "最后封板时间", "炸板次数", "换手率", "成交额", "流通市值", "总市值", "封板资金", "机器人评分", "机器人标签"] if c in zt_df.columns]
        show_table(zt_df[cols] if cols else zt_df, "明日连板观察 Top", sort_col="机器人评分")
    else:
        st.info("暂无数据")

with tabs[3]:
    if not zt_df.empty and "连板高度" in zt_df.columns:
        first_df = zt_df[zt_df["连板高度"] <= 1]
        show_table(first_df, "首板观察池", sort_col="机器人评分")
    else:
        st.info("暂无首板数据")

with tabs[4]:
    show_table(watch_df, "自选股监控", sort_col="涨跌幅_数值")
    if not watch_df.empty:
        mask = pd.Series(False, index=watch_df.index)
        for col in ["是否涨停", "接近涨停", "强异动", "弱风险"]:
            if col in watch_df.columns:
                mask = mask | (watch_df[col] == True)
        hit = watch_df[mask]
        show_table(hit, "自选股重点提醒", sort_col="涨跌幅_数值", height=300)

with tabs[5]:
    show_table(zb_df, "炸板股池", height=380)
    show_table(dt_df, "跌停股池", height=380)

with tabs[6]:
    show_table(prev_df, "昨日涨停池", height=380)
    show_table(strong_df, "强势股池", height=380)
    show_table(sub_new_df, "次新股池", height=380)

with tabs[7]:
    render_always_online_status_panel_8501()
    render_skills_system_panel(app_name="8501")
    render_smallcap_review_8501_panel()
    render_after_review_panel_v8_1()
    render_shared_image_panel(namespace="ai_youzhi", title="图片资料 / 视觉输入", expanded=False)
    render_ai_youzhi_chat(
        data_candidates=[
            globals().get('df'), globals().get('data'), globals().get('pool'),
            globals().get('today_pool'), globals().get('limit_pool'),
            globals().get('review_df'), globals().get('signal_df'),
            globals().get('limit_up_df'), globals().get('candidates'),
            globals().get('zt_pool'), globals().get('rank_df'), globals().get('watch_df'),
        ],
        market_context=globals(),
    )
with tabs[8]:
    path = REPORT_DIR / f"report_{TODAY}.md"
    if path.exists():
        st.markdown(path.read_text(encoding="utf-8"))
    else:
        st.info("暂无复盘报告，请先刷新数据")

with tabs[9]:
    wl_path = CONFIG_DIR / "watchlist.txt"
    if not wl_path.exists():
        wl_path.write_text("# 每行一个股票代码，也可写：601991 大唐发电\n", encoding="utf-8")
    text = st.text_area("手工自选股 watchlist.txt", value=wl_path.read_text(encoding="utf-8"), height=360)
    if st.button("保存自选股列表"):
        wl_path.write_text(text, encoding="utf-8")
        st.success("已保存。点击左侧刷新行情数据后生效。")
    st.caption("格式示例：601991 大唐发电。也可以在左侧填写通达信 .blk 自选股文件路径。")

with tabs[10]:
    st.subheader("单位格式化示例")
    st.dataframe(preview_unit_examples(), width="stretch")
    st.markdown(
        """
- 金额/市值/资金：自动转为 `万` 或 `亿`。
- 百分比：换手率、涨跌幅、振幅等统一显示 `%`。
- 时间：`92501` 显示为 `09:25:01`，`130033` 显示为 `13:00:33`。
- 原始 CSV 仍保留数值，便于排序和计算；`*_display.csv` 是人工查看版。
        """
    )


# ===== AI游资复盘聊天窗口：自动追加 =====
st.divider()
# ===== end AI游资复盘聊天窗口 =====


# ===== v8.3.1 8501 AI chat always online auto force =====
try:
    force_online_switches_8501()
except Exception:
    pass
# ===== end v8.3.1 8501 AI chat always online auto force =====

# ===== v8.3.2 stability panels 8501 =====
try:
    render_network_guard_panel(app_name='8501')
    render_web_research_panel(app_name='8501')
    render_backup_manager_panel()
except Exception:
    pass
# ===== end v8.3.2 stability panels 8501 =====
