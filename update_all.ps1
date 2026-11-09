# D:\guidejung 아래 4개 프로그램(key, BlogAutomator, move\autopost, shot)을 GitHub 최신 코드로 받고,
# 새 코드를 받은 프로그램이 켜져 있으면 다시 켭니다. 작업 중인 프로그램은 건드리지 않습니다.
#   - 업데이트.bat (D:\guidejung, 더블클릭)  → 이 스크립트
#   - run_daily.bat (PC 켤 때·07:50 작업 스케줄러) → 이 스크립트 -Startup
# 기록: key\logs\update.log
param([switch]$Startup, [switch]$Rerun)

$ErrorActionPreference = 'Continue'
$env:GIT_TERMINAL_PROMPT = '0'  # never wait for a password in a hidden window
$base = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'update.log'
$problems = 0

function Say([string]$text, [string]$color = 'Gray') {
    Write-Host $text -ForegroundColor $color
    Add-Content -LiteralPath $logFile -Value ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text) -Encoding UTF8
}

$branch = 'claude/practical-hypatia-qnp7l5'
$apps = @(
    @{ Name = '키워드 리포트'; Dir = 'key'; Branch = $branch; Port = 8765 },
    @{ Name = 'BlogAutomator'; Dir = 'BlogAutomator'; Branch = $branch; Port = 37321 },
    @{ Name = 'autopost'; Dir = 'move\autopost'; Branch = $branch; Port = 8777 },  # main + Claude's changes
    @{ Name = 'shot'; Dir = 'shot'; Branch = $branch; Port = 8790 }
)
$nodeDir = 'C:\Program Files\nodejs'
if (Test-Path $nodeDir) { $env:PATH = "$nodeDir;$env:PATH" }

function Get-ListenPid([int]$port) {
    $found = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
    if ($found) { return $found }
    # Get-NetTCPConnection found nothing on this PC while the programs were running, so nothing was restarted
    # after an update (2026-11-09): netstat as a second way.
    foreach ($line in (netstat -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$port\s+\S+\s+(?:LISTENING|수신 대기)\s+(\d+)") { return [int]$Matches[1] }
    }
    return $null
}

function Wait-PortFree([int]$port) {
    for ($i = 0; $i -lt 30 -and (Get-ListenPid $port); $i++) { Start-Sleep -Milliseconds 500 }
}

# Ends the program and its console window (the cmd.exe that started it, when there is one).
function Stop-AppTree([int]$procId) {
    $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).ParentProcessId
    $target = $procId
    if ($parent -and (Get-Process -Id $parent -ErrorAction SilentlyContinue).ProcessName -eq 'cmd') { $target = $parent }
    taskkill /pid $target /t /f | Out-Null
}

# Returns @{ ok; status; data; error } instead of throwing.
function Invoke-Local([string]$method, [string]$url, [hashtable]$headers = @{}) {
    try {
        $params = @{ Method = $method; Uri = $url; Headers = $headers; TimeoutSec = 10 }
        if ($method -eq 'POST') { $params.Body = '{}'; $params.ContentType = 'application/json' }
        return @{ ok = $true; data = (Invoke-RestMethod @params) }
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        $msg = if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        return @{ ok = $false; status = $code; error = $msg }
    }
}

