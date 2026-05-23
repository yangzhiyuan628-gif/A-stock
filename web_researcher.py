# -*- coding: utf-8 -*-
"""
网页/本地搜索接入模块。

支持三类来源：
1. 用户输入的具体 URL，例如公司官网、公告页、东方财富个股页；
2. 本地搜索服务 LOCAL_SEARCH_ENDPOINT，例如：
   http://127.0.0.1:8000/search?q={query}
   返回 JSON: [{"title":"...", "url":"...", "content":"..."}]
3. Tavily 搜索 API，可选：
   TAVILY_API_KEY=xxxx

注意：
- 不抓取需要登录、验证码或付费的内容；
- 不编造搜索结果；
- 结果只作为大模型上下文。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote

import requests


def _clean_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()
        text = soup.get_text("\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_url_text(url: str, timeout: int = 12) -> tuple[bool, str, str]:
    url = (url or "").strip()
    if not url:
        return False, "", "URL为空。"

    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 stock-robot-research/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "application/pdf" in ctype:
            return False, "", "该URL是PDF，请先下载后走PDF上传。"
        text = _clean_html(r.text)
        title = url
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip() or url
        return True, title, text[:20000]
    except Exception as exc:
        return False, url, f"抓取失败：{type(exc).__name__}: {exc}"


def local_search(query: str, limit: int = 6) -> list[dict]:
    endpoint = os.getenv("LOCAL_SEARCH_ENDPOINT", "").strip()
    if not endpoint:
        return []

    url = endpoint.replace("{query}", quote(query))
    if "{limit}" in url:
        url = url.replace("{limit}", str(limit))

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            data = data.get("results") or data.get("data") or []
        out = []
        for item in data[:limit]:
            if not isinstance(item, dict):
                continue
            out.append({
                "title": str(item.get("title") or item.get("name") or ""),
                "url": str(item.get("url") or item.get("link") or ""),
                "content": str(item.get("content") or item.get("snippet") or item.get("text") or "")[:3000],
                "source": "LOCAL_SEARCH_ENDPOINT",
            })
        return out
    except Exception as exc:
        return [{"title": "本地搜索失败", "url": endpoint, "content": f"{type(exc).__name__}: {exc}", "source": "LOCAL_SEARCH_ENDPOINT"}]


def tavily_search(query: str, limit: int = 6) -> list[dict]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []

    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": limit,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        out = []
        for item in results[:limit]:
            out.append({
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "content": str(item.get("content") or "")[:3000],
                "source": "Tavily",
            })
        return out
    except Exception as exc:
        return [{"title": "Tavily搜索失败", "url": "", "content": f"{type(exc).__name__}: {exc}", "source": "Tavily"}]


def search_web_context(query: str, limit: int = 6) -> str:
    results = []
    results.extend(local_search(query, limit=limit))
    if not results:
        results.extend(tavily_search(query, limit=limit))

    if not results:
        return (
            "未配置可用的联网搜索源。可配置 LOCAL_SEARCH_ENDPOINT 或 TAVILY_API_KEY。\n"
            "LOCAL_SEARCH_ENDPOINT 示例：http://127.0.0.1:8000/search?q={query}"
        )

    parts = []
    for r in results[:limit]:
        parts.append(
            f"【网页结果】{r.get('title','')}\n"
            f"来源: {r.get('source','')}\n"
            f"URL: {r.get('url','')}\n"
            f"摘要: {r.get('content','')}"
        )
    return "\n\n".join(parts)
