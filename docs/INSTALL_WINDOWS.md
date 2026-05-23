# Windows 详细安装教程

以下假设项目放在：

```text
D:\csa\git\robote
```

## 1. 安装 Python

推荐 Python 3.10、3.11 或 3.12。安装时勾选：

```text
Add python.exe to PATH
```

检查：

```powershell
python --version
pip --version
```

## 2. 下载项目

方式一：Git 克隆

```powershell
cd D:\csa\git
git clone <your-repo-url> robote
cd robote
```

方式二：下载 ZIP 后解压到：

```text
D:\csa\git\robote
```

## 3. 创建虚拟环境并安装依赖

推荐直接运行：

```powershell
cd D:\csa\git\robote
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

手动安装也可以：

```powershell
cd D:\csa\git\robote
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python .\scripts\init_project.py
```

## 4. 配置 API Key

复制环境变量模板：

```powershell
copy .env.example .env
notepad .env
```

DeepSeek 示例：

```text
AI_PROVIDER=deepseek
AI_MODEL=deepseek-chat
AI_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=你的Key
AI_API_KEY=你的Key
```

OpenAI 示例：

```text
AI_PROVIDER=openai
AI_MODEL=gpt-5.5
AI_BASE_URL=
OPENAI_API_KEY=你的Key
AI_API_KEY=你的Key
```

## 5. 配置邮箱提醒，可选

QQ 邮箱示例：

```text
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=你的邮箱@qq.com
SMTP_SENDER=你的邮箱@qq.com
SMTP_PASSWORD=你的邮箱授权码
SMTP_RECIPIENTS=接收提醒的邮箱@example.com
```

## 6. 启动 8501

```powershell
cd D:\csa\git\robote
powershell -ExecutionPolicy Bypass -File .\scripts\run_8501.ps1
```

浏览器打开：

```text
http://localhost:8501
```

8501 用于盘后复盘、AI 游资复盘、小市值候选池和 Skills。

## 7. 启动 8502

新开一个 PowerShell：

```powershell
cd D:\csa\git\robote
powershell -ExecutionPolicy Bypass -File .\scripts\run_8502.ps1
```

浏览器打开：

```text
http://localhost:8502
```

8502 用于实时盯盘、自定义规则、大模型问股和邮件提醒。

## 8. 第一次使用顺序

1. 启动 8502。
2. 查看涨幅榜、涨速榜是否有数据。
3. 进入“大模型问股”，测试 API 是否正常。
4. 进入“邮件提醒”，先发送测试邮件。
5. 盘中运行 8502，让它记录信号。
6. 盘后打开 8501，进入 AI 游资复盘。
7. 生成小市值高弹性复盘和明日观察方向。

## 9. 常见问题

### 9.1 DeepSeek SSLEOFError / ProxyError

进入页面底部 **Network Guard**：

1. 运行网络诊断。
2. 如检测到代理变量，点击“清理当前进程代理变量”。
3. 如果仍失败，勾选“AI API不继承系统代理 trust_env=False”。
4. 保存并重启 8501/8502。

### 9.2 AkShare / 东方财富接口失败

可能是网络、代理或接口临时限制。可以：

```powershell
pip install -U akshare requests urllib3 certifi
```

然后重启 8502。

### 9.3 安装 pytdx 失败

`pytdx` 主要用于可选的通达信本地数据。如果暂时安装失败，可以先注释 requirements.txt 里的 `pytdx`，项目仍可依赖 AkShare 运行。

### 9.4 页面没有数据

先运行：

```powershell
python main.py
```

或在 8501 左侧点击“刷新行情数据”。

## 10. 诊断

```powershell
python .\scripts\diagnose_project.py
```

如果报错，把完整输出复制给维护者。