function Restart-App($app, [string]$dir) {
    $procId = Get-ListenPid $app.Port
    # The report server and shot restart through their own address, so they do not need the process number.
    if (-not $procId -and $app.Dir -notin @('key', 'shot')) { Say '  꺼져 있어서 다시 켤 필요가 없습니다 (다음에 켤 때 새 버전).'; return }
    switch ($app.Dir) {
        'key' {
            # The report server starts again (new code) the next time a report is opened.
            $r = Invoke-Local 'POST' 'http://127.0.0.1:8765/api/shutdown' @{ 'X-Report-App' = '1' }
            # Started again at once (no window): an open guidejung home tab keeps working.
            if ($r.ok) {
                Start-Sleep 1
                Push-Location $dir; $env:PYTHONUTF8 = '1'; & python report_server.py --start; Pop-Location
                Say '  guidejung 홈(리포트 서버)을 새 버전으로 다시 켰습니다. 홈 탭이 이상하면 새로 고침(F5) 해 주세요.' Green
            } else { Say '  guidejung 홈(리포트 서버)이 꺼져 있어 다음에 켤 때 새 버전으로 켜집니다.' }
        }
        'BlogAutomator' {
            $r = Invoke-Local 'GET' 'http://127.0.0.1:37321/api/status' @{ 'X-Blogauto' = '1' }
            $busy = $r.ok -and ($r.data.generating -or @($r.data.jobs | Where-Object {
                $_.styles -and @($_.styles.PSObject.Properties.Value | Where-Object { $_.status -eq 'running' }).Count }).Count)
            if ($busy) { Say '  글 작성·임시저장 중이라 다시 켜지 않았습니다. 끝난 뒤 업데이트.bat을 한 번 더 실행하세요.' Yellow; $script:problems++; return }
            Stop-AppTree $procId
            Wait-PortFree $app.Port
            Start-Process -FilePath (Join-Path $dir '실행.bat') -WorkingDirectory $dir -WindowStyle Hidden
            Say '  BlogAutomator를 다시 켰습니다. 크롬 확장은 1분 안에 스스로 새로고침합니다.' Green
        }
        'move\autopost' {
            $r = Invoke-Local 'GET' 'http://127.0.0.1:8777/api/state'
            if ($r.ok -and @($r.data.jobs | Where-Object { $_.state -eq '진행 중' }).Count) {
                Say '  사이트 글 작성 중이라 다시 켜지 않았습니다. 끝난 뒤 업데이트.bat을 한 번 더 실행하세요.' Yellow; $script:problems++; return
            }
            Stop-AppTree $procId
            Wait-PortFree $app.Port
            Start-Process -FilePath 'python' -ArgumentList 'app.py', '--no-browser' -WorkingDirectory $dir -WindowStyle Hidden
            Say '  autopost를 다시 켰습니다 (창 없이).' Green
        }
        'shot' {
            # shot keeps the API keys typed at start: it exits with code 75 and its launcher starts it again.
            $r = Invoke-Local 'POST' 'http://127.0.0.1:8790/api/restart' @{ 'X-Shot-Update' = '1' }
            if ($r.ok) { Say '  shot을 다시 켰습니다 (입력한 키 그대로).' Green }
            elseif ($r.status -eq 409) { Say '  영상 제작 중이라 다시 켜지 않았습니다. 끝난 뒤 업데이트.bat을 한 번 더 실행하세요.' Yellow; $script:problems++ }
            elseif (-not $procId) { Say '  꺼져 있어서 다시 켤 필요가 없습니다 (다음에 켤 때 새 버전).' }
            else { Say '  shot 창을 닫고 run_typecast.bat으로 직접 다시 켜 주세요 (이번 한 번만).' Yellow; $script:problems++ }
        }
    }
}

