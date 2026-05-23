# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from pathlib import Path

def load_project_env(env_file: str = ".env") -> None:
    root = Path(__file__).resolve().parent
    path = root / env_file
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
