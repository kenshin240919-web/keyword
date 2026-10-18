@echo off
rem Registers run_daily.bat in Windows Task Scheduler (daily 07:50, runs ASAP if missed)
set "BAT=%~dp0run_daily.bat"
set "DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$a = New-ScheduledTaskAction -Execute $env:BAT -WorkingDirectory $env:DIR; $t = New-ScheduledTaskTrigger -Daily -At 07:50; $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Register-ScheduledTask -TaskName BlogKeywords -Action $a -Trigger $t -Settings $s -Force | Out-Null; Write-Host 'OK - BlogKeywords task registered, daily 07:50'"
pause
