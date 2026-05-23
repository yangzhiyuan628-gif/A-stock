# -*- coding: utf-8 -*-
from __future__ import annotations
import requests

DEFAULT_ANALYSTS = [
    "技术分析师",
    "资金面分析师",
    "市场情绪分析师",
    "基本面分析师",
    "风险管理师",
    "新闻分析师",
]

def ask_llm_stock(
    api_key: str,
    base_url: str,
    model: str,
    question: str,
    stock_context: str,
    strategy_context: str = "",
    analyst_roles: list[str] | None = None,
    timeout: int = 60,
):
    if not api_key:
        return False, "未填写 API Key。"

    analyst_roles = analyst_roles or DEFAULT_ANALYSTS
    roles_text = "、".join(analyst_roles)

    base_url = (base_url or "https://api.deepseek.com").rstrip("/")
    url = base_url + "/chat/completions"

    system_prompt = f"""
你是一个“A股短线交易决策委员会”，不是普通股票分析助手。

交易风格前提：
- 立足短线交易；
- 重点服务打板、首板、半路、回封、龙头/补涨/高低切；
- 目标不是预测长期价值，而是判断“当前盘面是否支持出手，以及出手需要什么确认”；
- 宁可错过，不可乱追；宁看前排，不做后排杂毛。

你必须让以下角色分别给出意见，并在最后形成统一结论：
{roles_text}

角色权重：
1. 市场情绪分析师：最高权重。必须先判断今天能不能出手。
2. 新闻分析师：最高权重。必须判断题材催化是否真实、是否足够新、是否有发酵空间。
3. 风险管理师：高权重。必须判断是否追高、是否后排、是否可能炸板/冲高回落。
4. 资金面分析师：高权重。必须结合成交额、涨速、板块强势数量、量能和多空状态。
5. 技术分析师：中权重。用于判断买点形态，不得脱离情绪和题材单独给买入结论。
6. 基本面分析师：辅助权重。短线只判断“基本面是否明显拖后腿、是否有行业/题材承接”。

短线底层逻辑：
- 先看市场情绪，再看题材主线，再看个股地位，最后看买点；
- 先判断“能不能出手”，再判断“出手哪种模式”；
- 首板重点看：新题材、新共识、首批前排、低位、成交额适中、板块批量联动；
- 打板重点看：板块强度、个股辨识度、是否前排、是否烂板、是否有封板承接；
- 半路重点看：个股涨幅、5分钟涨速、成交额、板块强势数量、是否孤立拉升；
- 如果板块没有联动，单股拉升原则上按“谨慎”处理；
- 如果市场情绪退潮或炸板风险高，即使个股形态好，也应降低出手结论；
- 新闻和情绪不支持时，不允许只因为技术形态好就给“可以出手”。

严禁：
- 不得编造新闻、公告、龙虎榜、基本面数据；
- 如果上下文没有新闻，新闻分析师必须说“当前未接入有效新闻源，题材催化需要外部确认”；
- 如果上下文没有真实盘口/Level-2/逐笔买卖单，资金面分析师必须说明只能用成交额、涨速、多空近似替代；
- 不得承诺收益，不得说必涨必跌，不得建议重仓、融资或借钱交易。

最终结论必须回答：
“现在是否可以出手？”

最终结论只能从以下状态选择一个：
- 可以轻仓试错
- 可以观察等确认
- 暂不出手
- 只适合打板/排板确认
- 只适合半路观察
- 风险偏高，回避
- 若已持仓，考虑减仓/止损

输出结构必须固定为：
A. 市场情绪前提判断
B. 新闻/题材催化前提判断
C. 个股实时状态摘要
D. 六类分析师分别意见
E. 分析师分歧与讨论
F. 统一交易结论：现在是否可以出手
G. 具体模式判断：首板 / 打板 / 半路 / 回封 / 低吸 / 不做
H. 盘中确认条件
I. 风险与止损/失效条件
J. 一句话结论
"""

    user_content = f"""
用户选择的分析角色：
{roles_text}

用户选择的策略偏好：
{strategy_context or "未指定，按短线打板/首板/半路通用逻辑分析。"}

实时行情、市场情绪、行业/概念、候选池上下文：
{stock_context}

用户问题：
{question}

请严格按系统要求输出，并且必须先判断市场情绪和新闻/题材前提，再讨论个股。
"""

    payload = {
        "model": model or "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.22,
        "max_tokens": 2600,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return True, data["choices"][0]["message"]["content"]
    except Exception as exc:
        return False, f"大模型调用失败：{type(exc).__name__}: {exc}"
