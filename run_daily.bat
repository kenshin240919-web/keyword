@echo off
rem Runs daily_keywords.py once per day and appends output to logs\daily.log
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONUTF8=1
python daily_keywords.py --skip-if-done >> logs\daily.log 2>&1
