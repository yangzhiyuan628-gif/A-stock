# -*- coding: utf-8 -*-
"""
shared_image_vision.py

给同一目录下的两个系统共用：
- 8501：短线打板机器人 / AI游资复盘
- 8502：A股主板非ST实盘监控 / 大模型问股

功能：
1. 共用一个图片库：uploads/shared_chat_images
2. 在聊天机器人页面上传、选择、预览图片
3. 自动把已选图片注入 OpenAI-compatible /chat/completions 请求
4. 支持图片：png/jpg/jpeg/webp
5. 如果模型不支持视觉输入，可以关闭“把图片传给模型”

说明：
- 这不是 OCR。它是把图片以 image_url data URL 形式传给支持视觉的模型。
- 如果 DeepSeek 当前模型不支持图片，会返回模型/API错误；此时页面仍能上传/预览，但模型看不了图。
"""

from __future__ import annotations

import base64
import copy
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
import streamlit as st


ROOT = Path(__file__).resolve().parent
IMAGE_DIR = ROOT / "uploads" / "shared_chat_images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_INJECT_IMAGES = 4


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem).strip("_")
    return (stem or "image") + suffix


def _ns(namespace: str) -> str:
    namespace = namespace or "default"
    return re.sub(r"[^a-zA-Z0-9_]+", "_", namespace)


def selected_key(namespace: str) -> str:
    return f"shared_vision_{_ns(namespace)}_selected"


def send_key(namespace: str) -> str:
    return f"shared_vision_{_ns(namespace)}_send"


def prompt_key(namespace: str) -> str:
    return f"shared_vision_{_ns(namespace)}_prompt"


def list_shared_images() -> list[dict[str, Any]]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(IMAGE_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        rows.append({
            "label": f"{p.name} | {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p.stat().st_mtime))}",
            "name": p.name,
            "path": str(p),
            "size_kb": round(p.stat().st_size / 1024, 1),
            "mtime": p.stat().st_mtime,
        })
    return rows


def save_uploaded_images(files, prefix: str = "") -> list[dict[str, Any]]:
    saved = []
    if not files:
        return saved

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    prefix = _ns(prefix) if prefix else "img"

    for f in files:
        suffix = Path(f.name).suffix.lower()
        if suffix not in IMAGE_EXTS:
            continue

        filename = _safe_name(f.name)
        out_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{prefix}_{filename}"
        out = IMAGE_DIR / out_name

        i = 1
        while out.exists():
            out = IMAGE_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{prefix}_{i}_{filename}"
            i += 1

        out.write_bytes(f.getvalue())
        saved.append({
            "name": out.name,
            "path": str(out),
            "size_kb": round(out.stat().st_size / 1024, 1),
        })

    return saved


def get_selected_image_paths(namespace: str) -> list[str]:
    key = selected_key(namespace)
    selected = st.session_state.get(key, [])
    rows = {r["label"]: r for r in list_shared_images()}

    paths = []
    for label in selected:
        row = rows.get(label)
        if row and Path(row["path"]).exists():
            paths.append(row["path"])

    return paths[:MAX_INJECT_IMAGES]


def get_all_active_image_paths() -> list[str]:
    """
    供 monkey patch 使用：
    只要某个命名空间勾选了“把图片传给模型”，就把该命名空间选中的图片注入请求。
    """
    paths = []
    try:
        for k, v in list(st.session_state.items()):
            if not k.startswith("shared_vision_") or not k.endswith("_send"):
                continue
            if not bool(v):
                continue

            namespace = k[len("shared_vision_"):-len("_send")]
            sel_key = f"shared_vision_{namespace}_selected"
            selected = st.session_state.get(sel_key, [])

            rows = {r["label"]: r for r in list_shared_images()}
            for label in selected:
                row = rows.get(label)
                if row and Path(row["path"]).exists():
                    paths.append(row["path"])
    except Exception:
        return []

    # 去重且最多4张，避免请求过大
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[:MAX_INJECT_IMAGES]


def image_to_data_url(path: str, max_size: int = 1600, jpeg_quality: int = 85) -> str:
    p = Path(path)

    try:
        from PIL import Image
        import io

        im = Image.open(p)
        im.thumbnail((max_size, max_size))
        buf = io.BytesIO()

        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            im.save(buf, format="PNG")
            mime = "image/png"
        else:
            im = im.convert("RGB")
            im.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
            mime = "image/jpeg"

        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"


def make_vision_content(text: str, image_paths: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            text
            + "\n\n【图片输入】用户在聊天界面选择了图片。"
            + "请先观察图片中可见的信息，再结合行情、PDF/网页资料和上下文回答。"
        ),
    }]

    for p in image_paths[:MAX_INJECT_IMAGES]:
        try:
            content.append({
                "type": "image_url",
                "image_url": {"url": image_to_data_url(p)},
            })
        except Exception as exc:
            content[0]["text"] += f"\n图片读取失败：{Path(p).name}: {exc}"

    return content


