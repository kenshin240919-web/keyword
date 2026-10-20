@echo off
rem Opens today's report (creates it first if it does not exist yet) with working "written" buttons
cd /d "%~dp0"
set PYTHONUTF8=1
python daily_keywords.py
if errorlevel 1 pause
