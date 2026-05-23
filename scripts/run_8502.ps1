# 启动 8502：实时盯盘系统
$ErrorActionPreference = "Stop"
cd $PSScriptRoot\..
if (Test-Path ".venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
streamlit run .\streamlit_realtime.py --server.port 8502
