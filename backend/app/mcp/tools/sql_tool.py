import os
import sqlite3
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[4] / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = Path(__file__).resolve().parents[2] / "database" / "enterprise.db"
FORBIDDEN = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE"]

def _sanitize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {}
    for k, v in record.items():
        if isinstance(v, Decimal):
            sanitized[k] = float(v)
        elif isinstance(v, (date, datetime)):
            sanitized[k] = v.isoformat()
        else:
            sanitized[k] = v
    return sanitized

def get_database_schema() -> str:
    """Returns database schemas from Supabase Postgres or local SQLite."""
    if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            ORDER BY table_name, ordinal_position;
        """)
        rows = cursor.fetchall()
        conn.close()
        
        tables = {}
        for table, col, dtype in rows:
            tables.setdefault(table, []).append(f"  {col} {dtype}")
        schema_str = "\n\n".join([f"CREATE TABLE {t} (\n" + ",\n".join(cols) + "\n);" for t, cols in tables.items()])
        return schema_str
    else:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        schemas = [row[0] for row in cursor.fetchall() if row[0] is not None]
        conn.close()
        return "\n\n".join(schemas)

def execute_readonly_query(sql_query: str) -> Dict[str, Any]:
    norm = sql_query.strip().upper()
    for kw in FORBIDDEN:
        if kw in norm.split():
            return {"error": f"Security violation: Query contains '{kw}'"}
    if not norm.startswith("SELECT") and not norm.startswith("WITH"):
        return {"error": "Security violation: Only SELECT/WITH statements are allowed"}

    try:
        if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
            import psycopg2
            from psycopg2.extras import RealDictCursor
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(sql_query)
            rows = cursor.fetchall()
            result = [_sanitize_record(dict(row)) for row in rows]
            conn.close()
            return {"row_count": len(result), "data": result}
        else:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql_query)
            rows = cursor.fetchall()
            result = [_sanitize_record(dict(row)) for row in rows]
            conn.close()
            return {"row_count": len(result), "data": result}
    except Exception as e:
        return {"error": f"SQL Error: {str(e)}"}
