# GitHub 整理说明

本版本从原始工作目录中清理了以下内容：

- `.env`：包含本地 API Key 或邮箱信息，不能上传。
- `backups/`：运行时备份 ZIP，体积大且无必要上传。
- `reports/`：行情和信号运行结果，属于本地生成数据。
- `logs/`：运行日志。
- `data/*.sqlite3` 和数据库备份：本地知识库和上传文档索引。
- `patch_*.py`：历史补丁脚本，最终代码已经合并，不再需要。
- `diagnose_*.py`：历史诊断脚本，改由 `scripts/diagnose_project.py` 统一诊断。
- `README_v*.md`：历史版本说明，整合进主 README 和 docs。
- `requirements_v*.txt`：历史依赖文件，整合为根目录 `requirements.txt`。
- `*.bak*`：历史备份文件。
- `__pycache__/`：Python缓存。

保留原则：

- 保留最终运行所需的 Python 模块。
- 保留 `streamlit_app.py` 和 `streamlit_realtime.py` 的功能入口。
- 保留 Skills 文档。
- 保留配置模板和安装脚本。
