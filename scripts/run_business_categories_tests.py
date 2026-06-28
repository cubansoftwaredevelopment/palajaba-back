"""
Ejecuta tests de categorías globales de negocio (unit + integración).

Uso (desde backend/):
  .\\venv\\Scripts\\python.exe scripts\\run_business_categories_tests.py
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

    steps = [
        [str(python), str(BACKEND_ROOT / "scripts" / "test_business_category_mapping.py")],
        [str(python), "-m", "unittest", "tests.test_business_categories_integration", "-v"],
    ]

    for command in steps:
        result = subprocess.run(command, cwd=BACKEND_ROOT)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
