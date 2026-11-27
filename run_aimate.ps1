param([switch]$Secure)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Set up the virtual environment first. See README.md."
}
Write-Host "AiMate: http://127.0.0.1:8765"
Write-Host "Local app password: .data/access-password.txt (created on first start), or APP_PASSWORD if you set it."
$previousHttpsProxy = $env:HTTPS_PROXY
$previousNoProxy = $env:NO_PROXY
$previousDevLogin = $env:AIMATE_DEV_LOGIN
try {
    if ($Secure) { $env:AIMATE_DEV_LOGIN = "0" }
    else { $env:AIMATE_DEV_LOGIN = "1"; Write-Host "Local dev mode: login bypass enabled. Use .\run.ps1 -Secure for authenticator/password sign-in." }
    # Recheck intranet bypasses even when the parent shell already set a proxy.
    if ($env:AIMATE_PROXY_ROUTING -ne "0") {
        . (Join-Path $PSScriptRoot "tools\proxy_routing.ps1")
        $connectionUrls = @'
import json
from app.store import Store
store = Store()
print(json.dumps([source.get("url", "") for source in store.config().values() if isinstance(source, dict)]))
store.db.close()
'@ | & $pythonPath -
        if ($LASTEXITCODE -ne 0) { throw "Cannot read saved connection URLs for proxy routing." }
        $routes = Get-AiMateProxyRoutes -ConnectionUrls ($connectionUrls | ConvertFrom-Json) `
            -HttpsProxy $env:HTTPS_PROXY -AllProxy $env:ALL_PROXY -NoProxy $env:NO_PROXY
        $env:HTTPS_PROXY = $routes.HttpsProxy
        $env:NO_PROXY = $routes.NoProxy
        Write-Host "Windows proxy routing checked; direct service routes preserved."
    }
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8765
} finally {
    $env:HTTPS_PROXY = $previousHttpsProxy
    $env:NO_PROXY = $previousNoProxy
    $env:AIMATE_DEV_LOGIN = $previousDevLogin
}
