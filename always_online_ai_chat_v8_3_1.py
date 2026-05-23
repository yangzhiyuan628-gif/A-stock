# -*- coding: utf-8 -*-
"""
always_online_ai_chat_v8_3_1.py

v8.3.1：大模型问股 / 对话机器人联网开关常开版

目标：
1. 大模型问股里的“联网搜索 / 允许联网 / 网页搜索 / 本地网址搜索”默认常开；
2. 用户不需要每次手动打开；
3. 如果页面原来有开关，则显示为已开启并禁用，避免误关；
4. 尽量不影响其他普通复选框；
5. 兼容 st.checkbox / st.toggle / st.session_state 三类写法。

说明：
- 这里的“联网”指你本地项目中已有的联网搜索逻辑。
- 本补丁不会凭空实现新的搜索引擎，只负责把原来的联网开关保持开启。
"""

from __future__ import annotations

import os
import re
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
    "web search",
    "online search",
    "internet",
    "browser",
    "browse",
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
    "联网",
    "网页",
    "网址",
    "搜索",
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


def force_online_switches() -> None:
    """
    每轮渲染时把 session_state 里疑似联网开关的值强制设为 True。
    """
    try:
        for k in list(st.session_state.keys()):
            if _is_online_label(k, k):
                # 避免把文本输入框误改成 True：只强制布尔值或空值
                v = st.session_state.get(k)
                if isinstance(v, bool) or v is None:
                    st.session_state[k] = True
    except Exception:
        pass

    # 同时写入环境变量，给项目其他模块读取
    os.environ["AI_CHAT_WEB_SEARCH_ALWAYS_ON"] = "1"
    os.environ["AI_WEB_SEARCH_ALWAYS_ON"] = "1"
    os.environ["ENABLE_WEB_SEARCH"] = "1"


def install_always_online_patch() -> None:
    """
    Monkey patch Streamlit 的 checkbox/toggle。
    只要 label/key 命中“联网/网页搜索/本地网址”等关键词，就：
    - value 强制 True
    - disabled 强制 True
    - 返回 True
    """
    if getattr(st, "_stock_robot_always_online_patch_v831", False):
        force_online_switches()
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
                    help=(help or "v8.3.1 已设置为常开：大模型问股默认允许联网/网页搜索。"),
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
                        help=(help or "v8.3.1 已设置为常开：大模型问股默认允许联网/网页搜索。"),
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

    st._stock_robot_always_online_patch_v831 = True
    force_online_switches()


def render_always_online_status_panel() -> None:
    """
    可选状态提示面板。
    """
    force_online_switches()
    with st.expander("联网搜索状态 v8.3.1", expanded=False):
        st.success("大模型问股的联网/网页搜索开关已设置为常开。")
        st.caption("如果模型仍然无法联网，说明问题不在开关，而在搜索接口/API/代理配置。")
        rows = []
        try:
            for k, v in st.session_state.items():
                if _is_online_label(k, k):
                    rows.append({"key": k, "value": v})
        except Exception:
            rows = []
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
