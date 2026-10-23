@echo off
rem Opens the overall status page (starts the report server if it is off).
cd /d "%~dp0"
set PYTHONUTF8=1
python report_server.py --status
if errorlevel 1 pause
