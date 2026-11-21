$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Set up the virtual environment first. See README.md."
}
Write-Host "AiMate: http://127.0.0.1:8765"
Write-Host "Local app password: .data/access-password.txt (created on first start), or APP_PASSWORD if you set it."
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8765
