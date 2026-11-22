"""Build the deterministic demo warehouse at data/northwind.sqlite."""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "northwind.sqlite"
SEED_SQL = ROOT / "data" / "seed.sql"

COUNTRIES = ["USA", "UK", "Germany", "France", "India", "Canada", "Japan", "Brazil"]
CITIES = ["New York", "London", "Berlin", "Paris", "Mumbai", "Toronto", "Tokyo", "Sao Paulo"]
SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
STATUSES = ["Shipped", "Delivered", "Processing", "Cancelled"]
CATEGORIES = ["Beverages", "Condiments", "Dairy", "Grains", "Produce", "Meat", "Snacks", "Electronics"]
FIRST = ["Ann", "Bob", "Cara", "Dan", "Elena", "Farah", "Gus", "Hana"]
LAST = ["Smith", "Jones", "Muller", "Dubois", "Sharma", "Brown", "Tanaka", "Silva"]


def build(db_path: Path = DB_PATH) -> Path:
    rng = random.Random(42)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.executescript(SEED_SQL.read_text(encoding="utf-8"))

    customers = [
        (i, f"{rng.choice(FIRST)} {rng.choice(LAST)} Trading {i}", rng.choice(FIRST),
         rng.choice(CITIES), rng.choice(COUNTRIES), rng.choice(SEGMENTS))
        for i in range(1, 21)
    ]
    categories = [(i, name) for i, name in enumerate(CATEGORIES, 1)]
    suppliers = [(i, f"{rng.choice(LAST)} Supply Co {i}", rng.choice(COUNTRIES)) for i in range(1, 11)]
    stores = [(i, f"Store {rng.choice(CITIES)} {i}", rng.choice(CITIES), rng.choice(COUNTRIES)) for i in range(1, 6)]
    employees = [
        (i, f"{rng.choice(FIRST)} {rng.choice(LAST)}", rng.choice(COUNTRIES),
         (date(2018, 1, 1) + timedelta(days=rng.randint(0, 2500))).isoformat(),
         round(rng.uniform(45000, 140000), 2))
        for i in range(1, 9)
    ]
    products = [
        (i, f"Product {CATEGORIES[rng.randint(0, 7)]} {i}", rng.randint(1, 8),
         rng.randint(1, 10), round(rng.uniform(5, 500), 2), rng.randint(0, 500),
         rng.choice([0, 0, 0, 0, 1]))
        for i in range(1, 41)
    ]

    start = date(2024, 1, 1)
    end = date(2026, 6, 30)
    span = (end - start).days
    orders: list[tuple] = []
    for i in range(1, 301):
        odate = start + timedelta(days=rng.randint(0, span))
        ship = odate + timedelta(days=rng.randint(1, 14))
        orders.append((i, rng.randint(1, 20), rng.randint(1, 8), rng.randint(1, 5),
                       odate.isoformat(), ship.isoformat(), round(rng.uniform(5, 400), 2),
                       rng.choice(STATUSES)))

    items: list[tuple] = []
    item_id = 1
    for order_id, *_ in orders:
        for _ in range(rng.randint(2, 7)):
            items.append((item_id, order_id, rng.randint(1, 40), rng.randint(1, 12),
                          round(rng.uniform(5, 500), 2), rng.choice([0, 0, 0, 0.05, 0.1])))
            item_id += 1

    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
    conn.executemany("INSERT INTO categories VALUES (?,?)", categories)
    conn.executemany("INSERT INTO suppliers VALUES (?,?,?)", suppliers)
    conn.executemany("INSERT INTO stores VALUES (?,?,?,?)", stores)
    conn.executemany("INSERT INTO employees VALUES (?,?,?,?,?)", employees)
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", products)
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", items)
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = build()
    print(f"Built {path} ({path.stat().st_size:,} bytes)")
