"""직접 뽑기 페이지 (http://127.0.0.1:8765/custom): 씨앗 키워드와 기간을 골라 추천 키워드를 따로 뽑습니다.

결과는 reports\\직접뽑기\\날짜_시각_첫씨앗.html·.csv로 저장되고, 매일 리포트(reports\\날짜.html)·seeds.txt·
추천 기록은 건드리지 않습니다. 한 번에 하나만 돌고, 진행 줄은 daily_keywords.LOG_SINK로 받습니다.
"""
import re
import threading
from datetime import date, timedelta

import daily_keywords as dk

job = {"running": False, "log": [], "name": "", "error": "", "seeds": [], "period": []}
lock = threading.Lock()
FIRST_DAY = date(2016, 1, 1)  # 데이터랩 추이가 있는 첫날


def presets(today=None):
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    season = dk.season_window(today, dk.load_config()["season_months_ahead"])
    last_year = dk.add_months(today, -12)
    pairs = [("작년 이맘때 다음 한 달 (매일 리포트 기준)", season),
             ("작년 이맘때 한 달", (last_year, dk.add_months(last_year, 1))),
             ("작년 이맘때부터 3개월", (last_year, dk.add_months(last_year, 3))),
             ("최근 한 달", (yesterday - timedelta(days=30), yesterday))]
    return [{"label": label, "start": a.isoformat(), "end": b.isoformat()} for label, (a, b) in pairs]


def history(limit=20):
    folder = dk.REPORT_DIR / "직접뽑기"
    files = sorted(folder.glob("*.html"), reverse=True)[:limit] if folder.exists() else []
    return [{"name": f.stem, "label": f.stem.replace("_", " ", 2)} for f in files]


def state():
    with lock:
        return {**job, "log": job["log"][-200:], "history": history(), "presets": presets()}


def start(body):
    """{seeds: "a, b", start: "YYYY-MM-DD", end: "YYYY-MM-DD"} → 백그라운드로 뽑기 시작. 잘못되면 ValueError."""
    seeds = [s.strip() for s in re.split(r"[,\n]", str(body.get("seeds") or "")) if s.strip()]
    if not seeds:
        raise ValueError("씨앗 키워드를 하나 이상 입력해 주세요.")
    if len(seeds) > 20 or any(len(s) > 30 for s in seeds):
        raise ValueError("씨앗 키워드는 20개까지, 하나에 30자까지입니다.")
    try:
        a, b = date.fromisoformat(str(body.get("start"))), date.fromisoformat(str(body.get("end")))
    except ValueError:
        raise ValueError("기간의 시작일과 종료일을 골라 주세요.")
    yesterday = date.today() - timedelta(days=1)
    if not FIRST_DAY <= a < b <= yesterday:
        raise ValueError(f"기간은 {FIRST_DAY} 이후, 어제({yesterday})까지이고 시작일이 종료일보다 앞이어야 합니다.")
    if (b - a).days > 366:
        raise ValueError("기간은 1년 이내로 골라 주세요.")
    with lock:
        if job["running"]:
            raise ValueError("이미 뽑는 중입니다. 끝난 뒤 다시 눌러 주세요.")
        job.update(running=True, log=[], name="", error="", seeds=seeds, period=[a.isoformat(), b.isoformat()])
    threading.Thread(target=_run, args=(seeds, a, b), daemon=True).start()


