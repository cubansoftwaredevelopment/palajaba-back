"""
Ejecuta la suite de orden de productos por categoría (unit + integración).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\run_catalog_product_sort_tests.py
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
        "tests.test_catalog_product_sort_unit",
        "tests.test_catalog_product_sort_integration",
    ]

    result = subprocess.run(
        [str(python), "-m", "unittest", *modules, "-v"],
        cwd=BACKEND_ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
