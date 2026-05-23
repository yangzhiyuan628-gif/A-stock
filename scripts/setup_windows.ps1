# Windows 一键初始化脚本
# 用法：右键 PowerShell，以普通用户身份运行：
#   cd D:\csa\git\robote
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1

$ErrorActionPreference = "Stop"

Write-Host "[1/5] 创建虚拟环境 .venv" -ForegroundColor Cyan
if (!(Test-Path ".venv")) {
    python -m venv .venv
}

Write-Host "[2/5] 激活虚拟环境" -ForegroundColor Cyan
. .\.venv\Scripts\Activate.ps1

Write-Host "[3/5] 升级 pip" -ForegroundColor Cyan
python -m pip install --upgrade pip setuptools wheel

Write-Host "[4/5] 安装依赖" -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "[5/5] 初始化目录和数据库" -ForegroundColor Cyan
python .\scripts\init_project.py

Write-Host "完成。启动8501：powershell -File .\scripts\run_8501.ps1" -ForegroundColor Green
Write-Host "启动8502：powershell -File .\scripts\run_8502.ps1" -ForegroundColor Green
