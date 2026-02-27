"""Database connection. Read-only on app tables; read/write on research schema."""
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from app.config import DATABASE_URL


@contextmanager
def get_connection():
    """Yield a DB connection. Caller must not hold long-lived transactions."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_read_only():
    """Verify we can read from the database (e.g. one app table). Returns (ok, message)."""
    if not DATABASE_URL:
        return False, "DATABASE_URL not set"
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                if row and row["ok"] == 1:
                    return True, "ok"
        return False, "unexpected response"
    except Exception as e:
        return False, str(e)
