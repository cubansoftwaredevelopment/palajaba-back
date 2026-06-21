"""
Ejecuta la suite de catálogo público de tienda (unit + integración).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\run_store_catalog_tests.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    python = BACKEND_ROOT / "venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    modules = [
        "tests.test_store_catalog_unit",
        "tests.test_view_only_store_catalog_unit",
        "tests.test_store_catalog_integration",
        "tests.test_view_only_store_catalog_integration",
    ]

    result = subprocess.run(
        [str(python), "-m", "unittest", *modules, "-v"],
        cwd=BACKEND_ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
