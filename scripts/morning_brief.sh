#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

python scripts/fetch_emails.py
python projects/morning-email/summarize.py