from __future__ import annotations

import re
import pandas as pd
import streamlit as st
from PIL import Image
from pathlib import Path
import os

from services import (
    create_ticket,
    list_tickets,
    load_ticket,
    reclassify_ticket,
    update_ticket_status,
    find_ticket_by_claim,
    ALLOWED_STATUSES,
)

#TECHNICIAN_PASSWORD = "ANALIZ(2025"

st.set_page_config(page_title="Tech Service", page_icon="🛠️", layout="wide")

# ---- technician auth ----
if "tech_authed" not in st.session_state:
    st.session_state.tech_authed = False

# Hardcoded fallback (works even if no env/secrets configured)
  # <-- set it here

# If you still want to allow overrides via env/secrets, keep these lines:
import os
try:
    TECH_PASSWORD = os.getenv("TECHNICIAN_PASSWORD", TECH_PASSWORD)
    TECH_PASSWORD = st.secrets.get("TECHNICIAN_PASSWORD", TECH_PASSWORD)
except Exception:
    pass

if not TECH_PASSWORD:
    st.sidebar.warning("TECH password not set. Set env var TECHNICIAN_PASSWORD or add it to .streamlit/secrets.toml")

st.sidebar.title("🛠️ Technical Service")

view = st.sidebar.radio("Go to", ["Front Desk Intake", "Technician", "Customer Status"], index=0)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_full_name(name: str) -> bool:
    name = (name or "").strip()
    return len(name.split()) >= 2


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))

# ----------------------------- Front Desk Intake -----------------------------

if view == "Front Desk Intake":
    st.title("Front desk — intake form")
    st.caption("Collect customer + device info, generate claim code, and hand device to technicians.")

    with st.form("intake", clear_on_submit=True):
        st.subheader("Customer")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            name = st.text_input("Full name *", placeholder="First Last")
        with c2:
            email = st.text_input("Email *", placeholder="you@example.com")
        with c3:
            phone = st.text_input("Phone (optional)")

        st.subheader("Device")
        d1, d2, d3, d4 = st.columns([1, 1, 1, 1])
        with d1:
            device_type = st.selectbox("Type", ["Laptop", "Phone", "Tablet", "Desktop", "Other"], index=0)
        with d2:
            brand = st.text_input("Brand", placeholder="e.g., Apple")
        with d3:
            model = st.text_input("Model", placeholder="e.g., MacBook Pro 13")
        with d4:
            serial = st.text_input("Serial/IMEI", placeholder="optional")
        accessories = st.text_input("Accessories", placeholder="e.g., charger, case")

        st.subheader("Problem")
        description = st.text_area("Describe the problem", height=160)
        files = st.file_uploader(
            "Attach photos (PNG/JPG/GIF/WEBP/PDF)",
            type=["png", "jpg", "jpeg", "gif", "webp", "pdf"],
            accept_multiple_files=True,
        )

        submitted = st.form_submit_button("Create ticket")

    if submitted:
        errs = []
        if not is_valid_full_name(name):
            errs.append("Please enter full name (first and last).")
        if not is_valid_email(email):
            errs.append("Please enter a valid email.")
        if not (description or "").strip():
            errs.append("Problem description is required.")
        if errs:
            for e in errs:
                st.error(e)
        else:
            tid = create_ticket(
                name=name,
                email=email,
                phone=phone,
                device_type=device_type,
                brand=brand,
                model=model,
                serial=serial,
                accessories=accessories,
                description=description,
                files=files,
                actor="front desk",
            )
            t = load_ticket(tid)
            st.success("Ticket created!")
            st.info(f"Ticket ID: {t.id}")
            st.warning(f"Claim Code for customer: {t.claim_code}")
            st.caption("Give the customer this claim code (and optionally email it). They can check their status with it.")


# ----------------------------- Technician -----------------------------

