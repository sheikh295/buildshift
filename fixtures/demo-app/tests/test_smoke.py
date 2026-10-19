"""Deterministic CI gate for the local merge queue."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow `python -m unittest discover` without installing the package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from demo_app.core import greet  # noqa: E402


class SmokeTests(unittest.TestCase):
    def test_greet_default(self) -> None:
        self.assertEqual(greet(), "hello, world")

    def test_greet_name(self) -> None:
        self.assertEqual(greet("buildshift"), "hello, buildshift")


if __name__ == "__main__":
    unittest.main()
