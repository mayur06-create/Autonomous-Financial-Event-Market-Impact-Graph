@echo off
cd /d "%~dp0\.."
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
