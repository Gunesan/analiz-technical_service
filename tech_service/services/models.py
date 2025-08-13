from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import json

ISO = "%Y-%m-%dT%H:%M:%SZ"

ALLOWED_STATUSES = [
    "new",            # submitted by front desk
    "received",       # device physically received
    "diagnosing",     # under diagnosis
    "repairing",      # in repair / parts ordered
    "ready for pickup",
    "completed",      # picked up/closed
]


def iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).strftime(ISO)


@dataclass
class LabelledIssue:
    name: str
    score: float
    source: str = "rules"

    def to_dict(self) -> Dict:
        return {"name": self.name, "score": float(self.score), "source": self.source}


@dataclass
class Ticket:
    # Customer & device
    id: str
    claim_code: str  # short code to give customer (e.g., 7-char alnum)
    name: str        # full name (required)
    email: str       # required
    phone: str       # optional
    device_type: str # e.g., Laptop, Phone, Tablet, Other
    brand: str
    model: str
    serial: str
    accessories: str # e.g., charger, case, etc.

    # Problem & status
    description: str
    status: str
    status_history: List[Dict[str, str]]  # [{"at": ISO, "status": str, "note": str, "by": str}]
    labels: List[LabelledIssue]

    # Timestamps
    created_at: str
    updated_at: str

    # runtime-only: derived paths (set by storage layer)
    _root: Optional[Path] = None

    def as_json(self) -> str:
        payload = {
            **{k: v for k, v in asdict(self).items() if not k.startswith("_")},
            "labels": [lbl.to_dict() for lbl in self.labels],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
