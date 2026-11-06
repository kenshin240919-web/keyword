"""guidejung 홈: 리포트 서버(8765)의 /home 한 페이지에서 모든 화면을 탭으로 봅니다.

오늘 키워드(리포트) · 진행 상황 · 영상(shot 8790) · 사이트 글(autopost 8777)을 한 탭 안에 넣어,
브라우저 탭과 프로그램 창을 여러 개 띄우지 않게 합니다 (2026-11-06, "창과 탭이 너무 많다").
각 프로그램은 그대로 따로 돌고, 이 페이지는 그 화면을 iframe으로 보여 주기만 합니다.
"""

HOME_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>guidejung</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --bg:#f5f6f8; --card:#fff; --ink:#1d2433; --muted:#667085; --line:#e4e7ec; --accent:#2b6cb0; --top:#1e2a3a; }
* { box-sizing: border-box; }
html, body { margin:0; height:100%; background:var(--bg); color:var(--ink); font-family:'Malgun Gothic','맑은 고딕',system-ui,sans-serif; }
body { display:flex; flex-direction:column; }
header { background:var(--top); color:#fff; display:flex; align-items:center; gap:6px; padding:0 16px; flex-wrap:wrap; }
header h1 { font-size:18px; margin:0 18px 0 0; padding:12px 0; letter-spacing:.5px; }
nav { display:flex; gap:4px; flex-wrap:wrap; }
nav button { background:transparent; color:#cfd6e1; border:0; border-bottom:3px solid transparent; padding:13px 14px 10px; font:inherit; font-size:15px; cursor:pointer; }
nav button:hover { color:#fff; }
nav button.on { color:#fff; border-bottom-color:#5ab0ff; font-weight:bold; }
nav button small { display:block; font-size:11px; color:#8fa0b5; font-weight:normal; }
.steps { background:#fff; border-bottom:1px solid var(--line); padding:10px 16px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; font-size:14px; }
.steps b { color:var(--accent); }
.step { background:#f0f5fb; border:1px solid #d6e4f5; border-radius:8px; padding:6px 10px; cursor:pointer; }
.step:hover { background:#e3eefa; }
.arrow { color:var(--muted); }
main { flex:1; position:relative; min-height:0; }
iframe, .pane { position:absolute; inset:0; width:100%; height:100%; border:0; background:var(--bg); }
.pane { overflow:auto; padding:28px 16px; }
.box { max-width:760px; margin:0 auto; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:22px 24px; line-height:1.7; }
.box h2 { margin:0 0 10px; font-size:19px; }
.box button { font:inherit; padding:6px 14px; border-radius:8px; border:1px solid #2b6cb0; background:#2b6cb0; color:#fff; cursor:pointer; margin-right:10px; }
.box pre { background:#f7f8fa; border:1px solid var(--line); border-radius:8px; padding:10px; font-size:12px; white-space:pre-wrap; max-height:260px; overflow:auto; }
.box table { border-collapse:collapse; width:100%; font-size:14px; }
.box td { border-top:1px solid var(--line); padding:8px 6px; vertical-align:top; }
.box td:first-child { white-space:nowrap; font-weight:bold; width:120px; }
.off { color:#b42318; font-weight:bold; }
</style></head>
<body>
<header>
  <h1>guidejung</h1>
  <nav id="tabs">
    <button data-tab="report">① 오늘 키워드<small>고르고 보내기</small></button>
    <button data-tab="status">② 진행 상황<small>기다리기·빨간 칸 처리</small></button>
    <button data-tab="shot">영상<small>필요할 때만</small></button>
    <button data-tab="autopost">사이트 글<small>필요할 때만</small></button>
    <button data-tab="help">도움말<small>무엇을 누르나</small></button>
  </nav>
</header>
<div class="steps">
  <span class="step" data-go="report"><b>①</b> 오늘 키워드에서 키워드를 고르고 <b>[블로그 4곳 보내기]</b></span><span class="arrow">→</span>
  <span class="step" data-go="status"><b>②</b> 진행 상황에서 기다리기 (빨간 칸만 옆 버튼 누르기)</span><span class="arrow">→</span>
  <span class="step" data-go="help"><b>③</b> 네이버 임시저장 글을 확인하고 <b>직접 발행</b></span>
</div>
<main id="main"></main>
<script>
const SHOT = 'http://127.0.0.1:8790/', AUTOPOST = 'http://127.0.0.1:8777/';
const panes = {};
const main = document.getElementById('main');

function box(html) { const d = document.createElement('div'); d.className = 'pane'; d.innerHTML = '<div class="box">' + html + '</div>'; return d; }
function frame(src) { const f = document.createElement('iframe'); f.src = src; return f; }
// A program's own screen, or a note when it is off (a no-cors request fails only when nothing answers).
async function programPane(name, url, what) {
  try { await fetch(url, { mode: 'no-cors', cache: 'no-store' }); return frame(url); }
  catch { const p = box('<h2>' + name + '</h2><p class="off">' + name + ' 프로그램이 꺼져 있습니다.</p><p>바탕화면의 <b>guidejung 시작</b>을 누르면 켜집니다.</p><p style="color:#667085">' + what + '</p>'); p.dataset.off = '1'; return p; }
}
const HELP = `<h2>무엇을 누르면 되나요?</h2>
<table>
<tr><td>매일 하는 일</td><td><b>①</b> <b>오늘 키워드</b> 탭에서 키워드를 고르고 <b>[블로그 4곳 보내기]</b>를 누릅니다.<br>
<b>②</b> 자동으로 <b>진행 상황</b> 탭으로 넘어갑니다. 글 작성 → 영상 → QR → 네이버 임시저장이 차례로 초록색이 되면 끝입니다.<br>
<b>③</b> 각 네이버 블로그의 <b>임시저장</b> 글을 열어 확인하고 직접 <b>발행</b>합니다. (발행은 프로그램이 하지 않습니다.)</td></tr>
<tr><td>빨간 칸이 생기면</td><td>진행 상황 탭의 그 줄 옆 버튼(<b>다시 시도</b>·<b>다시 시작</b>·<b>배포 다시</b> 등)을 누릅니다. 이유도 그 칸에 적혀 있습니다.</td></tr>
<tr><td>영상 · 사이트 글 탭</td><td>평소에는 볼 필요가 없습니다. 진행 상황에서 영상이나 사이트 글을 직접 확인하라고 할 때만 엽니다.</td></tr>
<tr><td>바탕화면 아이콘</td><td><b>guidejung 시작</b>: 모든 프로그램을 켜고 이 화면을 엽니다 (이미 켜져 있으면 이 화면만).<br>
<b>guidejung 업데이트</b>: 고친 프로그램을 받습니다.<br>
<b>guidejung 끄기</b>: 모든 프로그램을 끕니다 (Local은 그대로).<br>
블로그 크롬·Flow 크롬 바로가기는 <b>D:\\\\guidejung\\\\바로가기</b> 폴더로 옮겼습니다.</td></tr>
<tr><td>작업 표시줄의 크롬 창</td><td>블로그 크롬 4개와 Flow 크롬 1개는 글과 영상을 넣는 데 필요해서 최소화된 채로 켜 둡니다. 닫지 마세요.</td></tr>
</table>`;

let autoMade = false;
async function reportPane() {
  const d = await fetch('/api/today', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}));
  if (d.report) return frame('/reports/' + encodeURIComponent(d.report));
  const p = box('<div id="todaybox"></div>');
  const render = n => {
    const older = n.latest ? ' <a href="/reports/' + encodeURIComponent(n.latest) + '" target="_blank">지난 리포트 보기 (' + esc(n.latest.replace('.html', '')) + ')</a>' : '';
    p.querySelector('#todaybox').innerHTML = n.running
      ? '<h2>오늘 키워드를 뽑는 중입니다</h2><p>몇 분 걸립니다. 다 되면 이 탭에 저절로 나옵니다. 아래 기록이 계속 늘어나면 진행 중입니다.</p><pre>' + esc(n.log || '') + '</pre>'
      : '<h2>오늘 키워드가 아직 없습니다</h2><p>지금 뽑고 있지도 않습니다. <button id="make">지금 뽑기</button>' + older + '</p><p style="color:#667085">몇 분 걸리고, 다 되면 이 탭에 저절로 나옵니다.</p><pre>' + esc(n.log || '') + '</pre>';
    const b = p.querySelector('#make');
    if (b) b.onclick = make;
  };
  const make = async () => {
    await fetch('/api/make-today', { method: 'POST', headers: { 'X-Report-App': '1', 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
    setTimeout(tick, 1500);
  };
  const tick = async () => {
    const n = await fetch('/api/today', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}));
    if (n.report) { clearInterval(timer); delete panes.report; p.remove(); if (current === 'report') show('report'); return; }
    render(n);
  };
  render(d);
  // Nothing running and no report (e.g. this tab stayed open past midnight): start it once by itself.
  if (!d.running && !autoMade) { autoMade = true; make(); }
  const timer = setInterval(tick, 5000);
  return p;
}
function esc(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]); }

let current = null;
async function show(tab) {
  if (!['report', 'status', 'shot', 'autopost', 'help'].includes(tab)) tab = 'status';
  current = tab;
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  if (location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
  if (panes[tab]?.dataset.off) { panes[tab].remove(); delete panes[tab]; }  // was off: look again (it may be on now)
  if (!panes[tab]) {
    panes[tab] = tab === 'report' ? await reportPane() : tab === 'status' ? frame('/status')
      : tab === 'shot' ? await programPane('영상(shot)', SHOT, '숏폼 영상을 만드는 프로그램입니다.')
      : tab === 'autopost' ? await programPane('사이트 글(autopost)', AUTOPOST, 'guidejung·gov 워드프레스 글을 쓰고 배포하는 프로그램입니다.')
      : box(HELP);
    main.appendChild(panes[tab]);
  }
  Object.entries(panes).forEach(([k, el]) => { el.style.display = k === tab ? '' : 'none'; });
}
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => show(b.dataset.tab));
document.querySelectorAll('.step').forEach(s => s.onclick = () => show(s.dataset.go));
// Pages inside (report, status) switch tabs by changing this page's address: /home#status.
window.addEventListener('hashchange', () => show(location.hash.slice(1)));

// Tells the report server this page is open, so 'guidejung 시작' does not open a second tab.
const ping = () => fetch('/api/home-ping', { cache: 'no-store' }).catch(() => {});
ping(); setInterval(ping, 10000);

(async () => {
  let tab = location.hash.slice(1);
  if (!tab) {  // keywords not sent yet today → ① 오늘 키워드, otherwise ② 진행 상황
    const d = await fetch('/api/today').then(r => r.json()).catch(() => ({}));
    tab = d.sent_today ? 'status' : 'report';
  }
  show(tab);
})();
</script>
</body></html>
"""
