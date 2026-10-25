@echo off
rem Opens today's report (creates it first if it does not exist yet) with working "written" buttons
cd /d "%~dp0"
chcp 65001 >nul
title 오늘의 리포트
set PYTHONUTF8=1
echo 오늘의 리포트를 여는 중입니다. 오늘 처음이면 키워드를 뽑느라 몇 분 걸립니다.
python daily_keywords.py
if errorlevel 1 (
  echo.
  echo 리포트를 열지 못했습니다. 이 창을 캡처해서 Claude에게 보내 주세요.
  pause
)
