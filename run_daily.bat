@echo off
rem Runs daily_keywords.py and appends output to logs\daily.log
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONUTF8=1
python daily_keywords.py >> logs\daily.log 2>&1
