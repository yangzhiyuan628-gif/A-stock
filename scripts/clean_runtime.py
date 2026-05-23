# -*- coding: utf-8 -*-
"""清理运行时输出：reports/logs/backups，不删除代码和配置。"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
for folder in ["reports", "logs", "backups"]:
    p = ROOT / folder
    if p.exists():
        for x in p.iterdir():
            if x.name == ".gitkeep":
                continue
            if x.is_dir():
                shutil.rmtree(x, ignore_errors=True)
            else:
                x.unlink(missing_ok=True)
    p.mkdir(exist_ok=True)
    (p / ".gitkeep").write_text("", encoding="utf-8")
    print(f"已清理 {folder}")
