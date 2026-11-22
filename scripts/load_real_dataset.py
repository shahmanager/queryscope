"""Load a real public dataset (Sample Superstore) into a QueryScope-compatible warehouse.

Source: Mohanad234128/Project_MSC_Sample_Superstore, Data/Sample_Superstore.csv
~9,994 rows of genuine retail transactions. The CSV is downloaded once and
cached under data/real/. No API key is involved.

Field mapping is deliberately explicit so the mapping can be audited:
  Sales / (Quantity * (1 - Discount)) -> order_items.unit_price
      which makes the derived revenue measure reproduce real Sales exactly.
"""

from __future__ import annotations

import csv
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "data" / "real"
CSV_PATH = REAL_DIR / "sample_superstore.csv"
DB_PATH = REAL_DIR / "superstore.sqlite"
SOURCE_URL = (
    "https://raw.githubusercontent.com/Mohanad234128/"
    "Project_MSC_Sample_Superstore/main/Data/Sample_Superstore.csv"
)

DDL = """
CREATE TABLE categories (category_id INTEGER PRIMARY KEY, category_name TEXT NOT NULL);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY, company_name TEXT NOT NULL,
    segment TEXT, country TEXT, city TEXT
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY, product_name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(category_id), unit_price REAL NOT NULL
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY, order_ref TEXT NOT NULL,
    customer_id INTEGER REFERENCES customers(customer_id), order_date TEXT NOT NULL,
    freight REAL NOT NULL DEFAULT 0
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL, unit_price REAL NOT NULL, discount REAL NOT NULL
);
CREATE INDEX idx_real_orders_date ON orders(order_date);
CREATE INDEX idx_real_items_order ON order_items(order_id);
"""


def download() -> Path:
    if CSV_PATH.exists():
        return CSV_PATH
    REAL_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SOURCE_URL, CSV_PATH)
    return CSV_PATH


def parse_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%m/%d/%Y").date().isoformat()


def build() -> Path:
    csv_path = download()
    if DB_PATH.exists():
        DB_PATH.unlink()

    customers: dict[str, int] = {}
    products: dict[str, int] = {}
    categories: dict[str, int] = {}
    orders: dict[str, int] = {}
    customer_rows: list[tuple] = []
    product_rows: list[tuple] = []
    category_rows: list[tuple] = []
    order_rows: list[tuple] = []
    item_rows: list[tuple] = []

    with csv_path.open(encoding="cp1252", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            cid = customers.setdefault(row["Customer ID"], len(customers) + 1)
            if len(customer_rows) < cid:
                customer_rows.append(None)
            customer_rows[cid - 1] = (
                cid, row["Customer Name"], row["Segment"], row["Country"], row["City"]
            )

            category = row["Category"]
            cat_id = categories.setdefault(category, len(categories) + 1)
            if len(category_rows) < cat_id:
                category_rows.append(None)
            category_rows[cat_id - 1] = (cat_id, category)

            pid = products.setdefault(row["Product ID"], len(products) + 1)
            quantity = int(row["Quantity"])
            discount = float(row["Discount"])
            sales = float(row["Sales"])
            denominator = quantity * (1 - discount)
            unit_price = round(sales / denominator, 6) if denominator else 0.0
            if len(product_rows) < pid:
                product_rows.append(None)
            product_rows[pid - 1] = (pid, row["Product Name"], cat_id, unit_price)

            order_ref = row["Order ID"]
            oid = orders.setdefault(order_ref, len(orders) + 1)
            if len(order_rows) < oid:
                order_rows.append(None)
            order_rows[oid - 1] = (
                oid, order_ref, cid, parse_date(row["Order Date"]), 0.0
            )
            item_rows.append((len(item_rows) + 1, oid, pid, quantity, unit_price, discount))

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    conn.executemany("INSERT INTO categories VALUES (?,?)", [r for r in category_rows if r])
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", [r for r in customer_rows if r])
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", [r for r in product_rows if r])
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", [r for r in order_rows if r])
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", item_rows)
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
              ("categories", "customers", "products", "orders", "order_items")}
    conn.close()
    print(f"Built {DB_PATH} — {counts}")
    return DB_PATH


if __name__ == "__main__":
    build()
