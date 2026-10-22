@echo off
rem Updates all guidejung programs from GitHub (same as D:\guidejung\update launcher).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_all.ps1"
pause
