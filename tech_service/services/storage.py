from __future__ import annotations

import json
import random
import shutil
import string
from pathlib import Path
from typing import Iterable, List, Optional
from uuid import uuid4

from .models import Ticket, LabelledIssue, iso_now, ALLOWED_STATUSES
from .extractor import extract_labels

DATA_DIR = Path("data")
TICKETS_DIR = DATA_DIR / "tickets"
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}

TICKETS_DIR.mkdir(parents=True, exist_ok=True)


def _allowed_file(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_EXTS


def new_ticket_id() -> str:
    return uuid4().hex


def new_claim_code(n: int = 7) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


def ticket_dir(ticket_id: str) -> Path:
    d = TICKETS_DIR / ticket_id
    (d / "attachments").mkdir(parents=True, exist_ok=True)
    return d


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
    if not (name or "").strip() or len((name or "").split()) < 2:
        raise ValueError("Full name (first and last) is required")
    if not (email or "").strip():
        raise ValueError("Email is required")

    tid = new_ticket_id()
    folder = ticket_dir(tid)
    claim = new_claim_code()

    labels = [LabelledIssue(n, float(s), src) for (n, s, src) in extract_labels(description or "")]
    status = "new"
    history = [{"at": iso_now(), "status": status, "note": "Ticket created", "by": actor}]

    t = Ticket(
        id=tid,
        claim_code=claim,
        name=name.strip(),
        email=email.strip(),
        phone=(phone or "").strip(),
        device_type=(device_type or "").strip(),
        brand=(brand or "").strip(),
        model=(model or "").strip(),
        serial=(serial or "").strip(),
        accessories=(accessories or "").strip(),
        description=(description or "").strip(),
        status=status,
        status_history=history,
        labels=labels,
        created_at=iso_now(),
        updated_at=iso_now(),
        _root=folder,
    )

    (folder / "meta.json").write_text(t.as_json(), encoding="utf-8")

    # Save attachments
    for f in files or []:
        if hasattr(f, "name") and hasattr(f, "read"):
            name = Path(getattr(f, "name")).name
            if not _allowed_file(Path(name)):
                continue
            dest = folder / "attachments" / name
            dest.write_bytes(f.read())
        else:
            p = Path(f) if not isinstance(f, bytes) else None
            if p is not None and _allowed_file(p):
                shutil.copy(p, folder / "attachments" / p.name)
    return tid


def load(ticket_id: str) -> Ticket:
    folder = ticket_dir(ticket_id)
    data = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    ticket = Ticket(
        id=data["id"],
        claim_code=data.get("claim_code", ""),
        name=data.get("name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        device_type=data.get("device_type", ""),
        brand=data.get("brand", ""),
        model=data.get("model", ""),
        serial=data.get("serial", ""),
        accessories=data.get("accessories", ""),
        description=data.get("description", ""),
        status=data.get("status", "new"),
        status_history=data.get("status_history", []),
        labels=[LabelledIssue(**d) for d in data.get("labels", [])],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        _root=folder,
    )
    return ticket


def list_all() -> List[Ticket]:
    out: List[Ticket] = []
    for folder in sorted(TICKETS_DIR.glob("*")):
        meta = folder / "meta.json"
        if meta.exists():
            try:
                t = load(folder.name)
                out.append(t)
            except Exception:
                continue
    out.sort(key=lambda t: (t.created_at or "", t.id), reverse=True)
    return out


def reclassify(ticket_id: str) -> Ticket:
    t = load(ticket_id)
    t.labels = [LabelledIssue(n, float(s), src) for (n, s, src) in extract_labels(t.description)]
    t.updated_at = iso_now()
    (t._root / "meta.json").write_text(t.as_json(), encoding="utf-8")
    return t


def update_status(ticket_id: str, status: str, *, note: str = "", actor: str = "technician") -> Ticket:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Allowed: {ALLOWED_STATUSES}")
    t = load(ticket_id)
    t.status = status
    t.updated_at = iso_now()
    t.status_history.append({"at": iso_now(), "status": status, "note": note, "by": actor})
    (t._root / "meta.json").write_text(t.as_json(), encoding="utf-8")
    return t


def find_by_claim(claim_code: str) -> Optional[Ticket]:
    claim_code = (claim_code or "").strip().upper()
    for folder in TICKETS_DIR.glob("*"):
        meta = folder / "meta.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data.get("claim_code", "").upper() == claim_code:
                return load(data["id"])  # ensures full object shape
        except Exception:
            continue
    return None