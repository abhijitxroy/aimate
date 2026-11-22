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
        $proxyResolver = [System.Net.WebRequest]::GetSystemWebProxy()
        $systemProxy = $proxyResolver.GetProxy($githubUri)
        if ($systemProxy -and $systemProxy.AbsoluteUri -ne $githubUri.AbsoluteUri) {
            $env:HTTPS_PROXY = $systemProxy.AbsoluteUri
            # Preserve the system PAC's direct route for configured intranet services.
            $directHosts = @("127.0.0.1", "localhost")
            $connectionUrls = & $pythonPath -c 'import json; from app.store import Store; print(json.dumps([s.get("url", "") for s in Store().config().values() if isinstance(s, dict)]))'
            if ($LASTEXITCODE -ne 0) { throw "Cannot read saved connection URLs for proxy routing." }
            foreach ($connectionUrl in ($connectionUrls | ConvertFrom-Json)) {
                if (-not $connectionUrl) { continue }
                $connectionUri = [uri]$connectionUrl
                $connectionProxy = $proxyResolver.GetProxy($connectionUri)
                if (-not $connectionProxy -or $connectionProxy.AbsoluteUri -eq $connectionUri.AbsoluteUri) {
                    $directHosts += $connectionUri.Host
                }
            }
            $env:NO_PROXY = (@($previousNoProxy) + $directHosts | Where-Object { $_ } | Select-Object -Unique) -join ","
            Write-Host "Using the Windows-configured HTTPS proxy."
        }
    }
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8765
} finally {
    $env:HTTPS_PROXY = $previousHttpsProxy
    $env:NO_PROXY = $previousNoProxy
}
