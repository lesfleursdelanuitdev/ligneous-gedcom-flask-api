"""Configuration for ligneous-python-api."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5001"))

# Groq LLM (used for natural-language search).
# Place the real key in `.env` (gitignored), not in `.env.example`.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TIMEOUT_SECONDS = float(os.environ.get("GROQ_TIMEOUT_SECONDS", "20"))

# NL search execution caps (defense-in-depth alongside allowlisted SQL templates).
NL_MAX_ROWS = int(os.environ.get("NL_MAX_ROWS", "2000"))
NL_MAX_PROMPT_CHARS = int(os.environ.get("NL_MAX_PROMPT_CHARS", "1000"))

# When false, never insert into research.query_runs / research.result_sets (useful for DB users
# without write access to the research schema).
def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


NL_PERSIST_QUERY_RUNS = _env_bool("NL_PERSIST_QUERY_RUNS", True)
