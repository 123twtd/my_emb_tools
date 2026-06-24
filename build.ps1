# 串口助手 v1.0 打包脚本
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[1/4] 创建打包虚拟环境..."
if (-not (Test-Path ".venv-build")) {
    python -m venv .venv-build
}

& ".\.venv-build\Scripts\Activate.ps1"

Write-Host "[2/4] 安装依赖..."
pip install -q -r requirements.txt -r requirements-build.txt

Write-Host "[3/4] PyInstaller 打包..."
pyinstaller --clean --noconfirm build.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败"
}

Write-Host "[4/4] 完成"
Write-Host "输出目录: dist\SerialAssistant_v1.0\"
Write-Host "主程序:   dist\SerialAssistant_v1.0\SerialAssistant_v1.0.exe"
