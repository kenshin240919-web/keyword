@echo off
rem Google Trends "trending now" list on its own: saves trends\*.html/.csv and opens the page
rem (python google_trends.py --help for options: --hours 168, --active, --all)
cd /d "%~dp0"
chcp 65001 >nul
title 구글 트렌드
set PYTHONUTF8=1
echo 구글 트렌드 지금 뜨는 검색어를 받는 중입니다...
python google_trends.py %*
if errorlevel 1 (
  echo.
  echo 트렌드를 받지 못했습니다. 이 창을 캡처해서 Claude에게 보내 주세요.
  pause
)
