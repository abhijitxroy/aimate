# Optional Windows launch-time routing; never changes stored credentials or TLS.
function Get-AiMateProxyRoutes {
    param(
        [string[]]$ConnectionUrls = @(),
        [string]$HttpsProxy = "",
        [string]$AllProxy = "",
        [string]$NoProxy = "",
        [scriptblock]$ResolveProxy,
        [switch]$Disabled
    )
    if ($Disabled) {
        return [pscustomobject]@{ HttpsProxy = $HttpsProxy; NoProxy = $NoProxy }
    }
    if (-not $ResolveProxy) {
        $resolver = [System.Net.WebRequest]::GetSystemWebProxy()
        $ResolveProxy = { param($target) $resolver.GetProxy($target) }.GetNewClosure()
    }
    $selectedProxy = $HttpsProxy
    if (-not $HttpsProxy -and -not $AllProxy) {
        $githubUri = [uri]"https://api.github.com"
        $githubProxy = & $ResolveProxy $githubUri
        if ($githubProxy -and $githubProxy.AbsoluteUri -ne $githubUri.AbsoluteUri) {
            $selectedProxy = $githubProxy.AbsoluteUri
        }
    }
    # An inherited external proxy must not suppress the PAC's intranet bypasses.
    $directHosts = @("127.0.0.1", "localhost")
    foreach ($connectionUrl in $ConnectionUrls) {
        if (-not $connectionUrl) { continue }
        $connectionUri = [uri]$connectionUrl
        if (-not $connectionUri.IsAbsoluteUri -or $connectionUri.Scheme -notin @("http", "https")) {
            throw "A saved connection URL is invalid; check Connections & settings."
        }
        $connectionProxy = & $ResolveProxy $connectionUri
        if (-not $connectionProxy -or $connectionProxy.AbsoluteUri -eq $connectionUri.AbsoluteUri) {
            $directHosts += $connectionUri.Host
        }
    }
    $bypasses = @($NoProxy -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $bypasses = @($bypasses + $directHosts | Select-Object -Unique)
    return [pscustomobject]@{ HttpsProxy = $selectedProxy; NoProxy = $bypasses -join "," }
}
