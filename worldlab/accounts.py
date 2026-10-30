"""User accounts, sessions and run history in SQLite (standard library only).

Passwords are hashed with scrypt and a per-user salt. Session tokens are
random, sent to the browser in an HttpOnly cookie, and stored only as SHA-256
digests, so a copy of the database does not let anyone log in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SESSION_DAYS = 14
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


class AuthError(ValueError):
    pass


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Accounts:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                salt BLOB NOT NULL, pw BLOB NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                created REAL NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS progress (
                user_id INTEGER PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                run_dir TEXT NOT NULL, agent TEXT NOT NULL, choices TEXT, created REAL NOT NULL,
                result TEXT);
        """)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(runs)")}
        if "award" not in cols:
            self.db.execute("ALTER TABLE runs ADD COLUMN award TEXT")
            self.db.commit()
        self._fails: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ users
    def signup(self, email: str, password: str, name: str) -> dict:
        email = (email or "").strip().lower()
        name = (name or "").strip()
        if not EMAIL_RE.match(email) or len(email) > 200:
            raise AuthError("Enter a valid email address.")
        if not name or len(name) > 80:
            raise AuthError("Enter your name (up to 80 characters).")
        if len(password or "") < 8:
            raise AuthError("Use a password of at least 8 characters.")
        if len(password) > 200:
            raise AuthError("That password is too long.")
        salt = secrets.token_bytes(16)
        with self._lock:
            try:
                cur = self.db.execute("INSERT INTO users (email, name, salt, pw, created) VALUES (?,?,?,?,?)",
                                      (email, name, salt, _hash_password(password, salt), time.time()))
                self.db.commit()
            except sqlite3.IntegrityError:
                raise AuthError("An account with that email already exists. Log in instead.")
        return {"id": cur.lastrowid, "email": email, "name": name}

    def login(self, email: str, password: str, client: str = "") -> dict:
        email = (email or "").strip().lower()
        key = f"{client}|{email}"
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < 600]
        if len(recent) >= 8:
            raise AuthError("Too many attempts. Wait ten minutes and try again.")
        row = self.db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        ok = bool(row) and hmac.compare_digest(_hash_password(password or "", row["salt"]), row["pw"])
        if not row:
            _hash_password(password or "", b"0" * 16)          # same work either way
        if not ok:
            self._fails[key] = recent + [now]
            raise AuthError("That email and password don't match an account.")
        self._fails.pop(key, None)
        return {"id": row["id"], "email": row["email"], "name": row["name"]}

    # --------------------------------------------------------------- sessions
    def new_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self.db.execute("INSERT INTO sessions (token, user_id, created, expires) VALUES (?,?,?,?)",
                            (_digest(token), user_id, now, now + SESSION_DAYS * 86400))
            self.db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
            self.db.commit()
        return token

    def user_for(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.execute(
            "SELECT u.id, u.email, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token=? AND s.expires > ?", (_digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def end_session(self, token: str | None):
        if token:
            with self._lock:
                self.db.execute("DELETE FROM sessions WHERE token=?", (_digest(token),))
                self.db.commit()

    # ------------------------------------------------------------------- runs
    def add_run(self, user_id: int, run_dir: str, agent: str, choices) -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO runs (user_id, run_dir, agent, choices, created) VALUES (?,?,?,?,?)",
                                  (user_id, run_dir, agent, json.dumps(choices), time.time()))
            self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, result: dict | None, award: dict | None = None):
        with self._lock:
            self.db.execute("UPDATE runs SET result=?, award=? WHERE id=?",
                            (json.dumps(result) if result else None, json.dumps(award) if award else None, run_id))
            self.db.commit()

    # --------------------------------------------------------------- progress
    def progress(self, user_id: int) -> dict:
        r = self.db.execute("SELECT data FROM progress WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(r[0]) if r else {}

    def save_progress(self, user_id: int, data: dict):
        with self._lock:
            self.db.execute("INSERT INTO progress (user_id, data) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                            (user_id, json.dumps(data)))
            self.db.commit()

    def runs(self, user_id: int, limit: int = 30) -> list[dict]:
        rows = self.db.execute("SELECT * FROM runs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
        return [{"id": r["id"], "agent": r["agent"], "created": r["created"],
                 "choices": json.loads(r["choices"] or "null"), "result": json.loads(r["result"] or "null"),
                 "award": json.loads(r["award"] or "null")} for r in rows]

    def run(self, user_id: int, run_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM runs WHERE user_id=? AND id=?", (user_id, run_id)).fetchone()
        return dict(r) if r else None
