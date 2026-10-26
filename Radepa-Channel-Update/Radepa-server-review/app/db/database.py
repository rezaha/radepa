from __future__ import annotations
import sqlite3
from pathlib import Path
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)
_DB_PATH: str = ""

def init_db(db_path: str) -> None:
    global _DB_PATH
    _DB_PATH = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).parent / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.executescript(schema)
    logger.info("Database initialised at %s", db_path)

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