def inject_images_into_messages(messages: Any, image_paths: list[str]) -> Any:
    if not image_paths:
        return messages
    if not isinstance(messages, list):
        return messages

    new_messages = copy.deepcopy(messages)

    # 找最后一个 user message
    target = None
    for msg in reversed(new_messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            target = msg
            break

    if target is None:
        return new_messages

    content = target.get("content", "")

    if isinstance(content, str):
        target["content"] = make_vision_content(content, image_paths)
        return new_messages

    if isinstance(content, list):
        # 已经是多模态格式，追加图片
        has_note = any(isinstance(x, dict) and x.get("type") == "text" for x in content)
        if not has_note:
            content.insert(0, {"type": "text", "text": "请结合用户选择的图片进行分析。"})
        else:
            # 给第一段文字加提示
            for x in content:
                if isinstance(x, dict) and x.get("type") == "text":
                    x["text"] = str(x.get("text", "")) + "\n\n【图片输入】请结合用户选择的图片进行分析。"
                    break

        for p in image_paths[:MAX_INJECT_IMAGES]:
            try:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_to_data_url(p)},
                })
            except Exception:
                pass

        target["content"] = content
        return new_messages

    return new_messages


def install_shared_vision_patch(app_name: str = "") -> None:
    """
    非侵入式补丁：
    - 拦截 requests.post
    - 如果请求是 /chat/completions 且存在 messages
    - 自动把当前页面已选图片注入到最后一个 user message

    这样 8501 和 8502 可以共用同一个图片库和同一套逻辑。
    """
    if getattr(requests, "_stock_robot_shared_vision_patch", False):
        return

    old_post = requests.post

    def patched_post(url, *args, **kwargs):
        try:
            json_payload = kwargs.get("json", None)
            if isinstance(json_payload, dict):
                url_s = str(url)
                looks_like_chat = (
                    "/chat/completions" in url_s
                    or ("messages" in json_payload and "model" in json_payload)
                )

                if looks_like_chat and "messages" in json_payload:
                    image_paths = get_all_active_image_paths()
                    if image_paths:
                        new_payload = copy.deepcopy(json_payload)
                        new_payload["messages"] = inject_images_into_messages(new_payload.get("messages"), image_paths)
                        kwargs["json"] = new_payload
        except Exception:
            pass

        return old_post(url, *args, **kwargs)

    requests.post = patched_post
    requests._stock_robot_shared_vision_patch = True


def render_shared_image_panel(namespace: str = "default", title: str = "图片资料 / 视觉输入", expanded: bool = False) -> None:
    """
    在聊天机器人 Tab 内调用。
    8501 namespace 建议：ai_youzhi
    8502 namespace 建议：watch_ai
    """
    namespace = _ns(namespace)

    with st.expander(title, expanded=expanded):
        st.caption(
            "两个系统共用图片库：uploads/shared_chat_images。"
            "可以上传K线、分时、公告、新闻、财报、软件报错等截图。"
            "模型能否真正看图，取决于你接入的模型是否支持 vision/image_url。"
        )

        files = st.file_uploader(
            "上传图片",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key=f"shared_vision_{namespace}_uploader",
        )

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            if st.button("保存上传图片", key=f"shared_vision_{namespace}_save"):
                saved = save_uploaded_images(files, prefix=namespace)
                if saved:
                    st.success(f"已保存 {len(saved)} 张图片。")
                    st.rerun()
                else:
                    st.warning("没有保存图片。请先选择 png/jpg/jpeg/webp。")

        rows = list_shared_images()
        labels = [r["label"] for r in rows]
        current = st.session_state.get(selected_key(namespace), [])
        current = [x for x in current if x in labels]

        st.multiselect(
            "本轮问答要让模型查看的图片，最多 4 张",
            options=labels,
            default=current[:MAX_INJECT_IMAGES],
            key=selected_key(namespace),
        )

        with c2:
            st.checkbox(
                "把图片传给模型",
                value=st.session_state.get(send_key(namespace), True),
                key=send_key(namespace),
                help="如果当前模型不支持图片输入，请关闭。关闭后只能上传/预览图片，模型看不到图片内容。",
            )

        with c3:
            if st.button("删除已选图片", key=f"shared_vision_{namespace}_delete"):
                for p in get_selected_image_paths(namespace):
                    try:
                        Path(p).unlink()
                    except Exception:
                        pass
                st.session_state[selected_key(namespace)] = []
                st.rerun()

        selected_paths = get_selected_image_paths(namespace)
        if selected_paths:
            st.markdown("**已选择图片预览**")
            cols = st.columns(min(MAX_INJECT_IMAGES, len(selected_paths)))
            for i, p in enumerate(selected_paths[:MAX_INJECT_IMAGES]):
                with cols[i]:
                    st.image(p, caption=Path(p).name, use_container_width=True)

        if rows:
            with st.expander("共用图片库列表", expanded=False):
                import pandas as pd
                st.dataframe(
                    pd.DataFrame(rows)[["name", "size_kb", "path"]],
                    hide_index=True,
                    use_container_width=True,
                    height=180,
                )

        st.info(
            "用法示例：上传分时图后问“结合这张分时图和当前盯盘数据，这个票能不能半路？”"
            "如果报模型不支持图片，请换视觉模型或关闭“把图片传给模型”。"
        )
