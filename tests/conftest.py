"""Shared test fixtures; quick tests never require the raw research dataset."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


@pytest.fixture
def project_root():
    return ROOT
