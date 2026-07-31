"""Pytest path bootstrap for the fd-coding-law-bench-mcp project.

Lets ``import fd_coding_law_bench_mcp`` work without an editable install by
putting the project's ``src/`` on ``sys.path``. The package's own ``__init__``
then puts the law-template repo root on ``sys.path`` so ``import src.*`` works.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))
