# -*- coding: utf-8 -*-
"""
公司基本面/题材知识库：SQLite 版本

用途：
- 存储公司主业、转型方向、题材标签、风险提示、信息来源；
- AI 游资复盘时自动检索相关公司背景；
- 解决“模型不知道莲花控股是算力租赁”这类问题。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "company_kb.sqlite3"

DEFAULT_COMPANIES = [
    {
        "code": "600186",
        "name": "莲花控股",
        "main_business": "传统主业为调味品/味精等食品调味品业务。",
        "new_business": "公司近年推进算力业务转型，核心方向包括算力服务器租赁、智算中心建设运营、AI算力服务等；相关主体包括莲花科创、莲花紫星等。",
        "themes": "算力租赁,智算中心,AI算力,调味品,食品饮料",
        "shortline_logic": "短线不能只当食品股看，需同时按“算力租赁/AI算力转型”题材识别。若算力板块、AI基础设施、数据中心方向强势，该股可能被资金按算力转型线交易。",
        "risk_notes": "算力业务仍需关注采购交付、合同履约、回款、融资、供应链和监管问询风险；传统主业与算力转型之间存在估值切换不确定性。",
        "source": "用户确认 + 公司公开公告/公开报道；需结合最新公告和新闻实时核验。",
    },
]

def connect(db_path: Path = DB_PATH):
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(seed: bool = True) -> None:
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT,
            main_business TEXT,
            new_business TEXT,
            themes TEXT,
            shortline_logic TEXT,
            risk_notes TEXT,
            source TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        if seed:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for c in DEFAULT_COMPANIES:
                conn.execute("""
                INSERT OR IGNORE INTO company_profiles
                (code, name, main_business, new_business, themes, shortline_logic, risk_notes, source, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    c["code"], c["name"], c["main_business"], c["new_business"], c["themes"],
                    c["shortline_logic"], c["risk_notes"], c["source"], now, now
                ))
        conn.commit()

def add_or_update_company(code: str, name: str, main_business: str = "", new_business: str = "", themes: str = "", shortline_logic: str = "", risk_notes: str = "", source: str = "用户手动添加") -> None:
    init_db(seed=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    code = str(code).zfill(6)[-6:]
    with connect() as conn:
        old = conn.execute("SELECT id, created_at FROM company_profiles WHERE code=? OR name=? LIMIT 1", (code, name)).fetchone()
        if old:
            conn.execute("""
            UPDATE company_profiles
            SET code=?, name=?, main_business=?, new_business=?, themes=?, shortline_logic=?, risk_notes=?, source=?, updated_at=?, enabled=1
            WHERE id=?
            """, (code, name, main_business, new_business, themes, shortline_logic, risk_notes, source, now, old["id"]))
        else:
            conn.execute("""
            INSERT INTO company_profiles
            (code, name, main_business, new_business, themes, shortline_logic, risk_notes, source, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (code, name, main_business, new_business, themes, shortline_logic, risk_notes, source, now, now))
        conn.commit()

def search_company(query: str = "", code: str = "", name: str = "", limit: int = 5) -> list[dict]:
    init_db(seed=True)
    code = str(code or "").zfill(6)[-6:] if code else ""
    name = str(name or "")
    query = str(query or "")

    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM company_profiles WHERE enabled=1").fetchall()]

    scored = []
    for r in rows:
        score = 0
        if code and r.get("code") == code:
            score += 10
        if name and name in str(r.get("name", "")):
            score += 8
        txt = " ".join(str(r.get(k, "")) for k in ["code", "name", "main_business", "new_business", "themes", "shortline_logic", "risk_notes"])
        for token in [query, name, code, "算力", "租赁", "AI", "智算"]:
            if token and token in txt:
                score += 1
        if score > 0:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]

def company_context(rows: list[dict]) -> str:
    if not rows:
        return "本地公司知识库未命中。需要结合实时新闻、公告和个股资料识别公司基本面。"
    parts = []
    for r in rows:
        parts.append(
            f"【{r.get('code','')} {r.get('name','')}】\n"
            f"传统/主营业务: {r.get('main_business','')}\n"
            f"新业务/题材方向: {r.get('new_business','')}\n"
            f"题材标签: {r.get('themes','')}\n"
            f"短线理解: {r.get('shortline_logic','')}\n"
            f"风险提示: {r.get('risk_notes','')}\n"
            f"来源: {r.get('source','')}\n"
        )
    return "\n".join(parts)
