param([Parameter(Mandatory=$true)][string]$BackupDir)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ResolvedBackup = (Resolve-Path $BackupDir).Path
$BackupRoot = (Resolve-Path (Join-Path $ProjectRoot 'data\backups')).Path
if (-not $ResolvedBackup.StartsWith($BackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw '只允许恢复本项目 data\backups 下的备份' }
Set-Location $ProjectRoot
Get-Content -Raw (Join-Path $ResolvedBackup 'database.dump') | docker compose exec -T postgres pg_restore -U ai_news -d ai_news --clean --if-exists
Copy-Item (Join-Path $ResolvedBackup 'assets\*') 'data\assets' -Recurse -Force
Copy-Item (Join-Path $ResolvedBackup 'exports\*') 'data\exports' -Recurse -Force
Write-Host '恢复完成'

