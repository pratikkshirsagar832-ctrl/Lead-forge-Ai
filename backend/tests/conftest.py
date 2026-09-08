"""Shared fixtures for the backend test suite.

Kept deliberately small — most services are tested with their own local fakes
to stay deterministic and network-free.
"""

import sys
from pathlib import Path

import pytest

# Allow running `pytest` from the repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def backend_dir() -> Path:
    return BACKEND_DIR
