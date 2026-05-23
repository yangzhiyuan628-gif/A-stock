# -*- coding: utf-8 -*-
"""
delete_imported_pdfs.py

删除机器人资料库中已经导入的 PDF/网页资料。

支持数据库：
1. 8502 v7.7 问股资料库：
   data/watch_ai_pdf_web_kb.sqlite3
2. 8501 AI游资复盘资料库：
   data/pdf_web_kb.sqlite3

安全设计：
- 默认只列出，不删除；
- 真正删除必须加 --apply；
- 删除前会自动备份 sqlite3 数据库；
- 只删除数据库中的 documents/chunks 记录，不会删除你的本地原始 PDF 文件。

常用命令：

查看所有已导入资料：
    python delete_imported_pdfs.py --list

查看 8502 资料库：
    python delete_imported_pdfs.py --db data\watch_ai_pdf_web_kb.sqlite3 --list

删除 8502 中所有 PDF 资料：
    python delete_imported_pdfs.py --db data\watch_ai_pdf_web_kb.sqlite3 --source-type pdf --apply

删除 8501 中所有 PDF 资料：
    python delete_imported_pdfs.py --db data\pdf_web_kb.sqlite3 --source-type pdf --apply

按关键词删除：
    python delete_imported_pdfs.py --keyword 莲花控股 --apply

按 doc_id 删除：
    python delete_imported_pdfs.py --doc-id abc123 --apply

清空某个资料库全部资料，慎用：
    python delete_imported_pdfs.py --db data\watch_ai_pdf_web_kb.sqlite3 --all --apply
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path.cwd()

DEFAULT_DBS = [
    ROOT / "data" / "watch_ai_pdf_web_kb.sqlite3",
    ROOT / "data" / "pdf_web_kb.sqlite3",
]


def resolve_db(db_arg: str | None) -> list[Path]:
    if db_arg:
        p = Path(db_arg)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            raise SystemExit(f"数据库不存在：{p}")
        return [p]

    found = [p for p in DEFAULT_DBS if p.exists()]
    if not found:
        raise SystemExit(
            "没有找到资料库数据库。请确认是否存在：\n"
            "  data\\watch_ai_pdf_web_kb.sqlite3\n"
            "  data\\pdf_web_kb.sqlite3\n"
        )
    return found


def connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def check_schema(db_path: Path) -> bool:
    try:
        with connect(db_path) as conn:
            tables = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        return {"documents", "chunks"}.issubset(tables)
    except Exception:
        return False


def load_docs(db_path: Path) -> pd.DataFrame:
    if not check_schema(db_path):
        return pd.DataFrame()
    with connect(db_path) as conn:
        rows = conn.execute("""
        SELECT d.doc_id, d.title, d.source_type, d.source_path, d.created_at,
               COUNT(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON d.doc_id = c.doc_id
        GROUP BY d.doc_id, d.title, d.source_type, d.source_path, d.created_at
        ORDER BY d.created_at DESC
        """).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def match_docs(df: pd.DataFrame, args) -> pd.DataFrame:
    if df.empty:
        return df

    mask = pd.Series(False, index=df.index)

    if args.all:
        mask[:] = True

    if args.doc_id:
        doc_ids = [x.strip() for x in args.doc_id.split(",") if x.strip()]
        mask |= df["doc_id"].astype(str).isin(doc_ids)

    if args.source_type:
        mask |= df["source_type"].astype(str).str.lower().eq(args.source_type.lower())

    if args.keyword:
        key = str(args.keyword)
        joined = (
            df.get("title", "").astype(str) + " " +
            df.get("source_path", "").astype(str) + " " +
            df.get("source_type", "").astype(str)
        )
        mask |= joined.str.contains(key, regex=False, na=False)

    return df[mask].copy()


def backup_db(db_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_suffix(db_path.suffix + f".bak_before_delete_{ts}")
    shutil.copy2(db_path, backup)
    return backup


def delete_docs(db_path: Path, docs: pd.DataFrame) -> int:
    doc_ids = docs["doc_id"].astype(str).tolist()
    if not doc_ids:
        return 0

    with connect(db_path) as conn:
        for doc_id in doc_ids:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        conn.commit()

    return len(doc_ids)


def print_docs(db_path: Path, df: pd.DataFrame, title: str = "资料列表") -> None:
    print(f"\n===== {title}: {db_path} =====")
    if df.empty:
        print("(空)")
        return

    show = df.copy()
    cols = [c for c in ["doc_id", "title", "source_type", "source_path", "chunk_count", "created_at"] if c in show.columns]
    print(show[cols].to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="", help="指定数据库路径；不指定则同时处理 8501/8502 两个资料库")
    parser.add_argument("--list", action="store_true", help="只列出资料")
    parser.add_argument("--apply", action="store_true", help="真正执行删除；不加则只预览")
    parser.add_argument("--all", action="store_true", help="删除匹配数据库中的全部资料，慎用")
    parser.add_argument("--source-type", default="", help="按来源类型删除，例如 pdf 或 url")
    parser.add_argument("--keyword", default="", help="按标题/路径/类型关键词删除")
    parser.add_argument("--doc-id", default="", help="按 doc_id 删除，多个用英文逗号分隔")
    args = parser.parse_args()

    dbs = resolve_db(args.db)

    any_filter = args.all or args.source_type or args.keyword or args.doc_id
    if args.list or not any_filter:
        for db in dbs:
            df = load_docs(db)
            print_docs(db, df, "当前已导入资料")
        if not any_filter:
            print("\n[提示] 当前没有提供删除条件，所以只是列出。")
            print("示例：删除所有PDF：python delete_imported_pdfs.py --source-type pdf --apply")
        return

    total = 0
    for db in dbs:
        df = load_docs(db)
        if df.empty:
            print_docs(db, df, "当前资料库为空")
            continue

        matched = match_docs(df, args)
        print_docs(db, matched, "将要删除的资料")

        if matched.empty:
            continue

        if not args.apply:
            print("\n[DRY-RUN] 当前只是预览，未删除。确认无误后加 --apply。")
            total += len(matched)
            continue

        backup = backup_db(db)
        count = delete_docs(db, matched)
        total += count
        print(f"[OK] 已删除 {count} 个文档。删除前备份：{backup}")

    if args.apply:
        print(f"\n[DONE] 总计删除 {total} 个文档。")
    else:
        print(f"\n[DONE] 总计匹配 {total} 个文档，未删除。")


if __name__ == "__main__":
    main()
