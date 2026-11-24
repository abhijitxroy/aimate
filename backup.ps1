param([string]$OutputFolder)
$ErrorActionPreference = "Stop"
if (-not $OutputFolder) {
    $oneDriveRoot = $env:OneDriveCommercial
    if (-not $oneDriveRoot) { $oneDriveRoot = $env:OneDrive }
    if (-not $oneDriveRoot -or -not (Test-Path -LiteralPath $oneDriveRoot)) {
        throw "OneDrive folder was not found. Run .\backup.ps1 -OutputFolder 'YOUR_ONEDRIVE_FOLDER\AiMate-Migration'."
    }
    $OutputFolder = Join-Path $oneDriveRoot "AiMate-Migration"
}
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "AiMate's Python environment was not found." }
$OutputFolder = [System.IO.Path]::GetFullPath($OutputFolder)
New-Item -ItemType Directory -Path $OutputFolder -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "tools\portable_backup.py") -Destination $OutputFolder
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "app\device_key.py") -Destination $OutputFolder
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "app\database.py") -Destination $OutputFolder
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "tools\Restore-AiMate.ps1") -Destination $OutputFolder
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "docs\laptop-migration.md") -Destination (Join-Path $OutputFolder "START-HERE.md")
$backupPath = Join-Path $OutputFolder ("AiMate-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".aimate-backup")
Write-Host "Finish any current request and close AiMate's server before taking your final migration backup."
& $pythonPath (Join-Path $PSScriptRoot "tools\portable_backup.py") export --source $PSScriptRoot --output $backupPath
if ($LASTEXITCODE -ne 0) { throw "Backup failed. Your original workspace is unchanged." }
Write-Host "OneDrive migration folder: $OutputFolder"
Write-Host "Before surrendering this laptop: wait for OneDrive sync, then open OneDrive in your browser and confirm the backup and restore files are there."
Write-Host "On the new laptop: sign in to the same OneDrive account, download this folder, and run Restore-AiMate.ps1."
