@echo off
rem Opens the latest report with working "written" buttons (starts the local record server if needed)
cd /d "%~dp0"
set PYTHONUTF8=1
python report_server.py