Say ('=== 업데이트 시작' + $(if ($Startup) { ' (자동)' } else { '' }) + ' ===') Cyan
foreach ($app in $apps) {
    $dir = Join-Path $base $app.Dir
    Say ("[{0}] {1}" -f $app.Name, $dir) White
    if (-not (Test-Path (Join-Path $dir '.git'))) { Say '  git 저장소가 아니어서 건너뜁니다.' Yellow; $problems++; continue }
    $old = (git -C $dir rev-parse HEAD) 2>$null
    # Fetch into origin/<branch> by an explicit refspec and fast-forward to it. ("git pull origin <branch>"
    # fails with "Cannot fast-forward to multiple branches" when the clone's fetch settings bring more.)
    # cmd merges git's stderr into plain text (PowerShell 5 would turn it into error records).
    $ref = "refs/remotes/origin/$($app.Branch)"
    $out = (cmd /c "git -C `"$dir`" fetch origin +refs/heads/$($app.Branch):$ref 2>&1 && git -C `"$dir`" merge --ff-only $ref 2>&1" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        Say "  받기 실패: $out" Red
        Say '  (이 폴더에서 직접 고친 파일이 있으면 생길 수 있습니다. 이 내용을 Claude에게 보여 주세요.)' Red
        $problems++; continue
    }
    $new = (git -C $dir rev-parse HEAD) 2>$null
    if ($old -eq $new) { Say '  이미 최신입니다.'; continue }
    $changed = @(git -C $dir diff --name-only $old $new)
    Say ("  새 코드를 받았습니다 (파일 {0}개)." -f $changed.Count) Green
    if ($changed -contains 'package.json' -or $changed -contains 'package-lock.json') {
        Say '  npm install 실행 중...'
        Push-Location $dir; cmd /c 'npm install --no-audit --no-fund 2>&1' | Out-Null; Pop-Location
    }
    if ($changed -contains 'requirements.txt') {
        Say '  파이썬 패키지 설치 중...'
        Push-Location $dir; cmd /c 'python -m pip install -q -r requirements.txt 2>&1' | Out-Null; Pop-Location
    }
    Restart-App $app $dir
    # This script itself was updated: the rest is done by the new version (PowerShell already loaded this one).
    if ($app.Dir -eq 'key' -and $changed -contains 'update_all.ps1' -and -not $Rerun) {
        Say '  업데이트 스크립트가 바뀌어 새 버전으로 이어서 실행합니다.' Cyan
        $next = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'update_all.ps1'), '-Rerun')
        if ($Startup) { $next += '-Startup' }
        & powershell.exe @next
        exit $LASTEXITCODE
    }
}

