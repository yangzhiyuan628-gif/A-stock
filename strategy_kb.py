# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "shortline_strategy_kb.sqlite3"

DEFAULT_STRATEGIES = [
    ("首板新题材确认", "首板", "低位或相对低位，首批启动，板块有批量异动。", "涨幅7%以上且板块强势增加；封板看封单、回封、炸板承接。", "封板失败且回落跌破分时均线，板块助攻消失。", "小仓试错，题材确认度高再加。", "首板,新题材,板块联动,低位", "系统内置：短线打板经验规则"),
    ("半路启动买点", "半路", "涨幅3%~8%，5分钟涨速转强，成交额放大，板块有强势股。", "回踩均线不破再上，或突破日内高点时量能同步放大。", "突破后无量、冲高回落、板块联动断裂。", "半路仓位低于确认打板。", "半路,涨速,成交额,板块联动", "系统内置：短线打板经验规则"),
    ("回封板确认", "打板", "首次封板后炸板，但回落可控，板块仍有助攻。", "二次回封或多次炸板后仍能快速回封。", "炸板后无法回封、封单持续减少、板块龙头跳水。", "弱市降低仓位。", "回封,炸板,承接,打板", "系统内置：短线打板经验规则"),
    ("明日首板候选", "隔日预判", "今日未涨停但放量、涨速、板块联动或题材预热，涨幅2%~7%。", "次日竞价超预期、开盘承接、板块继续发酵。", "次日竞价低于预期、板块退潮、冲高回落。", "只进观察池，次日确认才出手。", "明日首板,隔日,预判,低位", "系统内置：短线打板经验规则"),
    ("高低切首板", "首板", "高位龙头分歧或监管压力增大，同题材低位补涨启动。", "低位率先封板或半路放量突破，题材仍有强度。", "高位龙头跳水带崩题材，低位补涨封板失败。", "快进快出，不能把补涨当龙头格局。", "高低切,补涨,首板", "系统内置：短线打板经验规则"),
    ("弱转强一进二", "连板", "昨日首板较弱或烂板，次日竞价/开盘明显超预期。", "竞价高开量能匹配，开盘快速上攻，回踩不破均价线。", "竞价强但开盘下杀，或板块无跟随。", "依赖市场连板情绪。", "弱转强,一进二,竞价", "系统内置：短线打板经验规则"),
]

def connect(db_path: Path = DB_PATH):
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(seed=True):
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT,
            setup TEXT,
            buy_trigger TEXT,
            sell_risk TEXT,
            position_rule TEXT,
            tags TEXT,
            source TEXT,
            source_type TEXT DEFAULT 'manual',
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        if seed:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for s in DEFAULT_STRATEGIES:
                conn.execute("""
                INSERT OR IGNORE INTO strategies
                (name, category, setup, buy_trigger, sell_risk, position_rule, tags, source, source_type, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'builtin', 1, ?, ?)
                """, (*s, now, now))
        conn.commit()

def add_strategy(name, category="", setup="", buy_trigger="", sell_risk="", position_rule="", tags="", source="用户手动添加"):
    init_db(seed=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO strategies
        (name, category, setup, buy_trigger, sell_risk, position_rule, tags, source, source_type, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', 1, COALESCE((SELECT created_at FROM strategies WHERE name=?), ?), ?)
        """, (name, category, setup, buy_trigger, sell_risk, position_rule, tags, source, name, now, now))
        conn.commit()

def list_strategies():
    init_db(seed=True)
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM strategies WHERE enabled=1 ORDER BY category,id").fetchall()]

def search_strategies(query="", limit=8):
    rows = list_strategies()
    if not query:
        return rows[:limit]
    keys = ["首板","打板","半路","回封","明日","弱转强","一进二","高低切","补涨","龙头","炸板","低吸"]
    tokens = [k for k in keys if k in query]
    tokens += [x.strip() for x in query.replace("，"," ").replace(","," ").split() if x.strip()]
    scored = []
    for r in rows:
        txt = " ".join(str(r.get(k,"")) for k in ["name","category","setup","buy_trigger","sell_risk","position_rule","tags","source"])
        score = sum(1 for t in tokens if t and t in txt)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]] or rows[:limit]

def strategies_to_context(rows):
    parts = []
    for r in rows:
        parts.append(
            f"【{r.get('category','')}】{r.get('name','')}\n"
            f"来源: {r.get('source','')}\n"
            f"适用形态: {r.get('setup','')}\n"
            f"买入触发: {r.get('buy_trigger','')}\n"
            f"风险/卖点: {r.get('sell_risk','')}\n"
            f"仓位规则: {r.get('position_rule','')}\n"
            f"标签: {r.get('tags','')}\n"
        )
    return "\n".join(parts)
