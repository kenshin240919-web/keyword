@echo off
rem Registers run_daily.bat in Windows Task Scheduler:
rem   at every logon (1 min delay) and daily 07:50; runs at most once per day.
set "BAT=%~dp0run_daily.bat"
set "DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $u = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name; $a = New-ScheduledTaskAction -Execute $env:BAT -WorkingDirectory $env:DIR; $l = New-ScheduledTaskTrigger -AtLogOn -User $u; $l.Delay = 'PT1M'; $t = New-ScheduledTaskTrigger -Daily -At 07:50; $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; $p = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive; Register-ScheduledTask -TaskName BlogKeywords -Action $a -Trigger @($l, $t) -Settings $s -Principal $p -Force -ErrorAction Stop | Out-Null; Write-Host ('OK - BlogKeywords registered for ' + $u + ': at logon + daily 07:50, once per day') } catch { Write-Host ('FAILED - ' + $_.Exception.Message) }"
pause
