import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "enterprise.db"

def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE customers (
        customer_id TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        region TEXT NOT NULL,
        tier TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE orders (
        order_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        discount_pct REAL NOT NULL,
        order_date TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    );
    """)

    customers = [
        ("CUST-001", "Apex Global APAC", "APAC", "Enterprise"),
        ("CUST-002", "Nippon Tech Solutions", "APAC", "Standard"),
        ("CUST-003", "Bavaria Systems GmbH", "EMEA", "Enterprise"),
        ("CUST-004", "Nordic Data Labs", "EMEA", "Standard"),
        ("CUST-005", "Sierra Cloud Corp", "NA", "Enterprise")
    ]
    cursor.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers)

    # Note: Apex Global (APAC) received an 18% discount, violating the 15% cap
    orders = [
        ("ORD-101", "CUST-001", "Enterprise AI Storage Array 500TB", 2, 45000.0, 18.0, "2026-08-14"),
        ("ORD-102", "CUST-002", "Standard Cloud Gateway", 5, 8000.0, 5.0, "2026-08-20"),
        ("ORD-103", "CUST-003", "Enterprise AI Storage Array 1PB", 1, 85000.0, 12.0, "2026-08-25"),
        ("ORD-104", "CUST-004", "Hybrid Cache Appliance", 4, 12000.0, 8.0, "2026-09-02"),
        ("ORD-105", "CUST-005", "Enterprise AI Storage Array 500TB", 3, 45000.0, 14.0, "2026-09-10")
    ]
    cursor.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", orders)

    conn.commit()
    conn.close()
    print(f"Enterprise database seeded successfully at: {DB_PATH}")

if __name__ == "__main__":
    init_db()
