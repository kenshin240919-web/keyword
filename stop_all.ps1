# guidejung 프로그램을 모두 끕니다 (바탕화면 'guidejung 끄기' = D:\guidejung\모두끄기.bat).
# 끄는 것: Blog Automator, autopost(사이트 글), shot(영상), 리포트 서버(홈), 블로그 크롬 4개, Flow 크롬.
# Local(워드프레스)은 다른 프로그램이라 그대로 둡니다. 글을 쓰는 중이면 먼저 물어봅니다 (2026-11-06).
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $PSScriptRoot

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
# Is a program on? Its port is listening. Which process is it? Its own command line: on this PC Windows names
# process 0 as the owner of every listening port (2026-11-09), so a port never led to the program and updates,
# 끄기 and 시작 all misjudged what was running.
function Test-Port([int]$port) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { return $true }
    return [bool](netstat -ano -p tcp | Select-String -Pattern ":$port\s+\S+\s+(LISTENING|수신 대기)")
}
function Get-AppPids([string]$app) {
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine })
    $found = switch ($app) {
        'blogauto' { $procs | Where-Object { $_.Name -eq 'electron.exe' -and $_.CommandLine -notmatch '--type=' -and "$($_.ExecutablePath) $($_.CommandLine)" -match 'BlogAutomator' } }
        'autopost' { $procs | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'app\.py' -and $_.CommandLine -match '--no-browser|autopost' } }
        'report' { $procs | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'report_server\.py' -and $_.CommandLine -match '--serve' } }
        'shot' {
            $procs | Where-Object { $p = $_; $p.Name -like 'python*' -and $p.CommandLine -match 'app\.py' -and $p.CommandLine -notmatch '--no-browser|autopost' -and
                ($p.CommandLine -match '\\shot\\' -or @($procs | Where-Object { $_.ProcessId -eq $p.ParentProcessId -and $_.CommandLine -match 'run_typecast' }).Count) }
        }
    }
    @($found | ForEach-Object { [int]$_.ProcessId })
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

# Programs, found by their command lines (all copies, e.g. a second shot that took port 8791).
$apps = @(@{ Name = 'Blog Automator'; App = 'blogauto'; Port = 37321 }, @{ Name = 'autopost (사이트 글)'; App = 'autopost'; Port = 8777 },
          @{ Name = 'shot (영상)'; App = 'shot'; Port = 8790 })
foreach ($app in $apps) {
    $ids = Get-AppPids $app.App
    if ($ids.Count) { foreach ($id in $ids) { Stop-AppTree $id }; Say "[$($app.Name)] 껐습니다." Green }
    elseif (Test-Port $app.Port) { Say "[$($app.Name)] 켜져 있는데 찾지 못했습니다. 작업 관리자에서 직접 꺼 주세요." Yellow }
    else { Say "[$($app.Name)] 이미 꺼져 있음" }
}

# The report server (home page): its own shutdown call, else its process (the call once failed while it ran).
$homeOff = $false
try {
    Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/shutdown' -Headers @{ 'X-Report-App' = '1' } -Body '{}' -ContentType 'application/json' -TimeoutSec 5 | Out-Null
    $homeOff = $true
} catch { }
$ids = Get-AppPids 'report'
if ($ids.Count) { Start-Sleep 1; foreach ($id in (Get-AppPids 'report')) { taskkill /pid $id /t /f | Out-Null }; $homeOff = $true }
Say $(if ($homeOff) { '[guidejung 홈 (리포트 서버)] 껐습니다.' } elseif (Test-Port 8765) { '[guidejung 홈 (리포트 서버)] 켜져 있는데 찾지 못했습니다.' } else { '[guidejung 홈 (리포트 서버)] 이미 꺼져 있음' }) $(if ($homeOff) { 'Green' } else { 'Gray' })

# Only Chromes with their own profile folder (Flow, and blog 1~4 when started that way). Blog Chromes that are
# profiles of the everyday Chrome stay open with it: closing them would close the user's own Chrome too.
$chromes = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'chrome-[1-4]["\\ ]|chrome-[1-4]$|chrome-flow' -and $_.CommandLine -notmatch '--type=' })
foreach ($c in $chromes) { taskkill /pid $c.ProcessId /t /f | Out-Null }
Say $(if ($chromes.Count) { "[Flow·블로그 전용 크롬] $($chromes.Count)개 껐습니다." } else { '[Flow·블로그 전용 크롬] 이미 꺼져 있음 (평소 크롬 안의 블로그 프로필은 그대로 둠)' }) $(if ($chromes.Count) { 'Green' } else { 'Gray' })

Say '=== 끝 — Local(워드프레스)은 그대로 켜 두었습니다. 다시 켤 때는 바탕화면 guidejung 시작. 이 창은 5초 뒤 닫힙니다. ===' Cyan
Start-Sleep 5
