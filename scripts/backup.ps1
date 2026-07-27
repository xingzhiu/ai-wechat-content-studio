$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupDir = Join-Path $ProjectRoot "data\backups\$Stamp"
New-Item -ItemType Directory -Force $BackupDir | Out-Null
docker compose exec -T postgres pg_dump -U ai_news -d ai_news -Fc > (Join-Path $BackupDir 'database.dump')
Copy-Item 'data\assets' (Join-Path $BackupDir 'assets') -Recurse -Force
Copy-Item 'data\exports' (Join-Path $BackupDir 'exports') -Recurse -Force
Write-Host "备份完成: $BackupDir"

