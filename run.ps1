# Ejecutar siempre desde la carpeta backend (no desde venv\Scripts)
$BackendRoot = $PSScriptRoot
Set-Location $BackendRoot

& "$BackendRoot\venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8081
