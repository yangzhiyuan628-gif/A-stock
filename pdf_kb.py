# -*- coding: utf-8 -*-
"""
PDF / 文本知识库，SQLite + 简单检索版。

不是微调模型，而是 RAG：
1. 上传 PDF；
2. 抽取文字；
3. 切块存入本地 SQLite；
4. 大模型回答时先检索相关片段，再把片段作为上下文给模型。

数据库：
    data/pdf_web_kb.sqlite3
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "pdf_web_kb.sqlite3"


def connect(db_path: Path = DB_PATH):
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE,
            title TEXT,
            source_type TEXT,
            source_path TEXT,
            created_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT,
            title TEXT,
            source_type TEXT,
            source_path TEXT,
            chunk_index INTEGER,
            text TEXT,
            created_at TEXT
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id)")
        conn.commit()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:24]


def _clean_text(text: str) -> str:
    text = text or ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    # 优先按段落切
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= chunk_size:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= chunk_size:
                buf = p
            else:
                start = 0
                while start < len(p):
                    chunks.append(p[start:start + chunk_size])
                    start += max(1, chunk_size - overlap)
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """
    优先 pypdf，失败时尝试 PyPDF2。
    """
    import io

    errors = []

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(f"\n\n[Page {i+1}]\n" + (page.extract_text() or ""))
            except Exception as exc:
                parts.append(f"\n\n[Page {i+1}] 抽取失败：{exc}")
        return _clean_text("\n".join(parts))
    except Exception as exc:
        errors.append(f"pypdf失败: {exc}")

    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(f"\n\n[Page {i+1}]\n" + (page.extract_text() or ""))
            except Exception as exc:
                parts.append(f"\n\n[Page {i+1}] 抽取失败：{exc}")
        return _clean_text("\n".join(parts))
    except Exception as exc:
        errors.append(f"PyPDF2失败: {exc}")

    raise RuntimeError("无法抽取PDF文字。请安装：pip install pypdf。详情：" + " | ".join(errors))


def add_text_document(title: str, text: str, source_type: str = "text", source_path: str = "") -> tuple[bool, str]:
    init_db()
    text = _clean_text(text)
    if not text:
        return False, "文本为空，未导入。"

    doc_id = hashlib.sha256((title + source_type + source_path + text[:5000]).encode("utf-8", errors="ignore")).hexdigest()[:24]
    chunks = _chunk_text(text)
    if not chunks:
        return False, "未能生成有效文本块。"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO documents (doc_id, title, source_type, source_path, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (doc_id, title, source_type, source_path, now))
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        for i, ck in enumerate(chunks):
            conn.execute("""
            INSERT INTO chunks (doc_id, title, source_type, source_path, chunk_index, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (doc_id, title, source_type, source_path, i, ck, now))
        conn.commit()
    return True, f"已导入 {title}，切分 {len(chunks)} 个片段。"


def add_pdf_bytes(filename: str, pdf_bytes: bytes) -> tuple[bool, str]:
    init_db()
    if not pdf_bytes:
        return False, "PDF为空。"
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as exc:
        return False, str(exc)

    doc_hash = _hash_bytes(pdf_bytes)
    title = filename or f"PDF-{doc_hash}"
    return add_text_document(title=title, text=text, source_type="pdf", source_path=filename)


def list_documents() -> list[dict]:
    init_db()
    with connect() as conn:
        rows = conn.execute("""
        SELECT d.*, COUNT(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON d.doc_id=c.doc_id
        GROUP BY d.id
        ORDER BY d.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def _tokenize_query(query: str) -> list[str]:
    query = query or ""
    # 股票/中文主题常见无空格；保留原句，同时抽取关键词
    words = []
    for token in re.split(r"[\s,，。；;:：/\\|]+", query):
        token = token.strip()
        if len(token) >= 2:
            words.append(token)
    # 加入常见题材词
    for kw in ["算力", "租赁", "智算", "AI", "人工智能", "数据中心", "主营", "公告", "合同", "业绩", "风险", "首板", "打板"]:
        if kw in query and kw not in words:
            words.append(kw)
    return words[:16]


def search_kb(query: str, top_k: int = 8) -> list[dict]:
    init_db()
    words = _tokenize_query(query)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM chunks ORDER BY created_at DESC LIMIT 2000").fetchall()]

    if not rows:
        return []

    scored = []
    q_lower = (query or "").lower()
    for r in rows:
        text = (r.get("text") or "")
        title = (r.get("title") or "")
        hay = (title + "\n" + text).lower()
        score = 0
        if q_lower and q_lower in hay:
            score += 5
        for w in words:
            if w.lower() in hay:
                score += 2 if len(w) >= 3 else 1
        if score > 0:
            scored.append((score, r))

    if not scored:
        # 没命中时给最近资料，避免空上下文
        return rows[: min(top_k, len(rows))]

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


def kb_context(query: str, top_k: int = 8) -> str:
    rows = search_kb(query, top_k=top_k)
    if not rows:
        return "本地PDF/网页知识库暂无资料。"

    parts = []
    for r in rows:
        parts.append(
            f"【资料片段】{r.get('title','')} | {r.get('source_type','')} | {r.get('source_path','')} | chunk {r.get('chunk_index')}\n"
            f"{(r.get('text') or '')[:1200]}"
        )
    return "\n\n".join(parts)
