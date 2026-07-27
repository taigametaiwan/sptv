#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python sptv_api.py --output sptv.m3u --debug debug/sptv_debug.json
python audit_m3u.py sptv.m3u --strict --allow-empty
printf 'Hoàn tất: %s/sptv.m3u\n' "$PWD"
