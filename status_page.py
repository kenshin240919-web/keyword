"""전체 진행 상황: 리포트 서버(8765)의 /status 페이지와 /api/overview.

각 프로그램에 상태를 물어 한 화면에 모읍니다 (읽기만 함).
  - Blog Automator 허브 (37321): 블로그 1~4번 글 작성·임시저장, 블로그 크롬 4개 연결
  - shot (8790): Google Flow 영상 생성, 자막 완성, Flow 크롬 연결
  - autopost (8777): guidejung·gov 사이트 발행
  - 워드프레스(Local): autopost config.json의 로컬 주소에 접속되는지만 확인 (비밀번호는 읽지 않음)
"""
import json
import time
import urllib.error
import urllib.request

import daily_keywords as dk

BLOGAUTO = "http://127.0.0.1:37321"
SHOT = "http://127.0.0.1:8790"
AUTOPOST = "http://127.0.0.1:8777"
ALIVE_SECONDS = 150  # an extension polls every minute


def _get(url, headers=None, timeout=3):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _reachable(url):
    try:
        urllib.request.urlopen(url, timeout=2).close()
        return True
    except urllib.error.HTTPError:
        return True  # the server answered
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wordpress_sites():
    """Local addresses from autopost's config.json: {name: url}. Only the url field is used."""
    path = dk.BASE_DIR.parent / "move" / "autopost" / "config.json"
    try:
        sites = json.loads(path.read_text(encoding="utf-8"))
        return {name: cfg["url"] for name, cfg in sites.items() if isinstance(cfg, dict) and cfg.get("url")}
    except (OSError, ValueError):
        return {}


def overview():
    blog = _get(f"{BLOGAUTO}/api/status", {"X-Blogauto": "1"})
    flow = _get(f"{SHOT}/api/flow/status", {"X-Shot-Flow": "1"})
    flow_poll = _get(f"{SHOT}/api/flow/poll-info", {"X-Shot-Flow": "1"}) or {}
    shot_latest = _get(f"{SHOT}/api/blogauto-auto/latest")
    auto = _get(f"{AUTOPOST}/api/state")
    now = time.time()

    programs = [{"name": "키워드 리포트", "ok": True},
                {"name": "Blog Automator", "ok": blog is not None, "fix": "BlogAutomator\\실행.bat"},
                {"name": "autopost (사이트)", "ok": auto is not None, "fix": "move\\autopost\\start.bat"},
                {"name": "shot (영상)", "ok": flow is not None, "fix": "shot\\run_typecast.bat"}]
    for name, url in _wordpress_sites().items():
        programs.append({"name": f"워드프레스 {name}", "ok": _reachable(url), "fix": "Local에서 사이트 Start"})
    clients = (blog or {}).get("clients") or {}
    for n in range(1, 5):
        seen = [v for k, v in clients.items() if k.split("@")[0] == str(n)]
        last = max((_iso_to_epoch(v) for v in seen), default=None)
        programs.append({"name": f"블로그 크롬 {n}번", "ok": last is not None and now - last < ALIVE_SECONDS,
                         "fix": f"바탕화면 '블로그 {n}번' 바로가기"})
    last_flow = flow_poll.get("last_poll")
    programs.append({"name": "Flow 크롬", "ok": bool(last_flow) and now - last_flow < ALIVE_SECONDS,
                     "fix": "바탕화면 'Flow 영상 크롬' (Shot Flow 확장 · 자동 생성 켜기)"})

    # Latest keyword sent from the report: the newest Blog Automator jobs that carry ctaKeyword.
    jobs = [j for j in (blog or {}).get("jobs", []) if j.get("ctaKeyword")]
    keyword = jobs[0]["ctaKeyword"] if jobs else ""
    jobs = [j for j in jobs if j.get("ctaKeyword") == keyword]
    flows = {r.get("slot"): r for r in (flow or []) if r.get("keyword") == keyword}
    done = {r.get("slot"): r for r in (shot_latest or []) if r.get("keyword") == keyword}
    rows = []
    for n in range(1, 5):
        job = next((j for j in jobs if j.get("style") == n), None)
        st = (job or {}).get("styles", {}).get(str(n)) or {}
        f, d = flows.get(n) or {}, done.get(n) or {}
        rows.append({
            "blog": n, "keyword": (job or {}).get("keyword", ""),
            "write": _write_state(job),
            "video": _video_state(f, d, job),
            "naver": _naver_state(st, job),
        })
    site = None
    for j in (auto or {}).get("jobs", []):
        if keyword and j.get("keyword") == keyword:
            result = j.get("result") or {}
            site = {"state": j.get("state"), "links": [{"title": v.get("title", k), "url": v.get("public")}
                                                       for k, v in result.items() if isinstance(v, dict) and v.get("public")],
                    "last": (j.get("log") or [""])[-1] if j.get("log") else ""}
    return {"programs": programs, "keyword": keyword, "rows": rows, "site": site, "at": time.strftime("%H:%M:%S")}


def _iso_to_epoch(iso):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _write_state(job):
    if not job:
        return {"icon": "wait", "text": "-"}
    status = job.get("status")
    if status == "queued":
        return {"icon": "wait", "text": "대기"}
    if status == "generating":
        return {"icon": "run", "text": f"작성 중 {round(job.get('percent') or 0)}%"}
    if status == "failed":
        return {"icon": "err", "text": job.get("error") or "작성 실패"}
    return {"icon": "ok", "text": "완료"}


