"""AI 游资风格复盘生成器（支持 OpenAI / DeepSeek）。

运行方式：
    python ai_report.py

DeepSeek 推荐环境变量：
    setx AI_PROVIDER "deepseek"
    setx DEEPSEEK_API_KEY "你的 DeepSeek key"
    setx AI_MODEL "deepseek-v4-flash"

OpenAI 推荐环境变量：
    setx AI_PROVIDER "openai"
    setx OPENAI_API_KEY "你的 OpenAI key"
    setx AI_MODEL "gpt-5.5"

也可以在 Streamlit 左侧栏临时输入 API Key。本程序只生成复盘报告，不会自动下单。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from formatters import format_for_display

REPORT_DIR = Path("reports")
CONFIG_DIR = Path("config")
REPORT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)
TODAY = datetime.now().strftime("%Y%m%d")


def load_csv(name: str) -> pd.DataFrame:
    path = REPORT_DIR / f"{name}_{TODAY}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_json(name: str) -> dict[str, Any]:
    path = REPORT_DIR / f"{name}_{TODAY}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _default_model(provider: str) -> str:
    provider = provider.lower().strip()
    if provider == "deepseek":
        return "deepseek-v4-flash"
    return "gpt-5.5"


def _default_base_url(provider: str) -> str:
    provider = provider.lower().strip()
    if provider == "deepseek":
        return "https://api.deepseek.com"
    return ""


def load_settings() -> dict[str, Any]:
    provider = os.getenv("AI_PROVIDER", "deepseek").strip().lower() or "deepseek"
    path = CONFIG_DIR / "settings.json"
    default = {
        "ai_provider": provider,
        "ai_model": os.getenv("AI_MODEL", _default_model(provider)),
        "ai_base_url": os.getenv("AI_BASE_URL", _default_base_url(provider)),
        "ai_report_top_n": 25,
        "ai_report_style": "短线游资复盘，重点看情绪、主线、连板、首板、风险，不给确定性承诺。",
    }
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            default.update(old)
        except Exception:
            pass
    else:
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")

    # 环境变量优先，方便 Streamlit 子进程临时传入
    provider = os.getenv("AI_PROVIDER", str(default.get("ai_provider", "deepseek"))).strip().lower() or "deepseek"
    default["ai_provider"] = provider
    default["ai_model"] = os.getenv("AI_MODEL", str(default.get("ai_model") or _default_model(provider))).strip()
    default["ai_base_url"] = os.getenv("AI_BASE_URL", str(default.get("ai_base_url") or _default_base_url(provider))).strip()

    # 防止旧配置里 DeepSeek 还显示 gpt 模型
    if provider == "deepseek" and str(default["ai_model"]).startswith("gpt"):
        default["ai_model"] = _default_model(provider)
    if provider == "deepseek" and not default.get("ai_base_url"):
        default["ai_base_url"] = _default_base_url(provider)
    return default


def get_api_key(provider: str) -> str:
    provider = provider.lower().strip()
    if os.getenv("AI_API_KEY", "").strip():
        return os.getenv("AI_API_KEY", "").strip()
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY", "").strip()
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "").strip()
    return os.getenv("OPENAI_API_KEY", "").strip()


def df_records(df: pd.DataFrame, n: int = 25) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    show = format_for_display(df.head(n))
    return show.fillna("").to_dict(orient="records")


def build_payload() -> dict[str, Any]:
    settings = load_settings()
    n = int(settings.get("ai_report_top_n", 25))
    return {
        "date": TODAY,
        "emotion": load_json("market_emotion"),
        "sector_strength": df_records(load_csv("sector_strength"), 20),
        "limit_up_pool_top": df_records(load_csv("zt_pool"), n),
        "watchlist_monitor": df_records(load_csv("watchlist_monitor"), n),
        "broken_limit_pool": df_records(load_csv("zbgc_pool"), 20),
        "down_limit_pool": df_records(load_csv("dtgc_pool"), 20),
        "previous_limit_pool": df_records(load_csv("prev_pool"), 20),
    }


def build_prompt(payload: dict[str, Any], settings: dict[str, Any]) -> str:
    data_text = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""
你是一个A股短线复盘助手，风格偏短线游资/打板机器人，但必须强调风险，不做收益承诺，不做自动下单建议。

请根据下面的结构化盘面数据，生成一份中文 Markdown 复盘报告。

报告结构固定为：
# AI短线复盘报告
## 1. 今日市场情绪
## 2. 今日主线与板块强度
## 3. 高标与连板梯队
## 4. 首板/低位补涨观察
## 5. 自选股异动
## 6. 明日盘前计划
## 7. 风险提示

写作要求：
- 语言简洁、直接、偏交易复盘口径。
- 不要编造数据；数据中没有的就写“暂无”。
- 不要说“必涨”“一定连板”。
- 重点输出观察条件：竞价、承接、板块助攻、炸板率、高标反馈。
- 所有表格里的单位已经格式化为亿、万、%、时间格式，直接使用。
- 风格备注：{settings.get('ai_report_style', '')}

结构化数据如下：
{data_text}
""".strip()


