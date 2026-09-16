#!/usr/bin/env bash
# Run VidGrab on Linux / WSL / macOS

set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

missing=()
python3 -c "import tkinter" 2>/dev/null || missing+=("python3-tk")
python3 -c "import ensurepip" 2>/dev/null || missing+=("python3-venv")
python3 -m pip --version >/dev/null 2>&1 || missing+=("python3-pip")

if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: Missing system packages: ${missing[*]}"
    echo ""
    echo "Install them with:"
    echo "  sudo apt update"
    echo "  sudo apt install -y python3-venv python3-pip python3-tk"
    echo ""
    echo "Then remove the broken venv (if any) and run again:"
    echo "  rm -rf .venv"
    echo "  ./run.sh"
    exit 1
fi

if [ -d .venv ] && [ ! -f .venv/bin/activate ]; then
    echo "Removing broken .venv (missing activate script)..."
    rm -rf .venv
fi

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip -q
pip install -r requirements.txt -q

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo ""
    echo "WARNING: ffmpeg not found. MP3 and most MP4 downloads need it."
    echo "Install with:  sudo apt install ffmpeg"
    echo ""
fi

python -m vidgrab
