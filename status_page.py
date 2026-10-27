"""전체 진행 상황: 리포트 서버(8765)의 /status 페이지와 /api/overview.

각 프로그램에 상태를 물어 한 화면에 모읍니다 (읽기만 함).
  - Blog Automator 허브 (37321): 블로그 1~4번 글 작성·임시저장, 블로그 크롬 4개 연결
  - shot (8790): Google Flow 영상 생성, 자막 완성, Flow 크롬 연결
  - autopost (8777): guidejung·gov 사이트 발행
  - 워드프레스(Local): autopost config.json의 로컬 주소(포트)에 접속되는지만 확인 (비밀번호는 읽지 않음)
"""
import json
import socket
import time
import urllib.error
import urllib.parse
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
    """Whether the site's port takes a connection. Loading the page itself took Local's WordPress
    longer than the check could wait, so running sites showed as off."""
    parts = urllib.parse.urlsplit(url)
    try:
        socket.create_connection((parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)), timeout=2).close()
        return True
    except (OSError, ValueError):
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
            "blog": n, "job": (job or {}).get("id", ""), "keyword": (job or {}).get("keyword", ""), "actions": _actions(job, st, f),
            "write": _write_state(job),
            "video": _video_state(f, d, job),
            "link": _link_state(job, (blog or {}).get("qrTasks") or [], (blog or {}).get("config", {}).get("qrBlog") or 1,
                                (blog or {}).get("qrCheck")),
            "naver": _naver_state(st, job),
        })
    site = None
    # Which WordPress site each post went to: match its address to autopost's site list {name: public url}.
    publics = sorted(((name, str(url).rstrip("/")) for name, url in ((auto or {}).get("sites") or {}).items() if url),
                     key=lambda x: -len(x[1]))  # gov.guidejung.com before guidejung.com
    def site_name(url):
        host = str(url).split("//")[-1]
        return next((name for name, pub in publics if host.startswith(pub.split("//")[-1])), "")
    for j in (auto or {}).get("jobs", []):
        if keyword and j.get("keyword") == keyword:
            result = j.get("result") or {}
            site = {"state": j.get("state"),
                    "links": [{"site": site_name(v.get("public")), "title": v.get("title", k), "url": v.get("public")}
                              for k, v in sorted(result.items()) if isinstance(v, dict) and v.get("public")],
                    "last": (j.get("log") or [""])[-1] if j.get("log") else ""}
    qr = next((j["link"] for j in jobs if "site.naver.com" in str(j.get("link") or "")), "")
    if site is not None and qr:
        site["qr"] = qr
    return {"programs": programs, "keyword": keyword, "rows": rows, "site": site,
            "qr_alerts": _qr_alerts((blog or {}).get("jobs", [])), "at": time.strftime("%H:%M:%S")}


QR_ALERT_SINCE = "2026-10-27"  # older posts were made before the QR check existed


def _qr_alerts(jobs):
    """Posts (any recent keyword, not just the current one) whose yellow box got the gov address instead of
    the Naver QR short link: shown at the top of the page until 다시 시작 gives them a QR link."""
    out = []
    for j in jobs:
        link = str(j.get("link") or "")
        if (not j.get("ctaKeyword") or j.get("waitLink") or not link or any(q in link for q in IS_QR)
                or str(j.get("createdAt") or "") < QR_ALERT_SINCE):
            continue
        st = (j.get("styles") or {}).get(str(j.get("style"))) or {}
        when = _iso_to_epoch(st.get("finishedAt") or j.get("createdAt"))
        out.append({"id": f"{j['id']}|{link}", "blog": j.get("style"), "keyword": j.get("keyword") or j.get("ctaKeyword"),
                    "when": time.strftime("%m/%d %H:%M", time.localtime(when)) if when else "",
                    "state": "임시저장됨" if st.get("status") == "saved" else "저장 전",
                    "note": j.get("linkNote") or "QR 대신 gov 주소가 링크됨", "link": link,
                    "action": None if st.get("status") == "running" else
                    {"label": "QR 만들고 다시 시작", "act": "restart", "job": j["id"], "style": j.get("style"), "confirm": True}})
    return out


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
        return {"icon": "warn" if job.get("retryAt") else "wait", "text": job.get("progress") if job.get("retryAt") else "대기"}
    if status == "generating":
        return {"icon": "run", "text": f"작성 중 {round(job.get('percent') or 0)}%"}
    if status == "failed":
        return {"icon": "err", "text": str(job.get("error") or "작성 실패").split(' {"')[0][:300]}
    return {"icon": "ok", "text": "완료"}