def fallback_report(payload: dict[str, Any], reason: str = "") -> str:
    e = payload.get("emotion") or {}
    sectors = payload.get("sector_strength") or []
    top = payload.get("limit_up_pool_top") or []
    watch = payload.get("watchlist_monitor") or []
    lines = [
        "# AI短线复盘报告（本地模板版）",
        "",
        "未检测到可用的 AI API Key，或远程模型调用失败，已生成本地模板版。设置 DeepSeek/OpenAI API Key 后，可生成更完整的自然语言复盘。",
    ]
    if reason:
        lines += ["", f"> 调用失败原因：{reason}"]
    lines += [
        "",
        "## 1. 今日市场情绪",
        f"- 涨停：{e.get('total_zt', '暂无')}，炸板：{e.get('total_zb', '暂无')}，跌停：{e.get('total_dt', '暂无')}，封板率：{e.get('seal_rate', '暂无')}%",
        f"- 连板数：{e.get('limit_up_chains', '暂无')}，最高板：{e.get('max_board', '暂无')}，情绪：{e.get('mood', '暂无')}",
        "",
        "## 2. 今日主线与板块强度",
    ]
    if sectors:
        for row in sectors[:8]:
            name = row.get("所属行业") or row.get("行业") or row.get("板块") or "未知板块"
            lines.append(f"- {name}：涨停 {row.get('涨停数量', '暂无')}，最高连板 {row.get('最高连板', '暂无')}")
    else:
        lines.append("- 暂无板块强度数据。")
    lines += ["", "## 3. 高标与连板梯队"]
    if top:
        for row in top[:10]:
            lines.append(f"- {row.get('代码','')} {row.get('名称','')}：{row.get('连板高度','')}板，评分 {row.get('机器人评分','')}，标签 {row.get('机器人标签','')}")
    else:
        lines.append("- 暂无涨停池数据。")
    lines += ["", "## 4. 自选股异动"]
    if watch:
        for row in watch[:10]:
            lines.append(f"- {row.get('代码','')} {row.get('名称') or row.get('自选名称','')}：涨跌幅 {row.get('涨跌幅','')}，结论 {row.get('监控结论','')}")
    else:
        lines.append("- 暂无自选股监控数据。")
    lines += [
        "",
        "## 5. 明日盘前计划",
        "- 先看最高板是否负反馈，再决定是否出手首板/一进二。",
        "- 主线需要继续批量助攻，孤板不追。",
        "- 炸板率升高或昨日涨停无溢价时，降低仓位或空仓。",
        "",
        "## 6. 风险提示",
        "- 本报告只用于复盘和观察，不构成投资建议，不做自动下单。",
    ]
    return "\n".join(lines)


def generate_with_deepseek(prompt: str, settings: dict[str, Any], api_key: str) -> str:
    from openai import OpenAI

    model = str(settings.get("ai_model") or "deepseek-v4-flash")
    base_url = str(settings.get("ai_base_url") or "https://api.deepseek.com")
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是谨慎的A股短线复盘助手，只做复盘观察，不做自动交易。"},
            {"role": "user", "content": prompt},
        ],
        stream=False,
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def generate_with_openai(prompt: str, settings: dict[str, Any], api_key: str) -> str:
    from openai import OpenAI

    model = str(settings.get("ai_model") or "gpt-5.5")
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=2500,
    )
    return response.output_text


def generate_ai_report() -> str:
    settings = load_settings()
    payload = build_payload()
    provider = str(settings.get("ai_provider", "deepseek")).strip().lower()
    api_key = get_api_key(provider)
    if not api_key:
        return fallback_report(payload, f"未检测到 {provider.upper()} API Key")

    try:
        import openai  # noqa: F401
    except Exception as exc:
        return fallback_report(payload, f"openai 包未安装或导入失败：{exc}")

    prompt = build_prompt(payload, settings)
    try:
        if provider == "deepseek":
            return generate_with_deepseek(prompt, settings, api_key)
        if provider == "openai":
            return generate_with_openai(prompt, settings, api_key)
        return generate_with_deepseek(prompt, settings, api_key)
    except Exception as exc:
        return fallback_report(payload, str(exc))


def main() -> None:
    report = generate_ai_report()
    out = REPORT_DIR / f"ai_report_{TODAY}.md"
    out.write_text(report, encoding="utf-8")
    print(f"[OK] AI复盘报告已生成: {out}")
    print(report)


if __name__ == "__main__":
    main()
