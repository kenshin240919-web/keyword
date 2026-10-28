@echo off
rem 직접 뽑기: 원하는 씨앗 키워드로 추천 키워드를 따로 뽑습니다 (매일 리포트와 기록은 그대로).
cd /d "%~dp0"
chcp 65001 >nul
title 키워드 직접 뽑기
set PYTHONUTF8=1
python daily_keywords.py --seeds
echo.
pause