IS_QR = ("site.naver.com", "naver.me")


def _actions(job, st, flow):
    """Buttons for this blog's row: {column: [{label, act, ...}]} (handled by POST /api/action)."""
    if not job:
        return {}
    out = {"write": [], "video": [], "naver": []}
    if job.get("status") == "failed":
        out["write"].append({"label": "다시 쓰기", "act": "rewrite", "job": job["id"]})
    if flow.get("status") == "error" and flow.get("pid"):
        out["video"].append({"label": "영상 다시 만들기", "act": "flow_retry", "pid": flow["pid"]})
    status = st.get("status")
    if status == "video":
        out["video"].append({"label": "영상 없이 저장", "act": "skip_video", "job": job["id"]})
    if status == "link":
        out["naver"].append({"label": "링크 없이 저장", "act": "skip_link", "job": job["id"]})
    if status in ("saved", "error"):
        out["naver"].append({"label": "다시 시작" if status == "saved" else "다시 시도", "act": "restart",
                             "job": job["id"], "style": job.get("style"), "confirm": status == "saved"})
    return out


def act(body):
    """Runs a status-page button: asks shot or Blog Automator to do it. Returns a short message."""
    kind = body.get("act")
    if kind == "flow_retry":
        _post(f"{SHOT}/api/flow/{_id(body.get('pid'))}/retry", {}, {"X-Shot-Flow": "1"})
        return "영상을 다시 만듭니다 (Flow, 실패하면 1번 더 시도)."
    job = _id(body.get("job"))
    if kind == "rewrite":
        _post(f"{BLOGAUTO}/api/jobs/{job}/rewrite", {})
        return "글을 다시 씁니다."
    if kind == "skip_video":
        _post(f"{BLOGAUTO}/api/jobs/{job}/video", {"skip": True})
        return "영상 없이 임시저장합니다."
    if kind == "skip_link":
        _post(f"{BLOGAUTO}/api/link", {"jobId": job, "skip": True})
        return "링크 없이 임시저장합니다."
    if kind == "restart":
        info = next((j for j in (_get(f"{BLOGAUTO}/api/status", {"X-Blogauto": "1"}) or {}).get("jobs", []) if j.get("id") == job), None)
        if not info:
            raise ValueError("작업을 찾을 수 없습니다.")
        if info.get("ctaKeyword") and not any(q in str(info.get("link") or "") for q in IS_QR):
            _post(f"{BLOGAUTO}/api/jobs/{job}/relink", {})
            if info.get("siteUrl"):
                return "네이버 QR 주소를 먼저 만들고, 글 전체를 다시 임시저장합니다."
            return "gov 글을 기다립니다. autopost에서 이 키워드를 다시 발행하면 QR 주소를 만들어 다시 임시저장합니다."
        _post(f"{BLOGAUTO}/api/jobs/{job}/styles/{int(info.get('style') or body.get('style'))}", {"status": "retry"})
        return "글 전체를 다시 임시저장합니다."
    raise ValueError("알 수 없는 동작입니다.")


def _id(value):
    value = str(value or "")
    if not value or not all(c.isalnum() or c in "_-" for c in value):
        raise ValueError("잘못된 작업 번호입니다.")
    return value


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "X-Blogauto": "1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
            message = detail.get("error") or detail.get("detail")
        except ValueError:
            message = ""
        raise ValueError(message or f"HTTP {e.code}") from None
    except (urllib.error.URLError, OSError):
        raise ValueError("프로그램에 연결하지 못했습니다 (꺼져 있는지 확인).") from None


