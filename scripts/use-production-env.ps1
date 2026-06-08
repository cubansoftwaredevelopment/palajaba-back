# Restaura la configuración de producción desde .env.production
$BackendRoot = Split-Path $PSScriptRoot -Parent
$productionFile = Join-Path $BackendRoot ".env.production"
$activeFile = Join-Path $BackendRoot ".env"

if (-not (Test-Path $productionFile)) {
    Write-Error "No existe backend/.env.production. Ejecuta primero use-local-env.ps1 o crea el respaldo manualmente."
    exit 1
}

Copy-Item $productionFile $activeFile -Force
Write-Host "Backend en modo PRODUCCIÓN (Atlas / .env.production restaurado)."
