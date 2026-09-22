$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Jalankan scripts\install.ps1 terlebih dahulu.' }
$runtimePath = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$env:VPN_MODE = 'existing'
$env:ALLOWED_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
$env:VITE_API_URL = 'http://127.0.0.1:8787'
$envPath = Join-Path $projectRoot '.env'
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in Get-Content -LiteralPath $envPath) {
        if ($line -match '^\s*([A-Z_]+)=(.*)$') {
            $envName = $matches[1]
            $envValue = $matches[2].Trim().Trim('"').Trim("'")
            if ($envName -in @('APP_ACCESS_KEY','JOB_TTL_SECONDS','MAX_PAGES','MAX_TOTAL_MB')) {
                [Environment]::SetEnvironmentVariable($envName, $envValue, 'Process')
            }
        }
    }
}
foreach ($port in @(8787,5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port sedang digunakan. Periksa proses sebelum menjalankan aplikasi lagi."
    }
}
$backend = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.app:app','--app-dir',('"' + $projectRoot + '"'),'--host','127.0.0.1','--port','8787','--no-access-log') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'backend.log') -RedirectStandardError (Join-Path $runtimePath 'backend-error.log')
$nodePath = (Get-Command node.exe).Source
$vitePath = Join-Path $projectRoot 'node_modules\vite\bin\vite.js'
$frontend = Start-Process -FilePath $nodePath -ArgumentList @(('"' + $vitePath + '"'),'--host','127.0.0.1','--port','5173','--strictPort') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'frontend.log') -RedirectStandardError (Join-Path $runtimePath 'frontend-error.log')
@{backend=$backend.Id; frontend=$frontend.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'processes.json')
Write-Host 'Arsip: http://127.0.0.1:5173'
Write-Host 'Mode lokal menggunakan VPN laptop yang sudah aktif.'
