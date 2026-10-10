# Backend en local

El API está en `palajaba-back`. Hace falta Python 3.11 y MongoDB en `mongodb://localhost:27017`.

Desde `palajaba-back`:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\run.ps1
```

El `.env` es opcional: sin él se usa la base `ecommerce` en `localhost:27017`. `run.ps1` libera el puerto 8081 y levanta el API en http://127.0.0.1:8081.

Si falta `ELTOQUE_API_KEY`, el servidor arranca igual y solo avisa que no pudo refrescar las tasas.
