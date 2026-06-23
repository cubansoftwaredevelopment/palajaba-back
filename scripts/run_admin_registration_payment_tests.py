"""
Ejecuta tests de monto 0 en aprobación admin (unit + integración).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\run_admin_registration_payment_tests.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    python = BACKEND_ROOT / "venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    modules = [
        "tests.test_registrations_payment_unit",
        "tests.test_admin_registration_payment_integration",
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)

    result = subprocess.run(
        [str(python), "-m", "unittest", *modules, "-v"],
        cwd=BACKEND_ROOT,
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
