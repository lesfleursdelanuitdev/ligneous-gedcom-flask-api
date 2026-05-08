"""Shared pytest fixtures for the ligneous-python-api test suite."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the app package is importable when pytest is run from the repo.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force Groq off for unit tests so the keyword fallback path is exercised.
os.environ.setdefault("GROQ_API_KEY", "")
