# -*- coding: utf-8 -*-
"""初始化项目目录、示例配置和本地数据库。"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
for d in ["config", "data", "reports", "logs", "backups", "skills", "skills/examples", "skills/uploads"]:
    (ROOT / d).mkdir(parents=True, exist_ok=True)

if not (ROOT / ".env").exists() and (ROOT / ".env.example").exists():
    shutil.copy(ROOT / ".env.example", ROOT / ".env")
    print("已从 .env.example 生成 .env，请填写自己的 API Key / 邮箱授权码。")

watch_example = ROOT / "config" / "watchlist.example.txt"
watch = ROOT / "config" / "watchlist.txt"
if not watch.exists() and watch_example.exists():
    shutil.copy(watch_example, watch)

# 初始化SQLite数据库和Skills
for mod_name, fn_name in [
    ("company_kb", "init_db"),
    ("pdf_kb", "init_db"),
    ("strategy_kb", "init_db"),
]:
    try:
        mod = __import__(mod_name)
        getattr(mod, fn_name)()
        print(f"初始化 {mod_name} OK")
    except Exception as e:
        print(f"初始化 {mod_name} 跳过/失败：{e}")

try:
    import skill_manager_v8_3
    skill_manager_v8_3.ensure_default_skills()
    print("初始化 Skills OK")
except Exception as e:
    print(f"初始化 Skills 失败：{e}")

print("项目初始化完成。")
