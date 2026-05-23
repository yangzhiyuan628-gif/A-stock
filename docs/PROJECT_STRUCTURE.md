# 项目结构说明

## 核心入口

- `streamlit_app.py`：8501，盘后复盘和 AI 游资复盘。
- `streamlit_realtime.py`：8502，实时盯盘和信号提醒。
- `main.py`：盘后行情抓取和基础报告生成。

## 核心模块

- `realtime_core.py`：实时行情、过滤、基础清洗。
- `kobe_rule_attribution_v8_2_1.py`：92科比模式化规则归因。
- `email_smallcap_alert_v8_2_2.py`：小市值偏好和邮件提醒。
- `smallcap_review_8501_v8_2_2.py`：8501 小市值高弹性复盘。
- `skill_manager_v8_3.py`：Skills 技能系统。
- `network_guard_v8_3_2.py`：网络/API稳定层。
- `web_research_v8_3_2.py`：联网检索增强。
- `realtime_logger_v8_3_2.py`：8502全天日志。
- `backup_manager_v8_3_2.py`：备份/回滚。

## 运行时目录

- `data/`：SQLite 知识库，运行时生成。
- `reports/`：行情、信号、复盘结果，运行时生成。
- `logs/`：错误和全天日志，运行时生成。
- `backups/`：本地备份，运行时生成。
- `skills/`：战法技能库，可版本化管理。