def _run(seeds, a, b):
    dk.LOG_SINK = lambda line: job["log"].append(line)
    try:
        name = dk.run(seeds=seeds, period=(a, b), open_browser=False)
        with lock:
            job["name"] = name or ""
    except SystemExit as e:  # daily_keywords stops with sys.exit("[오류] ...") when nothing fits
        with lock:
            job["error"] = str(e) or "뽑기를 멈췄습니다."
    except Exception as e:
        with lock:
            job["error"] = f"{type(e).__name__}: {e}"
    finally:
        dk.LOG_SINK = None
        with lock:
            job["running"] = False


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>키워드 직접 뽑기</title>
<style>
  :root { --ink:#1f2a37; --muted:#667085; --line:#d9e2f1; --blue:#2b6cb0; --bg:#f3f6ff; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.55 'Malgun Gothic', sans-serif; color:var(--ink); background:var(--bg); }
  header { background:#1e4e8c; color:#fff; padding:14px 20px; display:flex; justify-content:space-between; align-items:center; }
  header a { color:#cfe0ff; font-size:13px; }
  main { max-width:860px; margin:0 auto; padding:18px 16px 40px; }
  section { background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin-bottom:14px; }
  h2 { font-size:16px; margin:0 0 10px; }
  textarea, input[type=date] { font:inherit; border:1px solid var(--line); border-radius:8px; padding:8px 10px; }
  textarea { width:100%; min-height:80px; resize:vertical; }
  .note { color:var(--muted); font-size:13px; margin:6px 0 0; }
  .presets { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:10px; }
  .presets button { font:inherit; font-size:13px; border:1px solid var(--blue); color:var(--blue); background:#fff; border-radius:16px; padding:4px 12px; cursor:pointer; }
  .presets button.on { background:var(--blue); color:#fff; }
  .dates { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .go { font:inherit; font-weight:700; background:var(--blue); color:#fff; border:0; border-radius:10px; padding:12px 22px; cursor:pointer; }
  .go:disabled { background:#9db6d8; cursor:default; }
  #log { background:#0f172a; color:#d1e3ff; font:12.5px/1.6 Consolas, monospace; border-radius:8px; padding:10px 12px; max-height:260px; overflow:auto; white-space:pre-wrap; }
  .err { color:#c0392b; font-weight:700; }
  ul { margin:0; padding-left:18px; } li { margin:3px 0; }
  a { color:var(--blue); }
</style></head>
<body>
<header><b>키워드 직접 뽑기</b><span><a href="/" target="_blank">매일 리포트</a> · <a href="/status" target="_blank">전체 진행 상황</a></span></header>
<main>
  <section><h2>1. 씨앗 키워드</h2>
    <textarea id="seeds" placeholder="예: 청년지원금, 전세대출, 실업급여"></textarea>
    <p class="note">쉼표나 줄바꿈으로 구분 (20개까지). 이 단어들의 연관 키워드 중에서 검색은 많고 경쟁 글은 적은 키워드를 찾습니다.</p></section>
  <section><h2>2. 기준 기간</h2>
    <div class="presets" id="presets"></div>
    <div class="dates"><input type="date" id="start"> ~ <input type="date" id="end"></div>
    <p class="note">이 기간의 검색량(한 달 기준으로 환산한 추정값)으로 키워드를 고릅니다. 예: 내년 1월에 쓸 글이면 작년 1월을 고르세요. 2016년 이후, 어제까지, 1년 이내.</p></section>
  <section><button class="go" id="go">키워드 뽑기</button> <span id="msg" class="note"></span>
    <div id="logBox" hidden><p class="note">진행 상황 (몇 분 걸립니다. 끝나면 결과 페이지로 넘어갑니다)</p><div id="log"></div></div></section>
  <section><h2>지난 직접 뽑기 결과</h2><ul id="history"><li class="note">아직 없습니다.</li></ul>
    <p class="note">결과는 매일 리포트와 따로 저장되고(key\reports\직접뽑기), 블로그 4곳 보내기·오늘 썼어요 기록과도 섞이지 않습니다. 결과 페이지에는 키워드 복사 버튼만 있습니다.</p></section>
</main>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const resultUrl = name => '/reports/' + encodeURIComponent('직접뽑기/' + name + '.html');
let wasRunning = false, presetsDrawn = false;
async function refresh() {
  const d = await (await fetch('/api/custom', { cache: 'no-store' })).json();
  if (!presetsDrawn) {
    presetsDrawn = true; presetList = d.presets;
    $('presets').innerHTML = d.presets.map((p, i) => `<button type="button" data-i="${i}">${esc(p.label)}</button>`).join('');
    $('presets').onclick = e => { const p = d.presets[e.target.dataset.i]; if (!p) return; $('start').value = p.start; $('end').value = p.end; mark(); };
    const p = d.presets[0]; $('start').value = p.start; $('end').value = p.end; mark();
    if (d.running) { $('seeds').value = d.seeds.join(', '); $('start').value = d.period[0]; $('end').value = d.period[1]; }
  }
  $('history').innerHTML = d.history.length ? d.history.map(h => `<li><a href="${resultUrl(h.name)}" target="_blank">${esc(h.label)}</a></li>`).join('') : '<li class="note">아직 없습니다.</li>';
  $('go').disabled = d.running;
  if (d.running || d.log.length) { $('logBox').hidden = false; $('log').textContent = d.log.join('\n'); $('log').scrollTop = 1e9; }
  if (d.running) $('msg').textContent = '뽑는 중…';
  else if (wasRunning && d.name) { $('msg').textContent = '완료! 결과 페이지로 넘어갑니다.'; location.href = resultUrl(d.name); }
  else if (wasRunning && d.error) $('msg').innerHTML = `<span class="err">${esc(d.error)}</span>`;
  wasRunning = d.running;
}
let presetList = [];
function mark() {  // the preset that matches the chosen dates is shown pressed
  [...$('presets').children].forEach((b, i) => b.classList.toggle('on', presetList[i] && presetList[i].start === $('start').value && presetList[i].end === $('end').value));
}
$('start').onchange = $('end').onchange = () => mark();
$('go').onclick = async () => {
  $('msg').textContent = '';
  try {
    const r = await fetch('/api/custom', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Report-App': '1' },
      body: JSON.stringify({ seeds: $('seeds').value, start: $('start').value, end: $('end').value }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    wasRunning = true; refresh();
  } catch (err) { $('msg').innerHTML = `<span class="err">${esc(err.message)}</span>`; }
};
refresh(); setInterval(() => refresh().catch(() => { $('msg').textContent = '리포트 서버에 연결하지 못했습니다.'; }), 2000);
</script>
</body></html>
"""