elif view == "Technician":
        # --- Technicians-only: require password ---
    if not st.session_state.tech_authed:
        st.subheader("Technician login")
        st.caption("Enter the technician password to access the repair queue.")
        pwd = st.text_input("Password", type="password", key="tech_pwd")
        if st.button("Sign in", key="tech_signin"):
            if TECH_PASSWORD and pwd == TECH_PASSWORD:
                st.session_state.tech_authed = True
                st.success("Signed in.")
                st.rerun()
            else:
                st.error("Invalid password. Ask your admin to set TECHNICIAN_PASSWORD.")
        st.stop()

    st.title("Technician — repair queue")

    tickets = list_tickets()

    q = st.text_input("Search (name, email, brand, model, description)")
    rows = []
    for t in tickets:
        text = " ".join([t.name, t.email, t.brand, t.model, t.description])
        if q and q.lower() not in text.lower():
            continue
        rows.append(
            {
                "id": t.id,
                "claim": t.claim_code,
                "created": t.created_at,
                "status": t.status,
                "device": f"{t.device_type} — {t.brand} {t.model}",
                "customer": t.name,
                "labels": ", ".join(l.name for l in t.labels),
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if rows:
        sel = st.selectbox("Select a ticket", [r["id"] for r in rows])
        t = next(tt for tt in tickets if tt.id == sel)

        st.subheader(f"Ticket {t.id} — {t.device_type} {t.brand} {t.model}")
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(f"**Customer:** {t.name} — {t.email}")
            st.markdown(f"**Claim code:** {t.claim_code}")
            st.markdown(f"**Current status:** {t.status}")
            st.markdown("**Problem description**")
            st.write(t.description)
            st.markdown("**Status history**")
            for h in t.status_history:
                st.write(f"{h['at']} — {h['status']} ({h.get('by','')}) — {h.get('note','')}")
        with c2:
            st.markdown("**Update status**")
            new_status = st.selectbox(
                "Set status",
                ALLOWED_STATUSES,
                index=ALLOWED_STATUSES.index(t.status) if t.status in ALLOWED_STATUSES else 0,
            )
            note = st.text_input("Note (optional)", placeholder="e.g., waiting for part")
            if st.button("Save status"):
                update_ticket_status(t.id, new_status, note=note, actor="technician")
                st.success("Status updated.")
                st.rerun()

        # Attachments
        att_dir = Path("data") / "tickets" / t.id / "attachments"
        if att_dir.exists():
            st.markdown("**Attachments**")
            cols = st.columns(3)
            for i, p in enumerate(sorted(att_dir.glob("*"))):
                col = cols[i % 3]
                if p.suffix.lower() == ".pdf":
                    col.caption(f"PDF: {p.name}")
                    col.download_button("Download", data=p.read_bytes(), file_name=p.name, mime="application/pdf")
                else:
                    try:
                        img = Image.open(p)
                        col.image(img, caption=p.name, use_column_width=True)
                        col.download_button("Download", data=p.read_bytes(), file_name=p.name)
                    except Exception:
                        col.write(p.name)

# ----------------------------- Customer Status -----------------------------
elif view == "Customer Status":
    st.title("Check your repair status")
    st.caption("Use the claim code given to you at intake.")

    with st.form("lookup"):
        claim = st.text_input("Claim code", placeholder="e.g., 7H2K9QW").upper()
        email = st.text_input("Email used at intake")
        submitted = st.form_submit_button("Look up")

    if submitted:
        if not claim or not is_valid_email(email):
            st.error("Please enter a valid claim code and email.")
        else:
            t = find_ticket_by_claim(claim)
            if not t or t.email.strip().lower() != email.strip().lower():
                st.error("We couldn't find a ticket with that claim code and email.")
            else:
                st.subheader(f"Status for claim {t.claim_code}")
                st.markdown(f"**Current status:** {t.status}")
                st.markdown(f"**Submitted:** {t.created_at}")
                st.markdown("**Device**")
                st.write(f"{t.device_type} — {t.brand} {t.model}")
                st.markdown("**Problem**")
                st.write(t.description)
                st.markdown("**Status history**")
                for h in t.status_history:
                    st.write(f"{h['at']} — {h['status']} — {h.get('note','')}")

elif view == "Customer Status":
    import time, json, pathlib

    st.title("Check your repair status")
    st.caption("Use the claim code given to you at intake.")

    # ---- helpers (local to this section) ----
    STATUS_STEPS = ["new", "received", "diagnosing", "repairing", "ready for pickup", "completed"]
    STEP_INDEX = {s: i for i, s in enumerate(STATUS_STEPS)}

    def status_progress(status: str) -> int:
        i = STEP_INDEX.get((status or "").lower().strip(), 0)
        return int(i * 100 / (len(STATUS_STEPS) - 1))

    # Optional Lottie support (safe if package not installed)
    def load_lottie(path: str):
        try:
            from streamlit_lottie import st_lottie  # pip install streamlit-lottie
        except Exception:
            return None, None
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            return st_lottie, data
        except Exception:
            return None, None

    ANIMS = {  # put .json files under assets/animations/ (or change paths)
        "new": "assets/animations/new.json",
        "received": "assets/animations/box.json",
        "diagnosing": "assets/animations/diagnose.json",
        "repairing": "assets/animations/repair.json",
        "ready for pickup": "assets/animations/ready.json",
        "completed": "assets/animations/done.json",
    }

    # tiny CSS shimmer for claim code
    st.markdown("""
    <style>
    .badge {
      display:inline-block; padding:6px 10px; border-radius:8px;
      background: linear-gradient(90deg, #1f2937, #374151, #1f2937);
      color:#e5e7eb; font-weight:600; letter-spacing:0.5px;
      animation: shimmer 2.2s infinite; background-size: 200% 100%;
    }
    @keyframes shimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }
    </style>
    """, unsafe_allow_html=True)

    # ---- form (unique key) ----
    with st.form("customer_status_form"):
        claim = st.text_input("Claim code", placeholder="e.g., 7H2K9QW").strip().upper()
        email = st.text_input("Email used at intake").strip()
        submitted = st.form_submit_button("Look up")

    if submitted:
        if not claim or not is_valid_email(email):
            st.error("Please enter a valid claim code and email.")
        else:
            with st.spinner("Looking up your ticket..."):
                t = find_ticket_by_claim(claim)
                time.sleep(0.4)  # purely visual

            if not t or t.email.strip().lower() != email.strip().lower():
                st.error("We couldn't find a ticket with that claim code and email.")
            else:
                st.subheader(f"Status for claim {t.claim_code}")
                st.markdown(f"**Current status:** {t.status}")
                st.markdown(f"Claim code: <span class='badge'>{t.claim_code}</span>", unsafe_allow_html=True)

                # progress bar
                st.markdown("**Progress**")
                st.progress(status_progress(t.status))
                st.caption(" → ".join(STATUS_STEPS))

                # optional Lottie animation
                lottie, anim = load_lottie(ANIMS.get(t.status.lower().strip(), ""))
                if lottie and anim:
                    lottie(anim, height=160, loop=True, key=f"anim_{t.status}")

                # little celebration when ready/completed
                if t.status.lower() in {"ready for pickup", "completed"}:
                    st.balloons()

                # details
                st.markdown("**Device**")
                st.write(f"{t.device_type} — {t.brand} {t.model}")
                st.markdown("**Problem**")
                st.write(t.description)
                st.markdown("**Status history**")
                for h in t.status_history:
                    st.write(f"{h['at']} — {h['status']} — {h.get('note','')}")

#fiziksel olarak print alinacak csv file tipi formatda
#teknisyenden asamsi daha kapsamli olabilir
#kullanici ile mail sistemi yeni parca
#desk de gorebilirsin


#TECHNICIAN_PASSWORD="your-strong-pass" streamlit run app_streamlit.py
