$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$previousDemoMode = $env:AIMATE_DEMO
$env:AIMATE_DEMO = "1"
try {
    & (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port 8765
} finally {
    if ($null -eq $previousDemoMode) {
        Remove-Item Env:AIMATE_DEMO
    } else {
        $env:AIMATE_DEMO = $previousDemoMode
    }
}
