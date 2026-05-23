# -*- coding: utf-8 -*-
from pdf_kb import init_db, DB_PATH, list_documents
init_db()
print(f"[OK] PDF/网页知识库已初始化：{DB_PATH}")
print(f"[OK] 当前文档数：{len(list_documents())}")
