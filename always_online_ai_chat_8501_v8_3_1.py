# -*- coding: utf-8 -*-
"""
always_online_ai_chat_8501_v8_3_1.py

v8.3.1：8501 AI游资复盘 / 对话机器人 联网开关常开版

目标：
1. 8501 的 AI游资复盘、问股、聊天机器人中，“联网搜索 / 允许联网 / 网页搜索 / 本地网址搜索”默认常开；
2. 用户不用每次手动打开；
3. 如果页面原来有开关，则显示为已开启并禁用，避免误关；
4. 兼容 st.checkbox / st.toggle / st.session_state；
5. 同时写入环境变量，让底层搜索/联网模块可直接读取。

说明：
- 这里的“联网”指你本地项目里已有的搜索逻辑或联网问答逻辑；
- 该补丁不新增搜索引擎，只负责把原有联网开关保持开启；
- 如果 API 本身或网络代理不通，仍然需要单独修复网络/API。
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st


ONLINE_LABEL_KEYWORDS = [
    "联网",
    "网页搜索",
    "网络搜索",
    "网上搜索",
    "在线搜索",
    "本地网址",
    "访问网址",
    "访问网页",
    "搜索网上",
    "搜索新闻",
    "新闻检索",
    "公司新闻",
    "实时新闻",
    "公告搜索",
    "web search",
    "online search",
    "internet",
    "browser",
    "browse",
    "search news",
]

ONLINE_KEY_KEYWORDS = [
    "web",
    "online",
    "internet",
    "browse",
    "browser",
    "search_web",
    "web_search",
    "enable_web",
    "use_web",
    "news_search",
    "联网",
    "网页",
    "网址",
    "搜索",
    "新闻",
]

NEGATIVE_KEYWORDS = [
    "不联网",
    "关闭联网",
    "禁用联网",
    "disable",
]


def _contains_any(text: Any, words: list[str]) -> bool:
    s = str(text or "").lower()
    return any(str(w).lower() in s for w in words)


def _is_online_label(label: Any, key: Any = None) -> bool:
    text = f"{label or ''} {key or ''}"
    if _contains_any(text, NEGATIVE_KEYWORDS):
        return False
    return _contains_any(text, ONLINE_LABEL_KEYWORDS) or _contains_any(text, ONLINE_KEY_KEYWORDS)


def force_online_switches_8501() -> None:
    """
    每轮渲染时，把 session_state 里疑似联网/新闻/网页搜索开关强制设为 True。
    """
    try:
        for k in list(st.session_state.keys()):
            if _is_online_label(k, k):
                v = st.session_state.get(k)
                # 只强制布尔型，避免把文本输入框误改成 True
                if isinstance(v, bool) or v is None:
                    st.session_state[k] = True
    except Exception:
        pass

    # 给底层模块读取
    os.environ["AI_CHAT_WEB_SEARCH_ALWAYS_ON"] = "1"
    os.environ["AI_WEB_SEARCH_ALWAYS_ON"] = "1"
    os.environ["ENABLE_WEB_SEARCH"] = "1"
    os.environ["ENABLE_NEWS_SEARCH"] = "1"
    os.environ["ENABLE_COMPANY_NEWS_SEARCH"] = "1"
    os.environ["AI_YOUZHI_ONLINE_ALWAYS_ON"] = "1"


def install_always_online_patch_8501() -> None:
    """
    Monkey patch Streamlit checkbox/toggle。

    命中“联网/网页搜索/新闻搜索/本地网址”等关键词时：
    - value 强制 True
    - disabled 强制 True
    - 返回 True
    """
    if getattr(st, "_stock_robot_always_online_patch_8501_v831", False):
        force_online_switches_8501()
        return

    old_checkbox = st.checkbox
    old_toggle = getattr(st, "toggle", None)

    def patched_checkbox(label, value=False, key=None, help=None, on_change=None, args=None, kwargs=None, *, disabled=False, label_visibility="visible"):
        if _is_online_label(label, key):
            if key is not None:
                try:
                    st.session_state[key] = True
                except Exception:
                    pass
            try:
                old_checkbox(
                    label,
                    value=True,
                    key=key,
                    help=(help or "v8.3.1 已设置为常开：8501 AI游资复盘默认允许联网/新闻/网页搜索。"),
                    on_change=on_change,
                    args=args,
                    kwargs=kwargs,
                    disabled=True,
                    label_visibility=label_visibility,
                )
            except TypeError:
                try:
                    old_checkbox(label, value=True, key=key, help=help, disabled=True)
                except Exception:
                    pass
            return True

        return old_checkbox(
            label,
            value=value,
            key=key,
            help=help,
            on_change=on_change,
            args=args,
            kwargs=kwargs,
            disabled=disabled,
            label_visibility=label_visibility,
        )

    def patched_toggle(label, value=False, key=None, help=None, on_change=None, args=None, kwargs=None, *, disabled=False, label_visibility="visible"):
        if _is_online_label(label, key):
            if key is not None:
                try:
                    st.session_state[key] = True
                except Exception:
                    pass

            if old_toggle is not None:
                try:
                    old_toggle(
                        label,
                        value=True,
                        key=key,
                        help=(help or "v8.3.1 已设置为常开：8501 AI游资复盘默认允许联网/新闻/网页搜索。"),
                        on_change=on_change,
                        args=args,
                        kwargs=kwargs,
                        disabled=True,
                        label_visibility=label_visibility,
                    )
                except TypeError:
                    try:
                        old_toggle(label, value=True, key=key, help=help, disabled=True)
                    except Exception:
                        pass
            else:
                try:
                    old_checkbox(label, value=True, key=key, help=help, disabled=True)
                except Exception:
                    pass
            return True

        if old_toggle is not None:
            return old_toggle(
                label,
                value=value,
                key=key,
                help=help,
                on_change=on_change,
                args=args,
                kwargs=kwargs,
                disabled=disabled,
                label_visibility=label_visibility,
            )
        return old_checkbox(label, value=value, key=key, help=help, disabled=disabled)

    st.checkbox = patched_checkbox
    if old_toggle is not None:
        st.toggle = patched_toggle

    st._stock_robot_always_online_patch_8501_v831 = True
    force_online_switches_8501()


def render_always_online_status_panel_8501() -> None:
    """
    可选状态提示面板。
    """
    force_online_switches_8501()
    with st.expander("8501 联网搜索状态 v8.3.1", expanded=False):
        st.success("8501 AI游资复盘 / 问股机器人的联网、新闻、网页搜索开关已设置为常开。")
        st.caption("如果大模型仍无法联网，通常是搜索接口、API联网能力、代理或网络连接问题，不是开关问题。")
        rows = []
        try:
            for k, v in st.session_state.items():
                if _is_online_label(k, k):
                    rows.append({"key": k, "value": v})
        except Exception:
            rows = []
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
