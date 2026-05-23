# -*- coding: utf-8 -*-
"""项目诊断脚本：检查目录、关键文件、依赖导入和Python语法。"""
from pathlib import Path
import py_compile
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
print("== Python ==")
print(sys.version)

print("\n== 关键文件 ==")
for rel in ["streamlit_app.py", "streamlit_realtime.py", "main.py", "requirements.txt", ".env.example"]:
    p = ROOT / rel
    print(rel, "OK" if p.exists() else "MISSING")

print("\n== 关键目录 ==")
for rel in ["config", "data", "reports", "logs", "backups", "skills"]:
    p = ROOT / rel
    print(rel, "OK" if p.exists() else "MISSING")

print("\n== 依赖导入 ==")
for pkg in ["streamlit", "pandas", "requests", "akshare", "openai", "pypdf", "PIL"]:
    print(pkg, "OK" if importlib.util.find_spec(pkg) else "MISSING")

print("\n== 语法检查 ==")
failed = []
for p in sorted(ROOT.glob("*.py")):
    try:
        py_compile.compile(str(p), doraise=True)
        print(p.name, "OK")
    except Exception as e:
        print(p.name, "ERROR", e)
        failed.append(p.name)
print("\n结果：", "全部通过" if not failed else f"失败 {failed}")
