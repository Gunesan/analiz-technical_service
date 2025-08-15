# service_core/notify.py
from __future__ import annotations

import os
import re
import ssl
import smtplib
import socket
import time
from email.message import EmailMessage
from typing import Tuple, Optional


# ---------- helpers ----------

def _get(key: str, default: str = "") -> str:
    """
    Prefer environment variables; fall back to Streamlit secrets (if available).
    Returns default if not found.
    """
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st  # optional dependency
        v = st.secrets.get(key, default)
        return v if isinstance(v, str) else str(v)
    except Exception:
        return default


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _smtp_config() -> dict:
    """
    Build SMTP configuration from env/Streamlit secrets.
    Defaults favor Gmail STARTTLS on port 587 but you can override.
    """
    host = _get("SMTP_HOST", "smtp.gmail.com")
    port = int(_get("SMTP_PORT", "587"))  # 587 STARTTLS (Gmail default)
    user = _get("SMTP_USER", "")
    pwd = _get("SMTP_PASS", "")
    from_addr = _get("SMTP_FROM", f"Tech Service <{user}>" if user else "")
    # If not explicitly set, default STARTTLS=True when port==587, else False
    use_starttls = _to_bool(_get("SMTP_STARTTLS", ""), default=(port == 587))
    timeout = int(_get("SMTP_TIMEOUT_SECONDS", "20"))
    disabled = _to_bool(_get("SMTP_DISABLED", "0"), default=False)

    # Validate the non-sensitive bits; we won't hardcode any secrets
    missing = []
    if not host: missing.append("SMTP_HOST")
    if not port: missing.append("SMTP_PORT")
    if not user: missing.append("SMTP_USER")
    if not pwd:  missing.append("SMTP_PASS")
    if not from_addr: missing.append("SMTP_FROM")

    error = None
    if missing and not disabled:
        error = f"Email not configured. Missing: {', '.join(missing)}"

    return {
        "HOST": host,
        "PORT": port,
        "USER": user,
        "PASS": pwd,
        "FROM": from_addr,
        "USE_STARTTLS": use_starttls,
        "TIMEOUT": timeout,
        "DISABLED": disabled,
        "ERROR": error,
    }


def _build_body(
    *,
    ticket,
    old_status: str,
    new_status: str,
    note: str,
    base_url: Optional[str],
) -> Tuple[str, str]:
    subject = f"[Tech Service] Status updated: {new_status}"
    link_hint = ""
    if base_url:
        link_hint = f"\nCheck status: {base_url} (use claim code {getattr(ticket, 'claim_code', '')})"

    body = f"""Dear {ticket.name},

Your device ticket ({ticket.id}, claim code {ticket.claim_code}) has a new status.

Previous: {old_status}
Current : {new_status}
{('Note: ' + note) if note else ''}

Device: {ticket.device_type} — {ticket.brand} {ticket.model}
Submitted: {ticket.created_at}
{link_hint}

If you have questions, reply to this email.

— Technical Service
"""
    return subject, body


# ---------- public API ----------

def send_status_email(
    to_email: str,
    *,
    ticket,                 # service_core.models.Ticket
    old_status: str,
    new_status: str,
    note: str = "",
    base_url: Optional[str] = None,  # e.g., "https://yourcompany.com"
) -> Tuple[bool, str]:
    """
    Sends a plain-text status change email.
    Returns (ok: bool, message: str).
    """
    cfg = _smtp_config()

    if cfg["DISABLED"]:
        # Preview mode only — don't send
        subject, body = _build_body(ticket=ticket, old_status=old_status, new_status=new_status, note=note, base_url=base_url)
        print("=== SMTP_DISABLED=1; email preview ===")
        print("From:", cfg["FROM"])
        print("To:", to_email)
        print("Subject:", subject)
        print(body)
        print("=== END PREVIEW ===")
        return True, "preview (SMTP_DISABLED=1)"

    if cfg["ERROR"]:
        return False, cfg["ERROR"]

    if not to_email or not EMAIL_RE.match(to_email):
        return False, f"Invalid recipient email: {to_email!r}"

    subject, body = _build_body(ticket=ticket, old_status=old_status, new_status=new_status, note=note, base_url=base_url)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["FROM"]
    msg["To"] = to_email
    # Optional: set Reply-To to your user to simplify replies
    if cfg["USER"] and "@" in cfg["USER"]:
        msg["Reply-To"] = cfg["USER"]
    msg.set_content(body)

    attempts = 3
    last_exc = None

    for i in range(1, attempts + 1):
        try:
            if cfg["USE_STARTTLS"]:
                with smtplib.SMTP(cfg["HOST"], cfg["PORT"], timeout=cfg["TIMEOUT"]) as s:
                    s.ehlo()
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                    s.login(cfg["USER"], cfg["PASS"])
                    s.send_message(msg)
            else:
                # SSL path (e.g., port 465)
                with smtplib.SMTP_SSL(cfg["HOST"], cfg["PORT"], context=ssl.create_default_context(), timeout=cfg["TIMEOUT"]) as s:
                    s.login(cfg["USER"], cfg["PASS"])
                    s.send_message(msg)

            return True, "sent"

        except (smtplib.SMTPException, socket.timeout, OSError) as e:
            last_exc = e
            if i < attempts:
                time.sleep(1.5 * i)  # simple backoff
            else:
                break

    return False, f"send failed: {last_exc!r}"
