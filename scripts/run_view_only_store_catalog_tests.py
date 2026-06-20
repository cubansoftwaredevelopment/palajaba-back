"""Ejecuta tests unitarios e integración del catálogo público (solo vista).

Uso (desde backend/):
  python scripts/run_view_only_store_catalog_tests.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        "tests",
        pattern="test_view_only_store_catalog_*.py",
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
