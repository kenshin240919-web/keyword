# guidejung 프로그램을 한 번에 켭니다. 이미 켜져 있는 것은 건너뜁니다.
#   D:\guidejung\전체실행.bat (또는 바탕화면 'guidejung 전체 실행')으로 실행합니다.
# 순서: Local → Blog Automator → autopost → shot → 블로그 크롬 4개 → Flow용 크롬 → 리포트 + 전체 진행 상황
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $PSScriptRoot

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Test-Port([int]$port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
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

Say '=== guidejung 전체 실행 ===' Cyan

# 1. Local (워드프레스)
if (Get-Process -Name 'Local' -ErrorAction SilentlyContinue) { Say '[Local] 이미 켜져 있음' }
else {
    $local = @("$env:LOCALAPPDATA\Programs\Local\Local.exe", "$env:ProgramFiles\Local\Local.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($local) { Start-Process -FilePath $local; Say '[Local] 켰습니다. 사이트가 멈춰 있으면 Local 화면에서 Start를 눌러 주세요.' Green }
    else { Say '[Local] 프로그램을 찾지 못했습니다. 직접 켜 주세요.' Yellow }
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
    Start-Process -FilePath 'python' -ArgumentList 'app.py', '--no-browser' -WorkingDirectory $dir -WindowStyle Minimized
    Say '[autopost] 켰습니다 (작업 표시줄에 최소화된 창 — 닫으면 꺼집니다).' Green
}

# 4. shot (8790) — without the Typecast (grandmother voice) key; asks only for the Gemini key if it is not set
if (Test-Port 8790) { Say '[shot] 이미 켜져 있음' }
else {
    $dir = Join-Path $base 'shot'
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $dir -WindowStyle Minimized `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $dir 'run_typecast.ps1'), '-NoTypecast'
    Say '[shot] 켰습니다 (작업 표시줄에 최소화 — 닫으면 꺼집니다. Gemini 키를 묻는 경우에만 창을 열어 입력).' Green
}

# 5. 블로그 크롬 1~4번 (바탕화면 바로가기, 전용 프로필 BlogAutomator\chrome\chrome-N)
$desktops = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'))
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

# 6. Flow용 크롬 (평소 쓰는 크롬, Google 로그인). The Shot Flow extension opens the Flow tab itself when work comes.
$mainChrome = $chromeLines | Where-Object { $_ -and $_ -notlike '*BlogAutomator\chrome*' -and $_ -notlike '*--type=*' }
if ($mainChrome) { Say '[Flow용 크롬] 이미 켜져 있음' }
elseif ($chrome) { Start-Process -FilePath $chrome -ArgumentList 'https://flow.google.com/'; Say '[Flow용 크롬] 켰습니다.' Green }
else { Say '[Flow용 크롬] 크롬을 찾지 못했습니다. 직접 켜 주세요.' Yellow }

# 7. 리포트 + 전체 진행 상황
Say '프로그램이 준비되기를 기다리는 중...'
$null = Wait-Port 37321 30
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'open_report.bat' -WorkingDirectory $PSScriptRoot -WindowStyle Minimized
if (Wait-Port 8765 60) { Start-Process 'http://127.0.0.1:8765/status'; Say '[전체 진행 상황] 열었습니다.' Green }
else { Say '[전체 진행 상황] 리포트 서버가 아직 안 켜졌습니다. 잠시 뒤 http://127.0.0.1:8765/status 를 열어 주세요.' Yellow }

Say '=== 끝 — 빨간 항목은 진행 상황 페이지에서 확인하세요. 이 창은 10초 뒤 닫힙니다. ===' Cyan
Start-Sleep 10
