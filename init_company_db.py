# -*- coding: utf-8 -*-
from company_kb import init_db, DB_PATH, search_company
init_db(seed=True)
print(f"[OK] 公司知识库已初始化：{DB_PATH}")
print("[OK] 莲花控股示例：")
for r in search_company(code="600186", name="莲花控股"):
    print(r)
