# 启动 8501：盘后复盘 / AI游资复盘
$ErrorActionPreference = "Stop"
cd $PSScriptRoot\..
if (Test-Path ".venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
streamlit run .\streamlit_app.py --server.port 8501
