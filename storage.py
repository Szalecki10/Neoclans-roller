"""
Przechowywanie konfiguracji (tabeli genów) jako wersjonowanego dokumentu JSON.

Każdy zapis admina to nowy wiersz w `config_versions`; aktualna konfiguracja to
najnowszy wiersz. Dzięki temu da się wrócić do wcześniejszej wersji z panelu.

- DATABASE_URL ustawione  -> Postgres (np. darmowy Neon)
- brak DATABASE_URL       -> lokalny plik SQLite (do testów na własnym komputerze)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

KEEP_VERSIONS = 200


class SqliteStore:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS config_versions (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       created_at TEXT NOT NULL,
                       note TEXT NOT NULL DEFAULT '',
                       data TEXT NOT NULL
                   )"""
            )
            conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def secret(self, key):
        """Losowa wartość zapisana w bazie przy pierwszym użyciu (np. klucz sesji)."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO app_meta (key, value) VALUES (?, ?)", (key, secrets.token_hex(32))
            )
            return conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()[0]

    def latest(self):
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, created_at, note, data FROM config_versions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return None if row is None else _row(row[0], row[1], row[2], json.loads(row[3]))

    def save(self, data, note=""):
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO config_versions (created_at, note, data) VALUES (?, ?, ?)",
                (created_at, note, json.dumps(data, ensure_ascii=False)),
            )
            conn.execute(
                "DELETE FROM config_versions WHERE id NOT IN "
                "(SELECT id FROM config_versions ORDER BY id DESC LIMIT ?)",
                (KEEP_VERSIONS,),
            )
            return cur.lastrowid

    def versions(self, limit=50):
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, created_at, note FROM config_versions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row(*r) for r in rows]

    def version(self, version_id):
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, created_at, note, data FROM config_versions WHERE id = ?", (version_id,)
            ).fetchone()
        return None if row is None else _row(row[0], row[1], row[2], json.loads(row[3]))


class PostgresStore:
    def __init__(self, url):
        import psycopg
        from psycopg.types.json import Jsonb

        self._psycopg = psycopg
        self._jsonb = Jsonb
        self.url = url
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS config_versions (
                       id BIGSERIAL PRIMARY KEY,
                       created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                       note TEXT NOT NULL DEFAULT '',
                       data JSONB NOT NULL
                   )"""
            )
            conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _connect(self):
        # Darmowy Neon usypia bazę po 5 min bez ruchu; pierwsze połączenie ją budzi.
        return self._psycopg.connect(self.url, autocommit=True, connect_timeout=20)

    def secret(self, key):
        """Losowa wartość zapisana w bazie przy pierwszym użyciu (np. klucz sesji)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                (key, secrets.token_hex(32)),
            )
            return conn.execute("SELECT value FROM app_meta WHERE key = %s", (key,)).fetchone()[0]

    def latest(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, note, data FROM config_versions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return None if row is None else _row(*row)

    def save(self, data, note=""):
        with self._connect() as conn:
            version_id = conn.execute(
                "INSERT INTO config_versions (note, data) VALUES (%s, %s) RETURNING id",
                (note, self._jsonb(data)),
            ).fetchone()[0]
            conn.execute(
                "DELETE FROM config_versions WHERE id NOT IN "
                "(SELECT id FROM config_versions ORDER BY id DESC LIMIT %s)",
                (KEEP_VERSIONS,),
            )
        return version_id

    def versions(self, limit=50):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, note FROM config_versions ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [_row(*r) for r in rows]

    def version(self, version_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, note, data FROM config_versions WHERE id = %s", (version_id,)
            ).fetchone()
        return None if row is None else _row(*row)


def _row(version_id, created_at, note, data=None):
    if isinstance(created_at, datetime):
        created_at = created_at.astimezone(timezone.utc).isoformat(timespec="seconds")
    row = {"id": version_id, "createdAt": created_at, "note": note}
    if data is not None:
        row["data"] = data
    return row


def open_store(base_dir):
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw:
        # Wyciągamy sam adres, nawet jeśli wklejono „DATABASE_URL=…”, „psql '…'” albo adres w cudzysłowach.
        # Wartości nie wypisujemy: to connection string z hasłem do bazy.
        match = re.search(r"postgres(?:ql)?://[^\s'\"]+", raw)
        if not match:
            raise RuntimeError(
                "DATABASE_URL musi zawierać connection string z Neona zaczynający się od postgresql:// "
                "(Neon → projekt → Connect), a nie adres strony ani hasło."
            )
        return PostgresStore(match.group(0))
    return SqliteStore(os.environ.get("SQLITE_PATH") or os.path.join(base_dir, "data", "neoclans.db"))
