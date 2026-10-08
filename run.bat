@echo off
REM LordBlack Harness launcher (Windows)
cd /d "%~dp0"

if not exist venv (
    echo First run: creating Python virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q --disable-pip-version-check -r requirements.txt

python app.py %*
