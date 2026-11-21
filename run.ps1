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
try {
    # HTTPX uses proxy environment variables, not Windows' automatic proxy settings.
    if (-not $env:HTTPS_PROXY -and -not $env:ALL_PROXY) {
        $githubUri = [uri]"https://api.github.com"
        $systemProxy = [System.Net.WebRequest]::GetSystemWebProxy().GetProxy($githubUri)
        if ($systemProxy.AbsoluteUri -ne $githubUri.AbsoluteUri) {
            $env:HTTPS_PROXY = $systemProxy.AbsoluteUri
            $env:NO_PROXY = (@($previousNoProxy, "127.0.0.1", "localhost") | Where-Object { $_ }) -join ","
            Write-Host "Using the Windows-configured HTTPS proxy."
        }
    }
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8765
} finally {
    $env:HTTPS_PROXY = $previousHttpsProxy
    $env:NO_PROXY = $previousNoProxy
}
