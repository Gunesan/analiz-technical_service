from __future__ import annotations

from typing import List, Optional

from .models import Ticket
from .storage_sqlite import save_ticket, load, list_all, reclassify, update_status, find_by_claim


def create_ticket(**kwargs) -> str:
    return save_ticket(**kwargs)


def load_ticket(ticket_id: str) -> Ticket:
    return load(ticket_id)


def list_tickets() -> List[Ticket]:
    return list_all()


def reclassify_ticket(ticket_id: str) -> Ticket:
    return reclassify(ticket_id)


def update_ticket_status(ticket_id: str, status: str, *, note: str = "", actor: str = "technician") -> Ticket:
    return update_status(ticket_id, status, note=note, actor=actor)


def find_ticket_by_claim(claim_code: str) -> Optional[Ticket]:
    return find_by_claim(claim_code)
