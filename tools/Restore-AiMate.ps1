param(
    [string]$Backup,
    [string]$Destination = (Join-Path $env:USERPROFILE "AiMate")
)
$ErrorActionPreference = "Stop"
$Destination = [System.IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $Destination) { throw "Destination exists. Use -Destination with a new folder; existing data will not be replaced." }
if (-not $Backup) {
    $backups = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.aimate-backup" -File)
    if ($backups.Count -ne 1) { throw "Choose the file: .\Restore-AiMate.ps1 -Backup '.\AiMate-....aimate-backup'" }
    $Backup = $backups[0].FullName
}
$Backup = (Resolve-Path -LiteralPath $Backup).Path
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Install Python 3.11 or newer with the Windows Python launcher, then run this command again." }
& py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }
$bootstrap = Join-Path $PSScriptRoot ".migration-venv"
if (-not (Test-Path -LiteralPath (Join-Path $bootstrap "Scripts\python.exe"))) {
    & py -3 -m venv $bootstrap
    if ($LASTEXITCODE -ne 0) { throw "Could not create the migration Python environment." }
}
$pythonPath = Join-Path $bootstrap "Scripts\python.exe"
& $pythonPath -m pip install "cryptography>=43,<47" "sqlcipher3-wheels==0.5.7"
if ($LASTEXITCODE -ne 0) { throw "Dependency download failed. Check internet/proxy access and rerun; nothing has been restored yet." }
& $pythonPath (Join-Path $PSScriptRoot "portable_backup.py") restore --backup $Backup --destination $Destination
if ($LASTEXITCODE -ne 0) { throw "Restore failed. No existing workspace was replaced." }
& py -3 -m venv (Join-Path $Destination ".venv")
if ($LASTEXITCODE -ne 0) { throw "Data restored. Create .venv inside the restored folder before starting AiMate." }
$appPython = Join-Path $Destination ".venv\Scripts\python.exe"
& $appPython -m pip install -r (Join-Path $Destination "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Your app and data are safely restored. Retry this from the restored folder:"
    Write-Host ".\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
Write-Host "Ready. Start AiMate:"
Write-Host "cd '$Destination'"
Write-Host ".\run_aimate.ps1"
Write-Host "Then open http://127.0.0.1:8765. Use .\run_aimate.ps1 -Secure for authenticator login."
