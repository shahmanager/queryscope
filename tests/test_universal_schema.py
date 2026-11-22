"""The universality proof: a schema with zero Northwind/Superstore names.

Every table, column and value below is different. The engine must discover
the fact tables, time column, label dimensions, filters and revenue measure
from SQLite alone.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from queryscope.engine import Engine

DDL = """
CREATE TABLE providers (provider_id INTEGER PRIMARY KEY, name TEXT, specialty TEXT);
CREATE TABLE patients (
    patient_id INTEGER PRIMARY KEY, full_name TEXT, sex TEXT, country TEXT, dob TEXT
);
CREATE TABLE admissions (
    admission_id INTEGER PRIMARY KEY,
    patient_id INTEGER REFERENCES patients(patient_id),
    admitted_on TEXT NOT NULL,
    department TEXT,
    charge_amount REAL
);
CREATE TABLE diagnoses (
    diagnosis_id INTEGER PRIMARY KEY,
    admission_id INTEGER REFERENCES admissions(admission_id),
    code TEXT, description TEXT, severity TEXT
);
CREATE TABLE treatments (
    treatment_id INTEGER PRIMARY KEY,
    admission_id INTEGER REFERENCES admissions(admission_id),
    provider_id INTEGER REFERENCES providers(provider_id),
    name TEXT, cost REAL, units INTEGER
);
"""


def build_hospital(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    countries = ["Canada", "Japan", "Brazil"]
    departments = ["Cardiology", "Oncology", "Neurology"]
    specialties = ["Cardiology", "Oncology", "Neurology"]
    patients = [(i, f"Patient {i}", "F" if i % 2 else "M", countries[i % 3],
                 f"19{50 + i % 40}-01-01") for i in range(1, 31)]
    providers = [(i, f"Dr {i}", specialties[i % 3]) for i in range(1, 6)]
    admissions = []
    diagnoses = []
    treatments = []
    aid = 1
    for patient in patients:
        for _ in range(2):
            month = 1 + (aid % 12)
            admissions.append((aid, patient[0], f"2026-{month:02d}-15",
                               departments[aid % 3], 500.0 + aid * 37.5))
            diagnoses.append((aid, aid, f"D{aid % 9}", f"Condition {aid % 9}",
                              "High" if aid % 3 == 0 else "Low"))
            treatments.append((aid, aid, 1 + aid % 5, f"Procedure {aid % 7}",
                               100.0 + aid, 1 + aid % 4))
            aid += 1
    conn.executemany("INSERT INTO providers VALUES (?,?,?)", providers)
    conn.executemany("INSERT INTO patients VALUES (?,?,?,?,?)", patients)
    conn.executemany("INSERT INTO admissions VALUES (?,?,?,?,?)", admissions)
    conn.executemany("INSERT INTO diagnoses VALUES (?,?,?,?,?)", diagnoses)
    conn.executemany("INSERT INTO treatments VALUES (?,?,?,?,?,?)", treatments)
    conn.commit()
    conn.close()


def test_profile_discovers_unknown_schema(tmp_path: Path) -> None:
    db = tmp_path / "hospital.sqlite"
    build_hospital(db)
    engine = Engine(db_path=db, now=datetime(2026, 12, 31))
    profile = engine.profile

    assert set(profile.fact_tables) == {"admissions", "treatments"}
    assert profile.time_column is not None
    assert profile.time_column.table == "admissions"
    assert profile.dimensions["patients"] == "full_name"
    assert profile.dimensions["admissions"] == "department"
    assert "charge" in profile.revenue_expr.lower()
    assert "admissions" in profile.revenue_expr
    assert "column:patients.country" in [
        c for v in profile.column_aliases.values() for c in v
    ]


def test_queries_against_unknown_schema(tmp_path: Path) -> None:
    db = tmp_path / "hospital.sqlite"
    build_hospital(db)
    engine = Engine(db_path=db, now=datetime(2026, 12, 31))
    conn = sqlite3.connect(db)

    cases = [
        ("how many patients are there", "SELECT COUNT(*) FROM patients"),
        ("how many admissions are there", "SELECT COUNT(*) FROM admissions"),
        ("total revenue", "SELECT SUM(charge_amount) FROM admissions"),
        (
            "revenue by department",
            "SELECT department, SUM(charge_amount) FROM admissions GROUP BY department",
        ),
        (
            "show patients in Canada",
            "SELECT full_name FROM patients WHERE country = 'Canada'",
        ),
    ]
    for question, gold_sql in cases:
        answer = engine.ask(question)
        expected = sorted(tuple(r) for r in conn.execute(gold_sql).fetchall())
        actual = sorted(tuple(r) for r in answer.rows)
        assert answer.status == "answered", (question, answer.diagnostics)
        assert actual == expected, (question, actual[:2], expected[:2])
    conn.close()
