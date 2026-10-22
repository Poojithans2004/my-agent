#!/usr/bin/env python3
import json
import os
import urllib.request
import urllib.error
import time  
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / "secrets" / ".env"
BATCH_FILE = BASE_DIR / "projects" / "morning-email" / "unread_batch.json"
PREFS_FILE = BASE_DIR / "memory" / "preferences.md"
CLAUDE_MD = BASE_DIR / "CLAUDE.md"

def load_env(env_path):
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")



def call_gemini(api_key, system_rules, user_payload):
    models = (
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-flash-latest"
    )
    last_error = ""

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = json.dumps({
            "systemInstruction": {"parts": [{"text": system_rules}]},
            "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "temperature": 0.2
            }
        }).encode("utf-8")

        # Try each model up to 2 times before falling back to the next model
        for attempt in range(5):
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    parts = result["candidates"][0]["content"]["parts"]
                    return "".join(
                        p.get("text", "") for p in parts if not p.get("thought", False)
                    ).strip()
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                last_error = f"({e.code}) on {model}: {err_body}"
                if e.code == 404:
                    break  # Model not found, move to next model immediately
                if e.code in (429, 500, 503):
                    time.sleep(2)  # Wait 2 seconds and retry / fallback
                    continue
                raise RuntimeError(f"Gemini API Error {last_error}") from e

    raise RuntimeError(f"All Gemini models busy. Last error: {last_error}")
    for model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = json.dumps({
            "systemInstruction": {"parts": [{"text": system_rules}]},
            "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "temperature": 0.2
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            }
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                parts = result["candidates"][0]["content"]["parts"]
                return "".join(
                    p.get("text", "") for p in parts if not p.get("thought", False)
                ).strip()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                continue
            raise RuntimeError(f"Gemini API Error ({e.code}): {err_body}") from e

    raise RuntimeError("Could not find an active Gemini Flash model for this API key.")

def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": f"☕ Morning Email Brief:\n\n{text}"
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()

def main():
    load_env(ENV_FILE)
    if not BATCH_FILE.exists():
        print("No batch file found. Run fetch_emails.py first.")
        return

    emails = json.loads(BATCH_FILE.read_text(encoding="utf-8"))

    if not emails:
        summary = "Inbox clear—nothing urgent requires your attention this morning."
    else:
        system_rules = CLAUDE_MD.read_text(encoding="utf-8") if CLAUDE_MD.exists() else ""
        prefs = PREFS_FILE.read_text(encoding="utf-8") if PREFS_FILE.exists() else ""

        user_payload = (
            f"System Preferences:\n{prefs}\n\n"
            f"Email Data ({len(emails)} messages):\n{json.dumps(emails, ensure_ascii=False)}\n\n"
            "TASK: Based ONLY on the Email Data provided above, write my morning summary. "
            "Use clean sections and bullet points for:\n"
            "1. VIP / Contact Summary\n"
            "2. Urgent Matters\n"
            "3. Internships & Job Opportunities\n\n"
            "Strict Rule: Do NOT repeat my preferences or rules. Only output the final summary. If a section has no relevant emails, just write 'None'."
        )

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Missing GEMINI_API_KEY in secrets/.env")

        summary = call_gemini(api_key, system_rules, user_payload)

    print(summary)
    send_telegram(summary)

if __name__ == "__main__":
    main()