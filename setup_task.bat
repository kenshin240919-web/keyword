@echo off
rem Registers run_daily.bat in Windows Task Scheduler:
rem   at every logon (1 min delay) and daily 07:50; runs at most once per day.
set "BAT=%~dp0run_daily.bat"
set "DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$a = New-ScheduledTaskAction -Execute $env:BAT -WorkingDirectory $env:DIR; $l = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; $l.Delay = 'PT1M'; $t = New-ScheduledTaskTrigger -Daily -At 07:50; $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Register-ScheduledTask -TaskName BlogKeywords -Action $a -Trigger @($l, $t) -Settings $s -Force | Out-Null; Write-Host 'OK - BlogKeywords registered: at logon + daily 07:50, once per day'"
pause
