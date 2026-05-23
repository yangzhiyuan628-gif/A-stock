# 短线打板机器人｜Stock Robot

> 盘中盯盘 + 自定义短线规则 + AI 游资复盘 + 小市值高弹性筛选 + Skills 技能库。  
> 本项目只做行情观察、复盘辅助和规则统计，不自动下单，不构成投资建议。

## 1\. 项目入口

本项目包含两个 Streamlit 应用：

|入口|端口|作用|
|-|-:|-|
|`streamlit\_app.py`|8501|盘后复盘、AI 游资复盘、小市值候选池、Skills 技能库|
|`streamlit\_realtime.py`|8502|盘中实时盯盘、自定义规则、信号归因、邮件提醒、大模型问股|

启动方式：

```powershell
streamlit run .\streamlit_app.py --server.port 8501
streamlit run .\streamlit_realtime.py --server.port 8502
```

也可以使用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run\_8501.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run\_8502.ps1
```

## 2\. 当前功能总览

### 8502：盘中盯盘系统

* 沪深 A 股实时行情获取与主板非 ST 过滤。
* 涨幅榜、涨速榜、行业联动、概念联动。
* 自定义短线规则：半路、扫板、排板、回封、风控。
* 92 科比模式化规则归因：市场模式、题材人气、中位股过滤、股性风险。
* 小市值高弹性优先：中军参考，大市值例外。
* 邮件提醒：同股同规则去重，防止重复轰炸。
* 大模型问股：可读取行情、图片、PDF/知识库、联网检索和 Skills。
* 全天日志记录：用于盘后统计和回放。

### 8501：盘后复盘系统

* 读取 8502 全天日志和信号快照。
* AI 游资复盘：情绪、主线、首板、连板、风险。
* 小市值高弹性复盘池：明日重点小市值候选、中军参考、大市值核心例外。
* Skills 技能库：战法、PDF、复盘结论、规则胜率沉淀。
* 盘后信号效果统计与参数优化建议。

## 3\. 目录结构

```text
robote/
├─ streamlit\_app.py              # 8501 盘后复盘入口
├─ streamlit\_realtime.py         # 8502 实时盯盘入口
├─ main.py                       # 盘后行情抓取与报告生成
├─ requirements.txt              # 统一依赖
├─ .env.example                  # 环境变量模板
├─ scripts/                      # 安装、启动、诊断、清理脚本
├─ config/                       # 配置模板与本地映射
├─ data/                         # 本地数据库，运行时生成，不上传GitHub
├─ reports/                      # 运行结果，运行时生成，不上传GitHub
├─ logs/                         # 日志，运行时生成，不上传GitHub
├─ backups/                      # 备份，运行时生成，不上传GitHub
└─ skills/                       # Skills 技能库
```

## 4\. 安装

详细 Windows 安装流程见：[docs/INSTALL\_WINDOWS.md](docs/INSTALL_WINDOWS.md)。

最快方式：

```powershell
git clone <your-repo-url>
cd robote
powershell -ExecutionPolicy Bypass -File .\\scripts\\setup\_windows.ps1
```

然后编辑 `.env`，填入自己的 DeepSeek/OpenAI API Key 和邮箱授权码。

## 5\. 常用命令

```powershell
# 初始化项目目录和数据库
python .\scripts\\init_project.py

# 诊断项目
python .\scripts\\diagnose_project.py

# 启动 8501
powershell -ExecutionPolicy Bypass -File .\scripts\run_8501.ps1

# 启动 8502
powershell -ExecutionPolicy Bypass -File .\scripts\run_8502.ps1

# 清理运行时输出
python .\scripts\clean_runtime.py
```

## 6\. API Key 和联网

复制 `.env.example` 为 `.env`：

```powershell
copy .env.example .env
```

填写：

```text
DEEPSEEK_API_KEY=你的DeepSeek Key
AI_PROVIDER=deepseek
AI_MODEL=deepseek-chat
AI_BASE_URL=https://api.deepseek.com
```

如果遇到 `SSLEOFError` 或 `ProxyError`，进入页面底部的 **Network Guard** 面板，先运行网络诊断，再按提示清理代理或启用 `trust\_env=False`。

## 7\. 邮件提醒

邮件提醒使用 SMTP。QQ 邮箱一般需要“授权码”，不是登录密码。

`.env` 示例：

```text
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your\_email@qq.com
SMTP_SENDER=your\_email@qq.com
SMTP_PASSWORD=你的邮箱授权码
SMTP_RECIPIENTS=receiver@example.com
```

8502 页面中进入“邮件提醒”后，先发送测试邮件，再打开自动提醒。

## 8\. 风险声明

本项目只用于行情观察、策略研究、复盘统计和大模型辅助分析。任何信号都不是买卖建议，不能替代个人判断和风险控制。

