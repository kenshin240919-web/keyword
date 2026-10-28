@echo off
rem 키워드 직접 뽑기 페이지를 엽니다 (씨앗 키워드와 기간을 골라 따로 뽑기, 매일 리포트와 섞이지 않음).
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
python report_server.py --custom
if errorlevel 1 pause
