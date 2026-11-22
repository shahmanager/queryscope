-- QueryScope demo warehouse. A small, join-rich wholesale schema.

CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    company_name  TEXT NOT NULL,
    contact_name  TEXT,
    city          TEXT,
    country       TEXT,
    segment       TEXT
);

CREATE TABLE categories (
    category_id   INTEGER PRIMARY KEY,
    category_name TEXT NOT NULL
);

CREATE TABLE suppliers (
    supplier_id   INTEGER PRIMARY KEY,
    company_name  TEXT NOT NULL,
    country       TEXT
);

CREATE TABLE stores (
    store_id      INTEGER PRIMARY KEY,
    store_name    TEXT NOT NULL,
    city          TEXT,
    country       TEXT
);

CREATE TABLE employees (
    employee_id   INTEGER PRIMARY KEY,
    full_name     TEXT NOT NULL,
    country       TEXT,
    hire_date     TEXT,
    salary        REAL
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category_id   INTEGER REFERENCES categories(category_id),
    supplier_id   INTEGER REFERENCES suppliers(supplier_id),
    unit_price    REAL NOT NULL,
    units_in_stock INTEGER NOT NULL,
    discontinued  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER REFERENCES customers(customer_id),
    employee_id   INTEGER REFERENCES employees(employee_id),
    store_id      INTEGER REFERENCES stores(store_id),
    order_date    TEXT NOT NULL,
    shipped_date  TEXT,
    freight       REAL NOT NULL,
    status        TEXT NOT NULL
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    discount      REAL NOT NULL DEFAULT 0
);

CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
