#!/usr/bin/env bash
# Uruchomienie bez Dockera i bez uv (Linux/macOS): venv + pip + python -m src.
# Bez argumentów = "run" (input/ -> output/). Przykłady: ./start.sh check, ./start.sh gui
# Odpowiednik start.bat (Windows). Wymaga Pythona 3.13+ i pliku .env z kluczem API.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    PY=""
    for cand in python3.13 python3 python; do
        if command -v "$cand" >/dev/null 2>&1 \
            && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 13))' 2>/dev/null; then
            PY="$cand"
            break
        fi
    done
    if [ -z "$PY" ]; then
        echo "Brak Pythona 3.13+. Zainstaluj z https://www.python.org/downloads/" >&2
        exit 1
    fi
    "$PY" -m venv .venv
fi

# venv z uv nie ma pip; doinstaluj go w razie potrzeby
.venv/bin/python -m pip --version >/dev/null 2>&1 || .venv/bin/python -m ensurepip -q
echo "[start] Instaluje zaleznosci (pierwsze uruchomienie moze potrwac kilka minut)..."
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

if [ $# -eq 0 ]; then
    exec .venv/bin/python -m src run
fi
exec .venv/bin/python -m src "$@"
