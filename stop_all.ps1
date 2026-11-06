# guidejung 프로그램을 모두 끕니다 (바탕화면 'guidejung 끄기' = D:\guidejung\모두끄기.bat).
# 끄는 것: Blog Automator, autopost(사이트 글), shot(영상), 리포트 서버(홈), 블로그 크롬 4개, Flow 크롬.
# Local(워드프레스)은 다른 프로그램이라 그대로 둡니다. 글을 쓰는 중이면 먼저 물어봅니다 (2026-11-06).
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $PSScriptRoot

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Get-ListenPid([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
}
# Ends the program with its children and the console that started it: a cmd window, or shot's run_typecast.ps1
# loop (it would start shot again). Any other parent is left alone (its number may belong to another program now).
function Stop-AppTree([int]$procId) {
    $parentId = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).ParentProcessId
    $parent = if ($parentId) { Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue }
    $target = $procId
    if ($parent -and ($parent.Name -eq 'cmd.exe' -or ($parent.Name -eq 'powershell.exe' -and $parent.CommandLine -like '*run_typecast*'))) { $target = $parentId }
    taskkill /pid $target /t /f | Out-Null
}
function Get-Json([string]$url, [hashtable]$headers = @{}) {
    try { Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 5 } catch { $null }
}

Say '=== guidejung 끄기 ===' Cyan

# Work in progress? Ask first: a post being written or saved would be cut off.
$busy = @()
$blog = Get-Json 'http://127.0.0.1:37321/api/status' @{ 'X-Blogauto' = '1' }
if ($blog -and ($blog.generating -or @($blog.jobs | Where-Object { $_.styles -and @($_.styles.PSObject.Properties.Value | Where-Object { $_.status -eq 'running' }).Count }).Count)) {
    $busy += '네이버 글 작성·임시저장'
}
$auto = Get-Json 'http://127.0.0.1:8777/api/state'
if ($auto -and @($auto.jobs | Where-Object { $_.state -eq '진행 중' }).Count) { $busy += '사이트 글 작성·배포' }
if ($busy.Count) {
    Say ("지금 진행 중인 작업이 있습니다: {0}" -f ($busy -join ', ')) Yellow
    $answer = Read-Host '그래도 끌까요? 끄면 하던 작업은 다시 해야 합니다 (Y = 끄기, 그 밖의 키 = 취소)'
    if ($answer -notmatch '^[Yy]') { Say '끄지 않았습니다.' Green; Start-Sleep 3; exit }
}

# Programs, by the port each one listens on.
$apps = @(@{ Name = 'Blog Automator'; Port = 37321 }, @{ Name = 'autopost (사이트 글)'; Port = 8777 })
foreach ($app in $apps) {
    $procId = Get-ListenPid $app.Port
    if ($procId) { Stop-AppTree $procId; Say "[$($app.Name)] 껐습니다." Green } else { Say "[$($app.Name)] 이미 꺼져 있음" }
}
$shotOff = $true
foreach ($port in 8790..8799) {
    $procId = Get-ListenPid $port
    if ($procId -and (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName -like 'python*') { Stop-AppTree $procId; $shotOff = $false }
}
Say $(if ($shotOff) { '[shot (영상)] 이미 꺼져 있음' } else { '[shot (영상)] 껐습니다.' }) $(if ($shotOff) { 'Gray' } else { 'Green' })

# The report server (home page) stops through its own shutdown call.
try {
    Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/shutdown' -Headers @{ 'X-Report-App' = '1' } -Body '{}' -ContentType 'application/json' -TimeoutSec 5 | Out-Null
    Say '[guidejung 홈 (리포트 서버)] 껐습니다.' Green
} catch { Say '[guidejung 홈 (리포트 서버)] 이미 꺼져 있음' }

# Only the dedicated Chromes (blog 1~4, Flow): the user's own Chrome stays open.
$chromes = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'chrome-[1-4]["\\ ]|chrome-[1-4]$|chrome-flow' -and $_.CommandLine -notmatch '--type=' })
foreach ($c in $chromes) { taskkill /pid $c.ProcessId /t /f | Out-Null }
Say $(if ($chromes.Count) { "[블로그·Flow 크롬] $($chromes.Count)개 껐습니다." } else { '[블로그·Flow 크롬] 이미 꺼져 있음' }) $(if ($chromes.Count) { 'Green' } else { 'Gray' })

Say '=== 끝 — Local(워드프레스)은 그대로 켜 두었습니다. 다시 켤 때는 바탕화면 guidejung 시작. 이 창은 5초 뒤 닫힙니다. ===' Cyan
Start-Sleep 5
