$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Gagal membuat Python virtual environment.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Instalasi dependensi Python gagal.' }
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Instalasi dependensi frontend gagal.' }
    Write-Host 'Instalasi selesai. Jalankan .\scripts\start-local.ps1'
} finally { Pop-Location }
