"""Persistent local store. Input workbooks are never modified."""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager


def state_dir():
    path = Path(os.getenv("STATE_DIR", ".local-state"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    db = sqlite3.connect(state_dir() / "portfolio.sqlite", timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS people (id TEXT PRIMARY KEY, name TEXT NOT NULL, pan TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS schemes (id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, official_name TEXT, isin TEXT, mapping_status TEXT DEFAULT 'unmapped', candidates TEXT DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, person TEXT NOT NULL, scheme TEXT NOT NULL, date TEXT NOT NULL, type TEXT NOT NULL, units REAL NOT NULL, nav REAL, amount REAL NOT NULL, source TEXT NOT NULL, row_number INTEGER, occurrence INTEGER DEFAULT 1);
        CREATE INDEX IF NOT EXISTS tx_date ON transactions(date);
        CREATE TABLE IF NOT EXISTS sources (path TEXT PRIMARY KEY, hash TEXT, records INTEGER, imported_at TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS prices (kind TEXT NOT NULL, instrument TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL CHECK(value>0), source TEXT NOT NULL, fetched_at TEXT, PRIMARY KEY(kind,instrument,date));
        CREATE TABLE IF NOT EXISTS windows (kind TEXT, instrument TEXT, start TEXT, end TEXT, fetched_at TEXT, PRIMARY KEY(kind,instrument,start,end));
        CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, date TEXT NOT NULL, scheme TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL, units REAL NOT NULL, nav REAL, lots TEXT DEFAULT '[]', note TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, category TEXT, message TEXT, source TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS exclusions (transaction_id TEXT PRIMARY KEY, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS review_resolutions (group_id TEXT PRIMARY KEY, kept_ids TEXT NOT NULL, resolved_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transfer_links (transaction_id TEXT PRIMARY KEY, transfer_id TEXT NOT NULL REFERENCES transfers(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS reconciliation_events (id TEXT PRIMARY KEY, person TEXT NOT NULL, date TEXT NOT NULL, fund_name TEXT NOT NULL, units REAL NOT NULL, nav REAL NOT NULL, amount REAL NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL, row_number INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS consolidations (id TEXT PRIMARY KEY, person TEXT NOT NULL, scheme TEXT NOT NULL, date TEXT NOT NULL, original_id TEXT NOT NULL UNIQUE, purchase_id TEXT NOT NULL UNIQUE, redemption_id TEXT NOT NULL UNIQUE, units REAL NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS unit_precision (transaction_id TEXT PRIMARY KEY, units REAL NOT NULL, source TEXT NOT NULL, row_number INTEGER NOT NULL);
        ''')


def rows(sql, args=()):
    with connect() as db:
        return [dict(x) for x in db.execute(sql, args)]


def setting(key, default=None):
    result = rows("SELECT value FROM settings WHERE key=?", (key,))
    return result[0]["value"] if result else default


def set_setting(key, value):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
