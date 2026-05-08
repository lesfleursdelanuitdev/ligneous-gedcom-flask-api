"""Shared pytest fixtures for the ligneous-python-api test suite."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the app package is importable when pytest is run from the repo.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Prefer local `.env`, then repo `.env.local` files (fills missing vars only).
try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:
    _load_dotenv = None
else:
    for path in (
        ROOT / ".env",
        ROOT.parent / "ligneous-frontend" / ".env.local",
        ROOT.parent / "the-gonsalves-family" / ".env.local",
    ):
        if path.is_file():
            _load_dotenv(path, override=False)

# Force Groq off for unit tests so the keyword fallback path is exercised.
os.environ.setdefault("GROQ_API_KEY", "")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: hit PostgreSQL via DATABASE_URL (skip in CI unless secrets are wired)",
    )
