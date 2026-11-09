# guidejung 프로그램을 한 번에 켭니다. 이미 켜져 있는 것은 건너뜁니다.
#   바탕화면 'guidejung 시작' (= D:\guidejung\전체실행.bat)으로 실행합니다.
# 순서: guidejung 홈(브라우저 탭 1개) → Local → Blog Automator → autopost → shot → 블로그 크롬 4개 → Flow용 크롬
#       → 오늘 키워드 뽑기(창 없이, 결과는 홈의 '오늘 키워드' 탭에)
# 프로그램 창은 띄우지 않고 뒤에서 돌립니다. 끌 때는 바탕화면 'guidejung 끄기' (2026-11-06).
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $PSScriptRoot

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Get-ListenPid([int]$port) {
    $found = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
    if ($found) { return $found }
    # Get-NetTCPConnection found nothing on this PC while the programs were running (2026-11-09): netstat as a second way.
    foreach ($line in (netstat -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$port\s+\S+\s+(?:LISTENING|수신 대기)\s+(\d+)") { return [int]$Matches[1] }
    }
    return $null
}
function Test-Port([int]$port) { [bool](Get-ListenPid $port) }
function Wait-Port([int]$port, [int]$seconds) {
    for ($i = 0; $i -lt $seconds -and -not (Test-Port $port); $i++) { Start-Sleep 1 }
    Test-Port $port
}
function Chrome-Exe {
    $reg = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe' -ErrorAction SilentlyContinue).'(default)'
    foreach ($p in @($reg, "$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}
$chromeLines = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | ForEach-Object { $_.CommandLine })

Say '=== guidejung 시작 ===' Cyan

# 0. guidejung 홈 (리포트 서버 8765): 모든 화면이 이 탭 하나에. 이미 열려 있으면 새 탭을 열지 않습니다.
Push-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
& python report_server.py --home
Pop-Location
Say '[guidejung 홈] 브라우저에 열었습니다. 나머지 프로그램이 켜지는 동안 진행 상황 탭에서 초록색으로 바뀝니다.' Green

# 1. Local (워드프레스)
if (Get-Process -Name 'Local' -ErrorAction SilentlyContinue) { Say '[Local] 이미 켜져 있음' }
else {
    $local = @("$env:LOCALAPPDATA\Programs\Local\Local.exe", "$env:ProgramFiles\Local\Local.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($local) { Start-Process -FilePath $local; Say '[Local] 켰습니다. 사이트가 멈춰 있으면 Local 화면에서 Start를 눌러 주세요.' Green }
    else { Say '[Local] 프로그램을 찾지 못했습니다. 직접 켜 주세요.' Yellow }
}
# Local 사이트들을 새로 시작 (오래 켜 두면 응답이 멈춰 배포가 걸리던 문제 예방, 2026-10-28).
# move\local_sites.py가 있을 때만 (PC에서 만든 도우미: Local이 켜질 때까지 기다린 뒤 사이트를 Stop → Start).
$sites = Join-Path $base 'move\local_sites.py'
if (Test-Path $sites) {
    Say '[Local] 사이트를 다시 시작하는 중 (1분 정도)...'
    & python $sites restart-all
    if ($LASTEXITCODE -eq 0) { Say '[Local] 사이트 다시 시작 완료' Green } else { Say '[Local] 사이트 다시 시작 실패: Local 화면에서 Start를 눌러 주세요.' Yellow }
}

# 2. Blog Automator (37321)
if (Test-Port 37321) { Say '[Blog Automator] 이미 켜져 있음' }
else {
    $dir = Join-Path $base 'BlogAutomator'
    Start-Process -FilePath (Join-Path $dir '실행.bat') -WorkingDirectory $dir -WindowStyle Hidden
    Say '[Blog Automator] 켰습니다 (트레이).' Green
}

# 3. autopost (8777)
if (Test-Port 8777) { Say '[autopost] 이미 켜져 있음' }
else {
    $dir = Join-Path $base 'move\autopost'
    Start-Process -FilePath 'python' -ArgumentList 'app.py', '--no-browser' -WorkingDirectory $dir -WindowStyle Hidden
    Say '[autopost] 켰습니다 (창 없이 — 화면은 홈의 사이트 글 탭).' Green
}

# 4. shot (8790) — without the Typecast (grandmother voice) key; narration is the Flow video's own voice, no key needed
if (Test-Port 8790) { Say '[shot] 이미 켜져 있음' }
else {
    $dir = Join-Path $base 'shot'
    $env:SHOT_NO_BROWSER = '1'  # its screen is the home page's 영상 tab, not a tab of its own
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $dir -WindowStyle Hidden `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $dir 'run_typecast.ps1'), '-NoTypecast'
    Remove-Item Env:SHOT_NO_BROWSER -ErrorAction SilentlyContinue
    Say '[shot] 켰습니다 (창 없이 — 화면은 홈의 영상 탭).' Green
}

# 5. 블로그 크롬 1~4번 (바로가기: D:\guidejung\바로가기 또는 바탕화면, 전용 프로필 BlogAutomator\chrome\chrome-N)
$desktops = @((Join-Path $base '바로가기'), [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'))
$chrome = Chrome-Exe
foreach ($n in 1..4) {
    $profileDir = Join-Path $base "BlogAutomator\chrome\chrome-$n"
    if ($chromeLines | Where-Object { $_ -and $_ -like "*chrome-$n*" }) { Say "[블로그 크롬 $n번] 이미 켜져 있음"; continue }
    $lnk = $desktops | ForEach-Object { Get-ChildItem -Path $_ -Filter "블로그 ${n}번*.lnk" -ErrorAction SilentlyContinue } | Select-Object -First 1
    if ($lnk) { Start-Process -FilePath $lnk.FullName -WindowStyle Minimized; Say "[블로그 크롬 $n번] 켰습니다 ($($lnk.BaseName))." Green }
    elseif ($chrome -and (Test-Path $profileDir)) {
        Start-Process -FilePath $chrome -WindowStyle Minimized -ArgumentList "--user-data-dir=`"$profileDir`"", '--disable-renderer-backgrounding',
            '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', 'https://blog.naver.com/'
        Say "[블로그 크롬 $n번] 켰습니다 (전용 프로필)." Green
    }
    else { Say "[블로그 크롬 $n번] 바로가기를 찾지 못했습니다. 직접 켜 주세요." Yellow }
    Start-Sleep 2
}

# 6. Flow 전용 크롬 (D:\guidejung\chrome-flow 프로필: Google 로그인 + Shot Flow 확장). The extension opens
#    the Flow tab itself when work comes; the desktop shortcut 'Flow 영상 크롬' is made by 업데이트.bat.
$flowProfile = Join-Path $base 'chrome-flow'
if ($chromeLines | Where-Object { $_ -and $_ -like '*chrome-flow*' }) { Say '[Flow 전용 크롬] 이미 켜져 있음' }
elseif ($chrome) {
    Start-Process -FilePath $chrome -WindowStyle Minimized -ArgumentList "--user-data-dir=`"$flowProfile`"", '--disable-renderer-backgrounding',
        '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', 'https://flow.google.com/'
    Say '[Flow 전용 크롬] 켰습니다 (최소화).' Green
}
else { Say '[Flow 전용 크롬] 크롬을 찾지 못했습니다. 직접 켜 주세요.' Yellow }

# 7. 오늘 키워드 뽑기: 창 없이 돌고, 결과는 홈의 '오늘 키워드' 탭에 나옵니다 (오늘 이미 했으면 바로 끝).
$env:GUIDEJUNG_NO_BROWSER = '1'
Start-Process -FilePath 'cmd.exe' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
    -ArgumentList '/c', 'if not exist logs mkdir logs & python daily_keywords.py --skip-if-done >> logs\daily.log 2>&1'
Remove-Item Env:GUIDEJUNG_NO_BROWSER -ErrorAction SilentlyContinue
Say '[오늘 키워드] 뽑는 중 (창 없이 — 홈의 오늘 키워드 탭에 나옵니다)' Green

Say '=== 끝 — 이제 브라우저의 guidejung 탭만 보시면 됩니다. 이 창은 5초 뒤 닫힙니다. ===' Cyan
Start-Sleep 5