# Connection guide for Claude (kept in the shot repo) and this script's double-click launcher.
$guide = Join-Path $base 'shot\docs\guidejung-CLAUDE.md'
$guideDest = Join-Path $base 'CLAUDE.md'
if ((Test-Path $guide) -and (-not (Test-Path $guideDest) -or (Get-FileHash $guide).Hash -ne (Get-FileHash $guideDest).Hash)) {
    Copy-Item -LiteralPath $guide -Destination $guideDest -Force
    Say '연결 안내 파일(D:\guidejung\CLAUDE.md)을 새로 복사했습니다.'
}
$launcher = Join-Path $base '업데이트.bat'
$launcherText = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0key\update_all.ps1`"`r`npause`r`n"
if (-not (Test-Path $launcher) -or [IO.File]::ReadAllText($launcher) -ne $launcherText) {
    [IO.File]::WriteAllText($launcher, $launcherText, [Text.Encoding]::ASCII)
    Say "더블클릭용 $launcher 을(를) 만들었습니다."
}

# One-click start / stop of every program (2026-11-06: one home page, three desktop icons).
$starter = Join-Path $base '전체실행.bat'
$starterText = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0key\start_all.ps1`"`r`n"
if (-not (Test-Path $starter) -or [IO.File]::ReadAllText($starter) -ne $starterText) {
    [IO.File]::WriteAllText($starter, $starterText, [Text.Encoding]::ASCII)
    Say "한 번에 켜기용 $starter 을(를) 만들었습니다."
}
$stopper = Join-Path $base '모두끄기.bat'
$stopperText = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0key\stop_all.ps1`"`r`n"
if (-not (Test-Path $stopper) -or [IO.File]::ReadAllText($stopper) -ne $stopperText) {
    [IO.File]::WriteAllText($stopper, $stopperText, [Text.Encoding]::ASCII)
    Say "한 번에 끄기용 $stopper 을(를) 만들었습니다."
}

# Desktop: only 'guidejung 시작 / 업데이트 / 끄기'. The other guidejung shortcuts (blog Chromes, Flow Chrome, the old
# 전체 실행 / 진행 상황) go to D:\guidejung\바로가기; start_all.ps1 finds the blog Chrome shortcuts there.
$desktop = [Environment]::GetFolderPath('Desktop')
$tools = Join-Path $base '바로가기'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
function Set-Shortcut([string]$path, [string]$target, [string]$arguments = '', [int]$style = 1) {
    try {
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
        $lnk.TargetPath = $target; $lnk.Arguments = $arguments; $lnk.WorkingDirectory = $base; $lnk.WindowStyle = $style; $lnk.Save()
        return $true
    } catch { Say "바로가기를 만들지 못했습니다 ($path): $($_.Exception.Message)" Yellow; return $false }
}
if ($desktop) {
    $icons = @(@{ Name = 'guidejung 시작'; Target = $starter; Style = 7 }, @{ Name = 'guidejung 업데이트'; Target = $launcher; Style = 1 },
               @{ Name = 'guidejung 끄기'; Target = $stopper; Style = 1 })
    foreach ($icon in $icons) {
        $path = Join-Path $desktop "$($icon.Name).lnk"
        if (-not (Test-Path $path) -and (Set-Shortcut $path $icon.Target '' $icon.Style)) { Say "바탕화면에 '$($icon.Name)' 아이콘을 만들었습니다." Green }
    }
    foreach ($old in @('guidejung 전체 실행.lnk', 'guidejung 진행 상황.lnk')) {  # replaced by 'guidejung 시작' and its home page
        $path = Join-Path $desktop $old
        if (Test-Path $path) { Remove-Item -LiteralPath $path -Force; Say "바탕화면의 '$($old -replace '\.lnk$')' 아이콘을 지웠습니다 (guidejung 시작이 대신함)." }
    }
    $moved = @(Get-ChildItem -LiteralPath $desktop -Filter '*.lnk' -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^블로그 [1-4]번' -or $_.Name -eq 'Flow 영상 크롬.lnk' })
    foreach ($m in $moved) { Move-Item -LiteralPath $m.FullName -Destination (Join-Path $tools $m.Name) -Force }
    if ($moved.Count) { Say "바탕화면의 크롬 바로가기 $($moved.Count)개를 $tools 폴더로 옮겼습니다." Green }
}
$public = [Environment]::GetFolderPath('CommonDesktopDirectory')
$publicLeft = @(Get-ChildItem -LiteralPath $public -Filter '*.lnk' -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^블로그 [1-4]번|^Flow 영상 크롬|^guidejung ' })
if ($publicLeft.Count) { Say "공용 바탕화면의 바로가기($($publicLeft.Name -join ', '))는 관리자 권한이 있어야 옮길 수 있어 그대로 두었습니다. 직접 $tools 폴더로 옮겨 주세요." Yellow }

# Flow Chrome shortcut (its own profile D:\guidejung\chrome-flow, kept rendering while minimized), in the 바로가기 folder.
$flowShortcut = Join-Path $tools 'Flow 영상 크롬.lnk'
$chromePath = @((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe' -ErrorAction SilentlyContinue).'(default)',
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $chromePath) { Say '크롬(chrome.exe)을 찾지 못해 Flow 크롬 바로가기를 만들지 못했습니다.' Yellow }
elseif (-not (Test-Path $flowShortcut)) {
    $flowArgs = "--user-data-dir=`"$(Join-Path $base 'chrome-flow')`" --disable-renderer-backgrounding --disable-background-timer-throttling --disable-backgrounding-occluded-windows https://flow.google.com/"
    if (Set-Shortcut $flowShortcut $chromePath $flowArgs) { Say "$tools 폴더에 'Flow 영상 크롬' 바로가기를 만들었습니다." }
}

if ($problems) { Say "=== 끝 (확인할 것 $problems 건, 위 노란색·빨간색 줄) ===" Yellow }
else { Say '=== 끝 (모두 정상) ===' Green }