def _link_state(job, qr_tasks, qr_blog, qr_check=None):
    """Yellow box + thumbnail link: gov post → Naver QR short link (made by blog qr_blog's Chrome)."""
    if not job:
        return {"icon": "wait", "text": "-"}
    link, note = str(job.get("link") or ""), job.get("linkNote") or ""
    if job.get("waitLink"):
        if not job.get("siteUrl"):
            return {"icon": "wait", "text": "gov 글 발행 기다리는 중"}
        task = next((t for t in qr_tasks if t.get("ctaKeyword") == job.get("ctaKeyword")), {})
        if task.get("status") == "running":
            return {"icon": "run", "text": f"QR 만드는 중 (블로그 {qr_blog}번 크롬)"}
        at = _iso_to_epoch((qr_check or {}).get("at"))
        seen = f"마지막 확인 {time.strftime('%H:%M:%S', time.localtime(at))}" if at else "아직 확인 안 함: 그 크롬·확장 확인"
        return {"icon": "run" if at and time.time() - at < ALIVE_SECONDS else "warn",
                "text": f"QR 차례 기다리는 중 (블로그 {qr_blog}번 크롬 {seen})"}
    if "site.naver.com" in link or "naver.me" in link:
        return {"icon": "ok", "text": f"QR 링크 {link}"}
    if link:
        return {"icon": "warn", "text": note or f"링크 {link}"}
    return {"icon": "warn" if note else "wait", "text": note or "-"}


