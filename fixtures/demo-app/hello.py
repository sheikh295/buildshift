"""Compat shim for older smokes — prefer demo_app.core."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from demo_app.core import greet  # noqa: E402

__all__ = ["greet"]


if __name__ == "__main__":
    print(greet())
