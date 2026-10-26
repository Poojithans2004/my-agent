#!/usr/bin/env python3
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / "secrets" / ".env"
OUTPUT_FILE = BASE_DIR / "projects" / "morning-email" / "unread_batch.json"

def load_env(env_path):
    if not env_path.exists():
        return  # In the cloud, variables are injected directly via GitHub Secrets
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
def decode_str(val):
    if not val:
        return ""
    return "".join(
        t.decode(enc or "utf-8", errors="replace") if isinstance(t, bytes) else t
        for t, enc in decode_header(val)
    )

def get_plain_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    # Strip quoted reply history (lines starting with '>') and collapse whitespace
    lines = [line for line in body.splitlines() if not line.strip().startswith(">")]
    cleaned = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return cleaned[:1000]

def main():
    load_env(ENV_FILE)
    host = os.environ["EMAIL_HOST"]
    user = os.environ["EMAIL_USER"]
    password = os.environ["EMAIL_PASS"]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    since_str = cutoff.strftime("%d-%b-%Y")

    mail = imaplib.IMAP4_SSL(host)
    mail.login(user, password)
    mail.select("INBOX", readonly=True)  # readonly=True leaves messages marked unread

    _, data = mail.search(None, f'(UNSEEN SINCE "{since_str}")')
    msg_ids = data[0].split()

    # Cap at the 30 most recent emails to prevent timeouts
    msg_ids = msg_ids[-15:]

    batch = []
    # Fetch all headers + text in one pass
    for m_id in reversed(msg_ids):
        _, msg_data = mail.fetch(m_id, "(RFC822)")
        for part in msg_data:
            if not isinstance(part, tuple):
                continue
            msg = email.message_from_bytes(part[1])

           # 1. Strict 12-hour filter in Python
            date_hdr = msg.get("Date", "")
            if not date_hdr:
                continue
            try:
                msg_date = parsedate_to_datetime(date_hdr)
                if msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                else:
                    msg_date = msg_date.astimezone(timezone.utc)
                
                # Strictly ignore anything older than 12 hours
                if msg_date < cutoff:
                    continue
            except Exception:
                # If the date header is malformed/unreadable, skip it instead of letting it through
                continue


            # # 2. Deterministic bulk/automated filter (Zero AI needed)
            # precedence = msg.get("Precedence", "").lower()
            # auto_submitted = msg.get("Auto-Submitted", "").lower()
            # if precedence in ("bulk", "list", "junk") or (auto_submitted and auto_submitted != "no"):
            #     continue

            batch.append({
                "from": decode_str(msg.get("From")),
                "subject": decode_str(msg.get("Subject")),
                "date": msg.get("Date", ""),
                "has_unsubscribe": bool(msg.get("List-Unsubscribe")),
                "snippet": get_plain_body(msg)
            })

    mail.logout()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    main()