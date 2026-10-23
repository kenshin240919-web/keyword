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
    @{ Name = 'autopost'; Dir = 'move\autopost'; Branch = 'main'; Port = 8777 },
    @{ Name = 'shot'; Dir = 'shot'; Branch = $branch; Port = 8790 }
)
$nodeDir = 'C:\Program Files\nodejs'
if (Test-Path $nodeDir) { $env:PATH = "$nodeDir;$env:PATH" }

function Get-ListenPid([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
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
    if (-not $procId) { return }
    switch ($app.Dir) {
        'key' {
            # The report server starts again (new code) the next time a report is opened.
            $r = Invoke-Local 'POST' 'http://127.0.0.1:8765/api/shutdown' @{ 'X-Report-App' = '1' }
            if ($r.ok) { Say '  리포트 서버를 껐습니다. 다음에 리포트를 열면 새 버전으로 켜집니다.' }
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
            Start-Process -FilePath 'python' -ArgumentList 'app.py', '--no-browser' -WorkingDirectory $dir -WindowStyle Minimized
            Say '  autopost를 다시 켰습니다 (작업 표시줄에 최소화).' Green
        }
        'shot' {
            # shot keeps the API keys typed at start: it exits with code 75 and its launcher starts it again.
            $r = Invoke-Local 'POST' 'http://127.0.0.1:8790/api/restart' @{ 'X-Shot-Update' = '1' }
            if ($r.ok) { Say '  shot을 다시 켰습니다 (입력한 키 그대로).' Green }
            elseif ($r.status -eq 409) { Say '  영상 제작 중이라 다시 켜지 않았습니다. 끝난 뒤 업데이트.bat을 한 번 더 실행하세요.' Yellow; $script:problems++ }
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

# One-click start of every program, plus a desktop shortcut to it.
$starter = Join-Path $base '전체실행.bat'
$starterText = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0key\start_all.ps1`"`r`n"
if (-not (Test-Path $starter) -or [IO.File]::ReadAllText($starter) -ne $starterText) {
    [IO.File]::WriteAllText($starter, $starterText, [Text.Encoding]::ASCII)
    Say "한 번에 켜기용 $starter 을(를) 만들었습니다."
}
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = if ($desktop) { Join-Path $desktop 'guidejung 전체 실행.lnk' } else { $null }
if ($shortcut -and -not (Test-Path $shortcut)) {
    try {
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
        $lnk.TargetPath = $starter; $lnk.WorkingDirectory = $base; $lnk.Save()
        Say "바탕화면에 'guidejung 전체 실행' 바로가기를 만들었습니다."
    } catch { Say "바탕화면 바로가기를 만들지 못했습니다: $($_.Exception.Message)" Yellow }
}

# Desktop shortcut to the overall status page (starts the report server when it is off).
$statusShortcut = if ($desktop) { Join-Path $desktop 'guidejung 진행 상황.lnk' } else { $null }
if ($statusShortcut -and -not (Test-Path $statusShortcut)) {
    try {
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($statusShortcut)
        $lnk.TargetPath = Join-Path $PSScriptRoot 'progress.bat'; $lnk.WorkingDirectory = $PSScriptRoot; $lnk.WindowStyle = 7; $lnk.Save()
        Say "바탕화면에 'guidejung 진행 상황' 바로가기를 만들었습니다."
    } catch { Say "진행 상황 바로가기를 만들지 못했습니다: $($_.Exception.Message)" Yellow }
}

# Desktop shortcut for the Flow Chrome: its own profile (D:\guidejung\chrome-flow), kept rendering while minimized.
$flowShortcut = if ($desktop) { Join-Path $desktop 'Flow 영상 크롬.lnk' } else { $null }
$chromePath = @((Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe' -ErrorAction SilentlyContinue).'(default)',
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($flowShortcut -and -not $chromePath) { Say '크롬(chrome.exe)을 찾지 못해 Flow 크롬 바로가기를 만들지 못했습니다.' Yellow }
if ($flowShortcut -and $chromePath -and -not (Test-Path $flowShortcut)) {
    try {
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($flowShortcut)
        $lnk.TargetPath = $chromePath
        $lnk.Arguments = "--user-data-dir=`"$(Join-Path $base 'chrome-flow')`" --disable-renderer-backgrounding --disable-background-timer-throttling --disable-backgrounding-occluded-windows https://flow.google.com/"
        $lnk.Save()
        Say "바탕화면에 'Flow 영상 크롬' 바로가기를 만들었습니다."
    } catch { Say "Flow 크롬 바로가기를 만들지 못했습니다: $($_.Exception.Message)" Yellow }
}

if ($problems) { Say "=== 끝 (확인할 것 $problems 건, 위 노란색·빨간색 줄) ===" Yellow }
else { Say '=== 끝 (모두 정상) ===' Green }
