$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot '.runtime\processes.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'Tidak ada proses lokal tercatat.'; exit }
$processes = Get-Content -LiteralPath $pidFile | ConvertFrom-Json
foreach ($processId in @($processes.backend, $processes.frontend)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -and $process.CommandLine.Contains($projectRoot)) {
        Stop-Process -Id $processId -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $pidFile
Write-Host 'Proses lokal milik proyek dihentikan.'
