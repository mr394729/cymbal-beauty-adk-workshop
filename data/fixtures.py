"""Shim: the fixture constants live in the shipped package (agents/cymbal_store_ops/fixtures.py).

Kept here so `python data/generate.py` (stdlib only) and the tests can keep doing `import fixtures`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.cymbal_store_ops.fixtures import *  # noqa: E402,F403
