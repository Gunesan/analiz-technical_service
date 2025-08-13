# service_core/notify.py
from __future__ import annotations
import os, ssl, smtplib
from email.message import EmailMessage
from typing import Tuple, Optional

def _get(key: str, default: str = "") -> str:
    # Prefer env var; fall back to Streamlit secrets if available
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st  # optional at runtime
        return st.secrets.get(key, default)
    except Exception:
        return default

def _smtp_config() -> dict:
    return {
        "HOST": _get("SMTP_HOST", ""),
        "PORT": int(_get("SMTP_PORT", "465")),  # 465 SSL, or 587 for STARTTLS
        "USER": _get("SMTP_USER", ""),
        "PASS": _get("SMTP_PASS", ""),
        "FROM": _get("SMTP_FROM", _get("SMTP_USER", "")),
        "USE_STARTTLS": _get("SMTP_STARTTLS", "0") in {"1", "true", "True"},
    }

def send_status_email(
    to_email: str,
    *,
    ticket,                 # service_core.models.Ticket
    old_status: str,
    new_status: str,
    note: str = "",
    base_url: Optional[str] = None,  # e.g., "https://yourcompany.com"
) -> Tuple[bool, str]:
    cfg = _smtp_config()
    # If not configured, silently skip
    if not (cfg["HOST"] and cfg["USER"] and cfg["PASS"] and cfg["FROM"] and to_email):
        return False, "Email not configured"

    subject = f"[Tech Service] Status updated: {new_status}"
    link_hint = ""
    if base_url:
        link_hint = f"\nCheck status: {base_url} (use claim code {ticket.claim_code})"

    body = f"""Hello {ticket.name},

Your device ticket ({ticket.id}, claim code {ticket.claim_code}) has a new status.

Previous: {old_status}
Current : {new_status}
{"Note: " + note if note else ""}

Device: {ticket.device_type} — {ticket.brand} {ticket.model}
Submitted: {ticket.created_at}
{link_hint}

If you have questions, reply to this email.

— Technical Service
"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["FROM"]
    msg["To"] = to_email
    msg.set_content(body)

    try:
        if cfg["USE_STARTTLS"]:
            with smtplib.SMTP(cfg["HOST"], cfg["PORT"]) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                s.login(cfg["USER"], cfg["PASS"])
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["HOST"], cfg["PORT"], context=ssl.create_default_context()) as s:
                s.login(cfg["USER"], cfg["PASS"])
                s.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, f"send failed: {e}"
