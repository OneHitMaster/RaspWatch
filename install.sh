#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== RaspWatch installer =="

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Please run as a normal user (not root)."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found."
  exit 1
fi

echo "== Backend venv =="
cd "${ROOT_DIR}/backend"
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "== Optional: build web UI (requires node) =="
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  cd "${ROOT_DIR}/web"
  npm install
  npm run build
else
  echo "Skipping web build (node/npm not found). Using legacy frontend."
fi

echo "== systemd service (optional) =="
if command -v systemctl >/dev/null 2>&1; then
  SERVICE_SRC="${ROOT_DIR}/raspwatch.service"
  SERVICE_DST="/etc/systemd/system/raspwatch.service"
  echo "Copying ${SERVICE_SRC} -> ${SERVICE_DST} (sudo)"
  sudo cp "${SERVICE_SRC}" "${SERVICE_DST}"
  sudo systemctl daemon-reload
  sudo systemctl enable raspwatch
  sudo systemctl restart raspwatch
  echo "RaspWatch service installed and started."
  echo "Open: http://<pi-ip>:9090"
else
  echo "systemctl not found; run manually: backend/venv/bin/python backend/main.py"
fi

