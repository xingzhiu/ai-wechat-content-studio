$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env'; Write-Host '已创建 .env，请先修改密码和密钥后重新运行。'; exit 1 }
docker compose up -d --build
Write-Host '审核后台: http://localhost:8080  n8n: http://localhost:5678  API文档: http://localhost:8000/docs'

