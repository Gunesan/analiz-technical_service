# services/storage_sqlite.py
from __future__ import annotations

import os
import json
import sqlite3
import random
import string
from pathlib import Path
from typing import Iterable, List, Optional
from uuid import uuid4

from .models import Ticket, LabelledIssue, iso_now, ALLOWED_STATUSES
from .extractor import extract_labels

# DB file (local). Note: on Streamlit Cloud this file is wiped on redeploys.
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / os.getenv("SQLITE_FILE", "app.db")
ATT_DIR_ROOT = DATA_DIR / "tickets"  # keep attachments compatible with existing UI
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}


def _allowed_file(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXTS


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATT_DIR_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            claim_code TEXT UNIQUE,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            device_type TEXT NOT NULL,
            brand TEXT,
            model TEXT,
            serial TEXT,
            accessories TEXT,
            description TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            at TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            by_actor TEXT
        );

        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            score REAL NOT NULL,
            source TEXT DEFAULT 'rules'
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            mime TEXT
        );
        """
    )
    conn.commit()


def new_ticket_id() -> str:
    return uuid4().hex


def new_claim_code(length: int = 7) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def ticket_dir(tid: str) -> Path:
    d = ATT_DIR_ROOT / tid
    (d / "attachments").mkdir(parents=True, exist_ok=True)
    return d


def _row_to_ticket(conn: sqlite3.Connection, row: sqlite3.Row) -> Ticket:
    cur = conn.cursor()
    # Labels
    cur.execute("SELECT name, score, source FROM labels WHERE ticket_id = ? ORDER BY score DESC", (row["id"],))
    lbls = [LabelledIssue(name=r["name"], score=float(r["score"]), source=r["source"]) for r in cur.fetchall()]
    # History
    cur.execute("SELECT at, status, note, by_actor FROM status_history WHERE ticket_id = ? ORDER BY id ASC", (row["id"],))
    hist = [{"at": r["at"], "status": r["status"], "note": r["note"] or "", "by": r["by_actor"] or ""} for r in cur.fetchall()]
    return Ticket(
        id=row["id"],
        claim_code=row["claim_code"],
        name=row["name"],
        email=row["email"],
        phone=row["phone"] or "",
        device_type=row["device_type"],
        brand=row["brand"] or "",
        model=row["model"] or "",
        serial=row["serial"] or "",
        accessories=row["accessories"] or "",
        description=row["description"] or "",
        status=row["status"],
        status_history=hist,
        labels=lbls,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        _root=ticket_dir(row["id"]),
    )


def save_ticket(
    *,
    name: str,
    email: str,
    phone: str,
    device_type: str,
    brand: str,
    model: str,
    serial: str,
    accessories: str,
    description: str,
    files: Iterable[Path | bytes | "UploadedFile"],
    actor: str = "front desk",
) -> str:
    conn = _connect()
    cur = conn.cursor()

    tid = new_ticket_id()
    claim = new_claim_code()
    created = iso_now()
    status = "new"

    cur.execute(
        """
        INSERT INTO tickets (id, claim_code, name, email, phone, device_type, brand, model, serial, accessories, description, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tid, claim, name, email, phone, device_type, brand, model, serial, accessories, description, status, created, created),
    )
    cur.execute(
        "INSERT INTO status_history (ticket_id, at, status, note, by_actor) VALUES (?, ?, ?, ?, ?)",
        (tid, created, status, "", actor),
    )

    labels = extract_labels(description or "")
    for lbl in labels:
        cur.execute(
            "INSERT INTO labels (ticket_id, name, score, source) VALUES (?, ?, ?, ?)",
            (tid, lbl.name, float(lbl.score), lbl.source),
        )

    conn.commit()

    # Save attachments to disk and index them
    att_root = ticket_dir(tid) / "attachments"
    for f in files or []:
        try:
            if hasattr(f, "name") and hasattr(f, "getbuffer"):  # Streamlit UploadedFile
                name = Path(f.name).name
                p = att_root / name
                p.write_bytes(f.getbuffer())
                mime = getattr(f, "type", None) or ""
            elif isinstance(f, (bytes, bytearray)):
                name = f"upload_{uuid4().hex}.bin"
                p = att_root / name
                p.write_bytes(bytes(f))
                mime = ""
            else:
                src = Path(f)
                if not _allowed_file(src):
                    continue
                p = att_root / src.name
                p.write_bytes(src.read_bytes())
                mime = ""
            cur.execute("INSERT INTO attachments (ticket_id, filename, path, mime) VALUES (?, ?, ?, ?)", (tid, name, str(p), mime))
        except Exception:
            continue

    conn.commit()
    conn.close()
    return tid


def load(ticket_id: str) -> Ticket:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise FileNotFoundError(f"Ticket {ticket_id} not found")
    t = _row_to_ticket(conn, row)
    conn.close()
    return t


def list_all() -> List[Ticket]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets ORDER BY created_at DESC")
    rows = cur.fetchall()
    out = [_row_to_ticket(conn, r) for r in rows]
    conn.close()
    return out


def reclassify(ticket_id: str) -> Ticket:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT description FROM tickets WHERE id = ?", (ticket_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise FileNotFoundError(f"Ticket {ticket_id} not found")
    desc = row["description"] or ""
    labels = extract_labels(desc)
    cur.execute("DELETE FROM labels WHERE ticket_id = ?", (ticket_id,))
    for lbl in labels:
        cur.execute(
            "INSERT INTO labels (ticket_id, name, score, source) VALUES (?, ?, ?, ?)",
            (ticket_id, lbl.name, float(lbl.score), lbl.source),
        )
    conn.commit()
    cur.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    t = _row_to_ticket(conn, cur.fetchone())
    conn.close()
    return t


def update_status(ticket_id: str, status: str, *, note: str = "", actor: str = "technician") -> Ticket:
    status = (status or "").strip()
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    conn = _connect()
    cur = conn.cursor()
    now = iso_now()
    cur.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?", (status, now, ticket_id))
    cur.execute(
        "INSERT INTO status_history (ticket_id, at, status, note, by_actor) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, now, status, note or "", actor),
    )
    conn.commit()
    cur.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    t = _row_to_ticket(conn, cur.fetchone())
    conn.close()
    return t


def find_by_claim(claim_code: str) -> Optional[Ticket]:
    conn = _connect()
    cur = conn.cursor()
    code = (claim_code or "").strip().upper()
    cur.execute("SELECT * FROM tickets WHERE UPPER(claim_code) = ?", (code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    t = _row_to_ticket(conn, row)
    conn.close()
    return t
