@echo off
rem Runs at logon and 07:50 (Task Scheduler): first updates all guidejung programs from GitHub,
rem then runs daily_keywords.py once per day. Output goes to logs\update.log and logs\daily.log.
rem Everything is in one ( ) block: cmd reads the block before running it, so the update may
rem replace this file safely.
(
  cd /d "%~dp0"
  if not exist logs mkdir logs
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_all.ps1" -Startup >NUL 2>&1
  set PYTHONUTF8=1
  python daily_keywords.py --skip-if-done >> logs\daily.log 2>&1
  exit /b
)
