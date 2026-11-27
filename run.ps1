# Ejecutar siempre desde la carpeta backend (no desde venv\Scripts)
$BackendRoot = $PSScriptRoot
Set-Location $BackendRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js no está en el PATH. Hace falta para auditar dependencias con osv-scanner."
    exit 1
}

$RepoRoot = Split-Path $BackendRoot -Parent
& node (Join-Path $RepoRoot "palajaba-front\scripts\audit-osv.mjs")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$port = 8081
Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*uvicorn app.main:app*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

$env:PYTHONPATH = $BackendRoot
# Sin --reload en Windows: el worker hijo puede cargar código viejo del intérprete del sistema.
& "$BackendRoot\venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port $port