def _video_state(flow, done, job):
    if done.get("done"):
        return {"icon": "ok", "text": "완성 (자막·내레이션)"}
    status = flow.get("status")
    if status == "running":
        return {"icon": "run", "text": flow.get("step") or "Flow 생성 중"}
    if status == "done":
        return {"icon": "run", "text": "자막·내레이션 입히는 중"}
    if status == "error":
        return {"icon": "err", "text": flow.get("error") or "Flow 실패 (확장 패널에서 다시 시도)"}
    if status == "skipped":
        return {"icon": "ok", "text": "영상 없이 저장"}
    if job and job.get("status") == "ready":
        return {"icon": "wait", "text": "Flow 차례 기다리는 중"}
    return {"icon": "wait", "text": "-"}


def _naver_state(st, job):
    status = st.get("status")
    if status == "video":
        return {"icon": "wait", "text": "영상 기다리는 중"}
    if status == "pending":
        return {"icon": "wait", "text": "크롬 차례 기다리는 중"}
    if status == "running":
        return {"icon": "run", "text": f"{round(st.get('percent') or 0)}% · {st.get('step') or '저장 중'}"}
    if status == "saved":
        warn = st.get("warning")
        return {"icon": "warn" if warn else "ok", "text": f"임시저장 완료{' · ' + warn if warn else (' · 영상 포함' if job and job.get('video') else '')}"}
    if status == "error":
        return {"icon": "err", "text": st.get("message") or "오류"}
    return {"icon": "wait", "text": "-"}


STATUS_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>전체 진행 상황</title>
<style>
  :root { --ink:#1f2a37; --muted:#667085; --line:#e4e7ec; --ok:#12805c; --run:#1a73e8; --err:#c0392b; --warn:#b54708; --bg:#f6f7f9; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 'Malgun Gothic', sans-serif; color:var(--ink); background:var(--bg); }
  header { background:var(--ink); color:#fff; padding:14px 20px; display:flex; justify-content:space-between; align-items:center; }
  main { max-width:1100px; margin:0 auto; padding:16px; }
  section { background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:14px; }
  h2 { font-size:16px; margin:0 0 10px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; }
  .chip { padding:5px 10px; border-radius:16px; font-size:13px; background:#e9f6f0; color:var(--ok); }
  .chip.off { background:#fdecea; color:var(--err); }
  .chip small { color:var(--muted); margin-left:4px; }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:10px 8px; border-top:1px solid var(--line); vertical-align:top; font-size:14px; }
  th { color:var(--muted); font-weight:normal; border-top:0; }
  .ok { color:var(--ok); } .run { color:var(--run); } .err { color:var(--err); } .warn { color:var(--warn); } .wait { color:var(--muted); }
  .note { color:var(--muted); font-size:13px; }
  a { color:var(--run); }
  @media (max-width: 700px) { th:nth-child(2), td:nth-child(2) { display:none; } }
</style></head>
<body>
<header><b>전체 진행 상황</b><span id="at" class="note" style="color:#cbd5e1"></span></header>
<main>
  <section><h2>프로그램</h2><div class="chips" id="programs"></div>
    <p class="note">빨간 항목은 꺼져 있거나 연결되지 않은 것입니다. 이름 옆 안내대로 켜 주세요.</p></section>
  <section><h2 id="title">진행 중인 키워드 없음</h2>
    <table><thead><tr><th>블로그</th><th>키워드</th><th>① 글 작성</th><th>② 숏폼 영상</th><th>③ 네이버 임시저장</th></tr></thead><tbody id="rows"></tbody></table></section>
  <section><h2>사이트 발행 (guidejung · gov)</h2><div id="site" class="note">-</div></section>
  <p class="note">3초마다 자동으로 새로 고칩니다. 리포트: <a href="/">오늘 리포트 열기</a></p>
</main>
<script>
const ICON = { ok: '✅', run: '⏳', err: '❌', warn: '⚠️', wait: '·' };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const cell = s => `<td class="${s.icon}">${ICON[s.icon] || ''} ${esc(s.text)}</td>`;
async function refresh() {
  try {
    const d = await (await fetch('/api/overview', { cache: 'no-store' })).json();
    document.getElementById('at').textContent = d.at + ' 기준';
    document.getElementById('programs').innerHTML = d.programs.map(p =>
      `<span class="chip ${p.ok ? '' : 'off'}">${p.ok ? '●' : '○'} ${esc(p.name)}${p.ok || !p.fix ? '' : `<small>→ ${esc(p.fix)}</small>`}</span>`).join('');
    document.getElementById('title').textContent = d.keyword ? `키워드: ${d.keyword}` : '진행 중인 키워드 없음 (리포트에서 블로그 4곳에 보내기)';
    document.getElementById('rows').innerHTML = d.rows.map(r =>
      `<tr><td><b>${r.blog}번</b></td><td>${esc(r.keyword)}</td>${cell(r.write)}${cell(r.video)}${cell(r.naver)}</tr>`).join('');
    const s = d.site;
    document.getElementById('site').innerHTML = !s ? '이 키워드의 사이트 작업 없음' :
      `<span class="${s.state === '완료' ? 'ok' : s.state === '실패' ? 'err' : 'run'}">${esc(s.state)}</span>
       ${s.links.map(l => ` · <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a>`).join('')}
       ${s.state !== '완료' && s.last ? `<div class="note">${esc(s.last)}</div>` : ''}`;
  } catch (e) {
    document.getElementById('at').textContent = '상태를 읽지 못했습니다';
  }
}
refresh(); setInterval(refresh, 3000);
</script>
</body></html>
"""