def _video_state(flow, done, job):
    via = f" ({flow['engine']})" if flow.get("engine") else ""
    if done.get("done"):
        return {"icon": "ok", "text": f"완성{via}"}
    status = flow.get("status")
    if status == "running":
        return {"icon": "run", "text": flow.get("step") or "Flow 생성 중"}
    if status == "done":
        return {"icon": "run", "text": f"자막·내레이션 입히는 중{via}"}
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
    if status == "link":
        return {"icon": "wait", "text": "③ QR 링크 기다리는 중"}
    if status == "pending":
        return {"icon": "wait", "text": "크롬 차례 기다리는 중"}
    if status == "running":
        return {"icon": "run", "text": f"{round(st.get('percent') or 0)}% · {st.get('step') or '저장 중'}"}
    if status == "saved":
        warn = st.get("warning")
        return {"icon": "warn" if warn else "ok", "text": f"임시저장 완료{' · ' + warn if warn else (' · 영상 포함' if job and job.get('video') else '') + (' · 링크 포함' if job and job.get('link') else '')}"}
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
  .post { display:flex; align-items:center; gap:10px; padding:8px 0; border-top:1px solid var(--line); flex-wrap:wrap; }
  .post:first-of-type { border-top:0; }
  .tag { font-size:12px; padding:2px 8px; border-radius:10px; background:#eef2ff; color:#3730a3; white-space:nowrap; }
  .post .url { color:var(--muted); font-size:13px; word-break:break-all; }
  .acts { margin-top:6px; } .act { border:1px solid var(--run); color:var(--run); background:#fff; border-radius:6px; padding:3px 9px; cursor:pointer; font:inherit; font-size:13px; margin:2px 4px 0 0; }
  .post button { border:1px solid var(--line); background:#fff; border-radius:6px; padding:4px 10px; cursor:pointer; font:inherit; font-size:13px; }
  a { color:var(--run); }
  .alert { border:2px solid var(--warn); background:#fffaeb; }
  .alert h2 { color:var(--warn); }
  .qr-item { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:8px 0; border-top:1px solid #fde7c2; }
  .qr-item:first-child { border-top:0; }
  .qr-item .url { color:var(--muted); font-size:13px; word-break:break-all; }
  .qr-item .dismiss { border:1px solid var(--line); background:#fff; border-radius:6px; padding:3px 9px; cursor:pointer; font:inherit; font-size:13px; }
  @media (max-width: 700px) { th:nth-child(2), td:nth-child(2) { display:none; } }
</style></head>
<body>
<header><b>전체 진행 상황</b><span id="at" class="note" style="color:#cbd5e1"></span></header>
<main>
  <section id="qrAlerts" class="alert" hidden><h2>⚠️ QR 대신 gov 주소로 들어간 글 <span id="qrCount"></span></h2>
    <div id="qrList"></div>
    <p class="note">[QR 만들고 다시 시작]을 누르면 QR 주소를 새로 만들어 그 글을 다시 임시저장합니다 (예전 임시저장 글은 네이버에서 지워 주세요). gov 주소 그대로 둘 글은 [확인함]을 누르면 이 칸에서 사라집니다.</p></section>
  <section><h2>프로그램</h2><div class="chips" id="programs"></div>
    <p class="note">빨간 항목은 꺼져 있거나 연결되지 않은 것입니다. 이름 옆 안내대로 켜 주세요.</p></section>
  <section><h2 id="title">진행 중인 키워드 없음</h2>
    <table><thead><tr><th>블로그</th><th>키워드</th><th>① 글 작성</th><th>② 숏폼 영상</th><th>③ QR 링크</th><th>④ 네이버 임시저장</th></tr></thead><tbody id="rows"></tbody></table></section>
  <section><h2>사이트 발행 (guidejung · gov) · 네이버 QR</h2><div id="site" class="note">-</div></section>
  <p class="note">3초마다 자동으로 새로 고칩니다. 리포트: <a href="/">오늘 리포트 열기</a></p>
</main>
<script>
const ICON = { ok: '✅', run: '⏳', err: '❌', warn: '⚠️', wait: '·' };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const btns = list => (list || []).map(a => `<button class="act" data-act='${esc(JSON.stringify(a))}'>${esc(a.label)}</button>`).join(' ');
const cell = (s, acts) => `<td class="${s.icon}">${ICON[s.icon] || ''} ${esc(s.text)}${acts && acts.length ? `<div class="acts">${btns(acts)}</div>` : ''}</td>`;
async function refresh() {
  try {
    const d = await (await fetch('/api/overview', { cache: 'no-store' })).json();
    document.getElementById('at').textContent = d.at + ' 기준';
    document.getElementById('programs').innerHTML = d.programs.map(p =>
      `<span class="chip ${p.ok ? '' : 'off'}">${p.ok ? '●' : '○'} ${esc(p.name)}${p.ok || !p.fix ? '' : `<small>→ ${esc(p.fix)}</small>`}</span>`).join('');
    document.getElementById('title').textContent = d.keyword ? `키워드: ${d.keyword}` : '진행 중인 키워드 없음 (리포트에서 블로그 4곳에 보내기)';
    const rowsHtml = d.rows.map(r =>
      `<tr><td><b>${r.blog}번</b></td><td>${esc(r.keyword)}</td>${cell(r.write, r.actions.write)}${cell(r.video, r.actions.video)}${cell(r.link)}${cell(r.naver, r.actions.naver)}</tr>`).join('');
    if (rowsHtml !== lastRows) { document.getElementById('rows').innerHTML = rowsHtml; lastRows = rowsHtml; }
    const s = d.site;
    const html = !s ? '이 키워드의 사이트 작업 없음' :
      `<div class="${s.state === '완료' ? 'ok' : s.state === '실패' ? 'err' : 'run'}">${esc(s.state)}</div>
       ${s.links.map(l => `<div class="post"><span class="tag">${esc(l.site || '사이트')}</span>
         <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a>
         <span class="url">${esc(l.url)}</span><button data-copy="${esc(l.url)}">주소 복사</button></div>`).join('')}
       ${s.qr ? `<div class="post"><span class="tag">네이버 QR</span><span>노란 표·썸네일 링크</span>
         <span class="url">${esc(s.qr)}</span><button data-copy="${esc(s.qr)}">주소 복사</button></div>` : ''}
       ${s.last ? `<div class="note">${s.state === '완료' ? '마지막 기록' : '지금'}: ${esc(s.last)}</div>` : ''}`;
    // Redraw only when it changed, so a "복사됨" label is not wiped by the 3-second refresh.
    if (html !== lastSite) { document.getElementById('site').innerHTML = html; lastSite = html; }
    showQrAlerts(d.qr_alerts || []);
  } catch (e) {
    document.getElementById('at').textContent = '상태를 읽지 못했습니다';
  }
}
let lastSite = '', lastRows = '', lastAlerts = null;
// Dismissed alerts are remembered in this browser (key: job id + its link, so a new gov link alerts again).
const seenKey = 'qrAlertsSeen';
const seen = () => { try { return JSON.parse(localStorage.getItem(seenKey) || '[]'); } catch { return []; } };
function showQrAlerts(list) {
  const done = seen(), open = list.filter(a => !done.includes(a.id));
  document.title = (open.length ? `⚠️ QR 확인 ${open.length}건 · ` : '') + '전체 진행 상황';
  const html = open.map(a => `<div class="qr-item"><b>${esc(a.when)}</b><span>${esc(a.blog)}번 블로그 · ${esc(a.keyword)}</span>
      <span class="tag">${esc(a.state)}</span><span class="warn">${esc(a.note)}</span><span class="url">${esc(a.link)}</span>
      ${a.action ? btns([a.action]) : ''}<button class="dismiss" data-seen="${esc(a.id)}">확인함</button></div>`).join('');
  if (html === lastAlerts) return;
  lastAlerts = html;
  document.getElementById('qrList').innerHTML = html;
  document.getElementById('qrCount').textContent = open.length ? `(${open.length}건)` : '';
  document.getElementById('qrAlerts').hidden = !open.length;
}
document.getElementById('qrList').addEventListener('click', e => {
  const id = e.target.dataset.seen;
  if (!id) return;
  try { localStorage.setItem(seenKey, JSON.stringify([...seen(), id].slice(-200))); } catch {}
  lastAlerts = null; refresh();
});
// Row buttons: 영상 다시 만들기 / 영상 없이 저장 / 링크 없이 저장 / 다시 시작 — all from this page.
async function runAct(e) {
  if (!e.target.dataset.act) return;
  const a = JSON.parse(e.target.dataset.act);
  if (a.confirm && !confirm('이 블로그 글을 처음부터 다시 써서 임시저장합니다.\\n이상하게 들어간 예전 임시저장 글은 네이버에서 직접 지워 주세요. 다시 시작할까요?')) return;
  e.target.disabled = true; e.target.textContent = '요청 중…';
  try {
    const r = await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Report-App': '1' }, body: JSON.stringify(a) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    e.target.textContent = '✓ ' + d.message;
  } catch (err) {
    e.target.disabled = false; e.target.textContent = a.label;
    alert('하지 못했습니다: ' + err.message + (/gov 글 주소가 없습니다|not found|404/.test(err.message)
      ? '\\n\\nBlog Automator가 예전 버전으로 켜져 있을 수 있습니다. Blog Automator 창을 닫고 실행.bat으로 다시 켠 뒤 눌러 주세요.' : ''));
  }
  lastRows = ''; lastAlerts = null; setTimeout(refresh, 1500);
}
document.getElementById('rows').addEventListener('click', runAct);
document.getElementById('qrList').addEventListener('click', runAct);
document.getElementById('site').addEventListener('click', async e => {
  const url = e.target.dataset.copy;
  if (!url) return;
  try { await navigator.clipboard.writeText(url); }
  catch { const t = document.createElement('textarea'); t.value = url; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
  e.target.textContent = '복사됨 ✓';
  setTimeout(() => { e.target.textContent = '주소 복사'; }, 1500);
});
refresh(); setInterval(refresh, 3000);
</script>
</body></html>
"""
