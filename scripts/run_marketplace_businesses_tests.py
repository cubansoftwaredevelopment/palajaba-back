"""Ejecuta tests unitarios e integración del listado de negocios.

Uso (desde backend/):
  python scripts/run_marketplace_businesses_tests.py

Integración HTTP (requiere MongoDB; levanta backend en :8082 si :8081 no tiene la ruta):
  python scripts/test_marketplace_businesses.py
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def run_unit_tests() -> bool:
    suite = unittest.defaultTestLoader.discover(
        "tests",
        pattern="test_marketplace_businesses_unit.py",
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def run_integration_script() -> bool:
    script = BACKEND_ROOT / "scripts" / "test_marketplace_businesses.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=BACKEND_ROOT,
        check=False,
    )
    return completed.returncode == 0


if __name__ == "__main__":
    ok_unit = run_unit_tests()
    ok_integration = run_integration_script()
    raise SystemExit(0 if ok_unit and ok_integration else 1)
