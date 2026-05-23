# -*- coding: utf-8 -*-
from strategy_kb import init_db, DB_PATH, list_strategies
init_db(seed=True)
print(f"[OK] 战法库已初始化：{DB_PATH}")
print(f"[OK] 当前战法数量：{len(list_strategies())}")
