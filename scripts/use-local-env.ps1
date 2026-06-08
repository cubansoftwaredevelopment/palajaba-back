# Activa desarrollo local. Guarda .env actual en .env.production si aún no existe.
$BackendRoot = Split-Path $PSScriptRoot -Parent
$productionFile = Join-Path $BackendRoot ".env.production"
$localFile = Join-Path $BackendRoot ".env.local.dev"
$activeFile = Join-Path $BackendRoot ".env"

if (-not (Test-Path $localFile)) {
    Write-Error "No se encontró .env.local.dev"
    exit 1
}

if (-not (Test-Path $productionFile)) {
    if (Test-Path $activeFile) {
        Copy-Item $activeFile $productionFile
        Write-Host "Respaldo de producción creado: backend/.env.production"
    } else {
        Write-Warning "No había .env activo; no se creó respaldo."
    }
}

Copy-Item $localFile $activeFile -Force
Write-Host "Backend en modo LOCAL (MongoDB local, backend :8081)."
Write-Host "Para volver a producción: .\scripts\use-production-env.ps1"
