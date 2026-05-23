from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from formatters import format_for_display

from data_source import (
    get_spot,
    get_zt_pool,
    get_zt_pool_dtgc,
    get_zt_pool_previous,
    get_zt_pool_strong,
    get_zt_pool_sub_new,
    get_zt_pool_zbgc,
    merge_watchlists,
)

TODAY = datetime.now().strftime("%Y%m%d")
REPORT_DIR = Path("reports")
CONFIG_DIR = Path("config")
REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)


def load_settings() -> dict[str, Any]:
    path = CONFIG_DIR / "settings.json"
    default = {
        "tdx_watchlist_path": "",
        "refresh_seconds": 60,
        "alert_gain_pct": 7.0,
        "alert_loss_pct": -5.0,
        "near_limit_pct": 8.0,
        "max_table_rows": 200,
    }
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        default.update(user)
        return default
    except Exception:
        return default


def save_csv(df: pd.DataFrame, name: str) -> Path:
    """保存原始表，同时保存一个 *_display.csv 便于人工查看。"""
    path = REPORT_DIR / f"{name}_{TODAY}.csv"
    display_path = REPORT_DIR / f"{name}_display_{TODAY}.csv"
    if df is None or df.empty:
        pd.DataFrame().to_csv(path, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(display_path, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        format_for_display(df).to_csv(display_path, index=False, encoding="utf-8-sig")
    print(f"[OK] 保存: {path}")
    print(f"[OK] 展示版: {display_path}")
    return path


def get_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    if s in {"", "-", "--", "nan", "None"}:
        return default
    unit = 1.0
    if "亿" in s:
        unit = 100_000_000.0
    elif "万" in s:
        unit = 10_000.0
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return default
    try:
        return float(m.group(0)) * unit
    except Exception:
        return default


def code_norm(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{6})")[0].fillna("")


def extract_board_count(value: Any) -> int:
    """从 连板数 / 涨停统计 等字段中提取连板高度。"""
    if value is None:
        return 1
    s = str(value)
    # 常见："3天3板"、"2连板"、"首板"、1
    if "首" in s:
        return 1
    nums = re.findall(r"\d+", s)
    if not nums:
        return 1
    # 涨停统计通常第一个数更接近高度，如 3天3板
    try:
        return max(1, int(nums[-1] if "板" in s and len(nums) >= 2 else nums[0]))
    except Exception:
        return 1


def enrich_limit_up(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    code_col = get_col(df, ["代码", "证券代码"])
    if code_col:
        df["代码"] = code_norm(df[code_col])

    lb_col = get_col(df, ["连板数", "涨停统计"])
    if lb_col:
        df["连板高度"] = df[lb_col].apply(extract_board_count)
    else:
        df["连板高度"] = 1

    first_time_col = get_col(df, ["首次封板时间", "首次涨停时间"])
    break_col = get_col(df, ["炸板次数", "开板次数"])
    turnover_col = get_col(df, ["换手率"])
    amount_col = get_col(df, ["成交额"])
    seal_col = get_col(df, ["封板资金", "封单资金"])
    price_col = get_col(df, ["最新价", "收盘价"])
    pct_col = get_col(df, ["涨跌幅", "涨幅"])

    score = pd.Series(50.0, index=df.index)
    score += df["连板高度"].clip(1, 6) * 5

    if first_time_col:
        t = df[first_time_col].astype(str).str.replace(":", "", regex=False).str.extract(r"(\d{4,6})")[0]
        t = pd.to_numeric(t, errors="coerce")
        score += t.apply(lambda x: 12 if pd.notna(x) and x <= 93500 else 8 if pd.notna(x) and x <= 100000 else 4 if pd.notna(x) and x <= 110000 else 0)
        df["早盘前排"] = t.apply(lambda x: bool(pd.notna(x) and x <= 100000))
    else:
        df["早盘前排"] = False

    if seal_col:
        seal = df[seal_col].apply(num)
        score += seal.rank(pct=True).fillna(0) * 15

    if break_col:
        breaks = df[break_col].apply(num)
        df["炸板次数_数值"] = breaks
        score -= breaks * 7
    else:
        df["炸板次数_数值"] = 0

    if turnover_col:
        turnover = df[turnover_col].apply(num)
        df["换手率_数值"] = turnover
        score += turnover.apply(lambda x: 6 if 3 <= x <= 18 else -4 if x > 30 else 0)
    else:
        df["换手率_数值"] = 0

    if amount_col:
        amount = df[amount_col].apply(num)
        df["成交额_数值"] = amount
        score -= amount.apply(lambda x: 5 if x > 8_000_000_000 else 0)
    else:
        df["成交额_数值"] = 0

    if pct_col:
        df["涨跌幅_数值"] = df[pct_col].apply(num)

    if price_col:
        df["最新价_数值"] = df[price_col].apply(num)
        # 短线低价偏好加一点，过高扣一点，不绝对
        score += df["最新价_数值"].apply(lambda x: 3 if 0 < x <= 10 else -2 if x >= 40 else 0)

    def tag(row: pd.Series) -> str:
        tags: list[str] = []
        h = int(row.get("连板高度", 1))
        if h <= 1:
            tags.append("首板")
        elif h == 2:
            tags.append("1进2")
        elif h == 3:
            tags.append("2进3")
        else:
            tags.append("高标")
        if bool(row.get("早盘前排", False)):
            tags.append("早盘前排")
        if row.get("炸板次数_数值", 0) > 0:
            tags.append("炸板回封")
        if row.get("成交额_数值", 0) > 8_000_000_000:
            tags.append("大成交")
        return " / ".join(tags)

    df["机器人评分"] = score.round(1)
    df["机器人标签"] = df.apply(tag, axis=1)
    return df.sort_values(["机器人评分", "连板高度"], ascending=[False, False])


def sector_strength(zt_df: pd.DataFrame) -> pd.DataFrame:
    if zt_df.empty:
        return pd.DataFrame()
    industry_col = get_col(zt_df, ["所属行业", "行业", "板块", "概念"])
    if not industry_col:
        return pd.DataFrame()
    grouped = zt_df.groupby(industry_col).agg(
        涨停数量=(industry_col, "size"),
        连板数量=("连板高度", lambda x: int((x >= 2).sum()) if hasattr(x, "sum") else 0),
        平均评分=("机器人评分", "mean"),
        最高连板=("连板高度", "max"),
    ).reset_index()
    grouped["平均评分"] = grouped["平均评分"].round(1)
    return grouped.sort_values(["涨停数量", "最高连板", "平均评分"], ascending=[False, False, False])


def analyze_watchlist(spot_df: pd.DataFrame, zt_df: pd.DataFrame, watch_df: pd.DataFrame, settings: dict[str, Any]) -> pd.DataFrame:
    if watch_df.empty:
        return pd.DataFrame()
    out = watch_df.copy()
    out["代码"] = code_norm(out["代码"])

    if not spot_df.empty:
        spot = spot_df.copy()
        code_col = get_col(spot, ["代码", "证券代码"])
        if code_col:
            spot["代码"] = code_norm(spot[code_col])
        keep = [c for c in ["代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "最高", "最低", "今开", "昨收", "量比", "换手率", "市盈率-动态", "市净率"] if c in spot.columns]
        spot = spot[keep].drop_duplicates(subset=["代码"])
        out = out.merge(spot, on="代码", how="left")

    zt_codes = set(zt_df["代码"].astype(str)) if not zt_df.empty and "代码" in zt_df.columns else set()
    out["是否涨停"] = out["代码"].isin(zt_codes)
    if "涨跌幅" in out.columns:
        out["涨跌幅_数值"] = out["涨跌幅"].apply(num)
    else:
        out["涨跌幅_数值"] = 0.0
    out["接近涨停"] = out["涨跌幅_数值"] >= float(settings.get("near_limit_pct", 8.0))
    out["强异动"] = out["涨跌幅_数值"] >= float(settings.get("alert_gain_pct", 7.0))
    out["弱风险"] = out["涨跌幅_数值"] <= float(settings.get("alert_loss_pct", -5.0))

    def reason(row: pd.Series) -> str:
        rs = []
        if row.get("是否涨停", False):
            rs.append("自选股涨停")
        elif row.get("接近涨停", False):
            rs.append("接近涨停")
        elif row.get("强异动", False):
            rs.append("强异动")
        if row.get("弱风险", False):
            rs.append("跌幅风险")
        return " / ".join(rs) if rs else "正常观察"

    out["监控结论"] = out.apply(reason, axis=1)
    return out.sort_values(["是否涨停", "接近涨停", "涨跌幅_数值"], ascending=[False, False, False])


def build_emotion(zt_df: pd.DataFrame, zb_df: pd.DataFrame, dt_df: pd.DataFrame, prev_df: pd.DataFrame) -> dict[str, Any]:
    total_zt = 0 if zt_df.empty else len(zt_df)
    total_zb = 0 if zb_df.empty else len(zb_df)
    total_dt = 0 if dt_df.empty else len(dt_df)
    seal_rate = round(total_zt / max(total_zt + total_zb, 1) * 100, 1)
    max_board = int(zt_df["连板高度"].max()) if not zt_df.empty and "连板高度" in zt_df.columns else 0
    lb_count = int((zt_df["连板高度"] >= 2).sum()) if not zt_df.empty and "连板高度" in zt_df.columns else 0

    prev_red_rate = None
    prev_avg_pct = None
    if prev_df is not None and not prev_df.empty:
        pct_col = get_col(prev_df, ["涨跌幅", "涨幅"])
        if pct_col:
            vals = prev_df[pct_col].apply(num)
            prev_avg_pct = round(float(vals.mean()), 2) if len(vals) else None
            prev_red_rate = round(float((vals > 0).mean() * 100), 1) if len(vals) else None

    # 简单情绪定性
    if total_zt >= 70 and seal_rate >= 75 and total_dt <= 10:
        mood = "强修复/强势"
    elif total_zt >= 45 and seal_rate >= 60:
        mood = "可交易"
    elif total_zb > total_zt or total_dt >= 20:
        mood = "谨慎/弱势"
    else:
        mood = "混沌"

    return {
        "date": TODAY,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_zt": total_zt,
        "total_zb": total_zb,
        "total_dt": total_dt,
        "seal_rate": seal_rate,
        "limit_up_chains": lb_count,
        "max_board": max_board,
        "prev_red_rate": prev_red_rate,
        "prev_avg_pct": prev_avg_pct,
        "mood": mood,
    }


def to_markdown_safe(df: pd.DataFrame, n: int = 20) -> str:
    if df is None or df.empty:
        return "暂无数据"
    show = format_for_display(df.head(n))
    try:
        return show.to_markdown(index=False)
    except Exception:
        return show.to_string(index=False)


def build_report(emotion: dict[str, Any], zt_df: pd.DataFrame, sector_df: pd.DataFrame, watch_df: pd.DataFrame, zb_df: pd.DataFrame, dt_df: pd.DataFrame) -> str:
    cols = [c for c in ["代码", "名称", "所属行业", "行业", "连板高度", "首次封板时间", "炸板次数", "换手率", "封板资金", "机器人评分", "机器人标签"] if c in zt_df.columns]
    watch_cols = [c for c in ["代码", "自选名称", "名称", "最新价", "涨跌幅", "是否涨停", "接近涨停", "监控结论"] if c in watch_df.columns]
    risk_cols = [c for c in ["代码", "名称", "涨跌幅", "成交额", "换手率", "炸板次数"] if c in zb_df.columns]

    lines: list[str] = []
    lines.append("# A股短线看盘报告 v5")
    lines.append("")
    lines.append(f"生成时间：{emotion.get('generated_at')}")
    lines.append("")
    lines.append("## 一、市场情绪")
    lines.append("")
    lines.append(f"- 涨停数量：{emotion.get('total_zt')}")
    lines.append(f"- 炸板数量：{emotion.get('total_zb')}")
    lines.append(f"- 跌停数量：{emotion.get('total_dt')}")
    lines.append(f"- 封板率：{emotion.get('seal_rate')}%")
    lines.append(f"- 连板数量：{emotion.get('limit_up_chains')}")
    lines.append(f"- 最高板：{emotion.get('max_board')}")
    lines.append(f"- 机器人情绪：{emotion.get('mood')}")
    if emotion.get("prev_red_rate") is not None:
        lines.append(f"- 昨日涨停红盘率：{emotion.get('prev_red_rate')}%，平均涨跌幅：{emotion.get('prev_avg_pct')}%")
    lines.append("")

    lines.append("## 二、板块强度")
    lines.append("")
    lines.append(to_markdown_safe(sector_df, 15))
    lines.append("")

    lines.append("## 三、明日连板观察 Top 20")
    lines.append("")
    lines.append(to_markdown_safe(zt_df[cols] if cols else zt_df, 20))
    lines.append("")

    lines.append("## 四、首板观察池")
    lines.append("")
    first = zt_df[zt_df.get("连板高度", pd.Series(dtype=int)) <= 1] if not zt_df.empty else pd.DataFrame()
    lines.append(to_markdown_safe(first[cols] if cols and not first.empty else first, 20))
    lines.append("")

    lines.append("## 五、自选股监控")
    lines.append("")
    lines.append(to_markdown_safe(watch_df[watch_cols] if watch_cols and not watch_df.empty else watch_df, 30))
    lines.append("")

    lines.append("## 六、风险池")
    lines.append("")
    lines.append("### 炸板股")
    lines.append(to_markdown_safe(zb_df[risk_cols] if risk_cols and not zb_df.empty else zb_df, 15))
    lines.append("")
    lines.append("### 跌停股")
    lines.append(to_markdown_safe(dt_df, 15))
    lines.append("")

    lines.append("## 七、明日盘前计划")
    lines.append("")
    lines.append("- 先看最高板是否负反馈；高标核按钮时，首板与一进二也要降仓位。")
    lines.append("- 先看主线板块是否继续批量涨停；如果只剩孤板，按兑现处理。")
    lines.append("- 自选股只做强异动和涨停确认，不因为加入自选而强行交易。")
    lines.append("- 非核心后排、尾盘偷鸡、巨量烂板，次日不及预期要快。")
    lines.append("")
    lines.append("> 本报告只用于复盘和观察，不构成投资建议，不做自动下单。")
    return "\n".join(lines)


def main() -> None:
    settings = load_settings()
    print(f"[INFO] 日期: {TODAY}")

    zt_df = enrich_limit_up(get_zt_pool(TODAY))
    prev_df = get_zt_pool_previous(TODAY)
    strong_df = get_zt_pool_strong(TODAY)
    sub_new_df = get_zt_pool_sub_new(TODAY)
    zb_df = get_zt_pool_zbgc(TODAY)
    dt_df = get_zt_pool_dtgc(TODAY)
    spot_df = get_spot()

    # 标准化关键字段
    for df in [prev_df, strong_df, sub_new_df, zb_df, dt_df, spot_df]:
        if df is not None and not df.empty:
            df.columns = [str(c).strip() for c in df.columns]
            c = get_col(df, ["代码", "证券代码"])
            if c:
                df["代码"] = code_norm(df[c])

    sector_df = sector_strength(zt_df)
    watchlist_df = merge_watchlists(CONFIG_DIR / "watchlist.txt", settings.get("tdx_watchlist_path") or None)
    watch_df = analyze_watchlist(spot_df, zt_df, watchlist_df, settings)
    emotion = build_emotion(zt_df, zb_df, dt_df, prev_df)

    save_csv(zt_df, "zt_pool")
    save_csv(prev_df, "prev_pool")
    save_csv(strong_df, "strong_pool")
    save_csv(sub_new_df, "sub_new_pool")
    save_csv(zb_df, "zbgc_pool")
    save_csv(dt_df, "dtgc_pool")
    save_csv(sector_df, "sector_strength")
    save_csv(watch_df, "watchlist_monitor")

    (REPORT_DIR / f"market_emotion_{TODAY}.json").write_text(json.dumps(emotion, ensure_ascii=False, indent=2), encoding="utf-8")
    report = build_report(emotion, zt_df, sector_df, watch_df, zb_df, dt_df)
    (REPORT_DIR / f"report_{TODAY}.md").write_text(report, encoding="utf-8")
    print("[OK] 复盘报告已生成")
    print(report)


if __name__ == "__main__":
    main()
