$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSScriptRoot
Set-Location $project

$render = Get-Command render -ErrorAction SilentlyContinue
if ($render) {
    $renderPath = $render.Source
} else {
    $renderPath = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\Render.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\render.exe'
    if (-not (Test-Path $renderPath)) { throw 'Render CLI tidak ditemukan. Pasang dengan winget install Render.CLI.' }
}

$serviceName = 'unair-repository-downloader-kjl'
$serviceUrl = "https://$serviceName.onrender.com"
$secretFile = Join-Path $project '.runtime\render-app-key.txt'
New-Item -ItemType Directory -Path (Split-Path $secretFile) -Force | Out-Null
if (-not (Test-Path $secretFile)) {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $newKey = ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
    [IO.File]::WriteAllText($secretFile, $newKey)
}
$accessKey = [IO.File]::ReadAllText($secretFile).Trim()

$servicesJson = & $renderPath services --output json
if ($LASTEXITCODE -ne 0) { throw 'Render CLI belum siap. Jalankan render login dan render workspace set.' }
$services = $servicesJson | ConvertFrom-Json
$existing = @($services) | Where-Object { $_ -and ($_.name -eq $serviceName -or $_.service.name -eq $serviceName) } | Select-Object -First 1
if ($existing) {
    Write-Host "Layanan sudah ada: $serviceName"
    Write-Host "URL: $serviceUrl"
    Write-Host "Kode akses tersimpan di: $secretFile"
    exit 0
}

$origin = "$serviceUrl,https://unair-repository-downloader.vercel.app"
$created = & $renderPath services create `
    --name $serviceName --type web_service `
    --repo 'https://github.com/Ahmadlazim-03/unair-repository-downloader' `
    --branch main --runtime docker --plan free --region singapore `
    --health-check-path /health `
    --env-var 'VPN_MODE=portal' `
    --env-var "ALLOWED_ORIGINS=$origin" `
    --env-var "APP_ACCESS_KEY=$accessKey" `
    --output json
if ($LASTEXITCODE -ne 0) { throw 'Render menolak pembuatan layanan. Periksa akun, billing, dan workspace di dashboard Render.' }
$service = $created | ConvertFrom-Json
Write-Host "Layanan dibuat: $($service.id)"
Write-Host "URL: $serviceUrl"
Write-Host "Kode akses tersimpan di: $secretFile"
Write-Host 'Tunggu deploy selesai, lalu jalankan scripts/check-production.py pada URL ini.'
