#!/usr/bin/env bash
# LordBlack Harness launcher (Linux/macOS)
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    echo "First run: creating Python virtual environment..."
    python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --disable-pip-version-check -r requirements.txt

python app.py "$@"
