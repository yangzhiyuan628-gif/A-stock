# 同时启动 8501 和 8502
$ErrorActionPreference = "Stop"
cd $PSScriptRoot\..
if (Test-Path ".venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; . .\.venv\Scripts\Activate.ps1; streamlit run .\streamlit_app.py --server.port 8501"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; . .\.venv\Scripts\Activate.ps1; streamlit run .\streamlit_realtime.py --server.port 8502"
