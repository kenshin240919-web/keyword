#!/usr/bin/env python3
"""매일 블로그에 쓸 추천 키워드를 골라 리포트로 만듭니다.

사용법:
    python daily_keywords.py                 # 오늘의 추천 키워드 리포트 생성
    python daily_keywords.py --written 궁합   # 이미 글을 쓴 키워드로 기록 (이후 추천 제외)
    python daily_keywords.py --unwritten 궁합 # 잘못 기록한 키워드 취소
    python daily_keywords.py --skip-if-done  # 오늘 리포트가 이미 있으면 건너뜀 (자동 실행용)
    python daily_keywords.py --refresh       # 오늘 결과를 버리고 새로 뽑기 (같은 날 재실행은 첫 결과 유지)

흐름: seeds.txt → 연관 키워드(검색광고) → 작년 시즌 검색수 추정(데이터랩) → 1차 필터
      → 블로그 문서 수(검색 API) → 점수 → reports/날짜.html, .csv + history.db 기록

작년 시즌: 오늘이 2026-10-20이면 2025-11-20 ~ 2025-12-20 (1년 전 기준 한 달 뒤 한 달).
검색광고 API는 최근 30일 검색수만 주므로, 데이터랩 일별 추이의 비율로 그 시기 검색수를 추정합니다.
    작년 시즌 검색수 ≈ 최근 30일 검색수 × (작년 시즌 추이 합 ÷ 최근 30일 추이 합)
"""
import argparse
import csv
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import keywordstool
import naver_api
from keywordstool import ApiError

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SEEDS_PATH = BASE_DIR / "seeds.txt"
DB_PATH = BASE_DIR / "history.db"
REPORT_DIR = BASE_DIR / "reports"

DEFAULT_CONFIG = {
    "min_volume": 1000,          # 작년 시즌 검색수(추정) 범위
    "max_volume": 50000,
    "min_now_volume": 100,       # 지금 월 검색수가 이보다 적으면 추정이 부정확해 제외
    "scan_limit": 500,           # 작년 시즌 검색수를 추정해 볼 후보 수
    "candidate_limit": 100,      # 블로그 문서 수까지 조회할 후보 수
    "season_months_ahead": 1,    # 1년 전 기준 몇 달 뒤부터 볼지
    "top_n": 10,
    "exclude_recent_days": 3,
    "weights": {"volume": 0.3, "opportunity": 0.5, "growth": 0.2},
    "banned_words": [],
    "open_report": True,
    "must_n": 3,
    # '블로그 N곳에 보내기'를 누르면 자동 포스팅 프로그램(autopost, 8777)에도 메인 키워드를 보냅니다.
    "autopost_enabled": True,
    "autopost_url": "http://127.0.0.1:8777",
    "image_dir": r"D:\guidejung\images",   # 메인 키워드와 같은 이름의 이미지(또는 1장만) 넣어 두는 폴더
    # 보낼 때 썸네일 5장(블로그 1~4번, 워프)을 만듭니다. 틀·글씨체는 thumbnail_dir, 결과는 thumbnail_out.
    "thumbnails_enabled": True,
    "thumbnail_dir": str(BASE_DIR / "thumbnail"),
    "thumbnail_out": str(BASE_DIR / "thumbnails"),
}
TELEGRAM_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


LOG_SINK = None  # the report server's 직접 뽑기 page reads the progress lines through this


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOG_SINK:
        LOG_SINK(line)


def load_config():
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        config.update({k: v for k, v in user.items() if k != "weights"})
        config["weights"].update(user.get("weights", {}))
    return config


def load_seeds():
    if not SEEDS_PATH.exists():
        sys.exit(f"[오류] 씨앗 키워드 파일이 없습니다: {SEEDS_PATH}")
    seeds = []
    for line in SEEDS_PATH.read_text(encoding="utf-8-sig").splitlines():
        word = "".join(line.split("#", 1)[0].split())
        if word and word not in seeds:
            seeds.append(word)
    if not seeds:
        sys.exit("[오류] seeds.txt에 씨앗 키워드를 한 줄에 하나씩 넣어 주세요.")
    return seeds


def with_retry(func, *args, tries=3, wait=1.0):
    for attempt in range(1, tries + 1):
        try:
            return func(*args)
        except ApiError as e:
            if attempt == tries:
                raise
            # 네이버 쪽 일시 오류(예: 데이터랩 errorCode 500)는 다시 요청하면 대부분 됩니다. 끝내 실패하면 그 묶음만 건너뜁니다.
            log(f"  네이버 API 일시 오류 → 다시 요청합니다 ({attempt}/{tries - 1}): {e}")
            time.sleep(wait * attempt)


def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


# ---------- 이력 DB ----------

def open_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS recommendations (
        day TEXT, keyword TEXT, score REAL, volume INTEGER,
        blog_total INTEGER, growth REAL, PRIMARY KEY (day, keyword))""")
    db.execute("CREATE TABLE IF NOT EXISTS written (keyword TEXT PRIMARY KEY, day TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS sent (keyword TEXT PRIMARY KEY, day TEXT)")
    return db


def excluded_keywords(db, today, recent_days):
    """Keywords not to recommend again (compared without spaces, case-insensitive): those recommended in the
    last few days, written ('작성 완료'), and **sent to the blogs** — a keyword sent but not yet marked written
    came back the next day (2026-10-30)."""
    since = (today - timedelta(days=recent_days)).isoformat()
    rows = db.execute(
        "SELECT keyword FROM recommendations WHERE day >= ? AND day < ? "
        "UNION SELECT keyword FROM written UNION SELECT keyword FROM sent",
        (since, today.isoformat()),
    )
    return {normalize(r[0]).upper() for r in rows}


# ---------- 수집 ----------

def collect_candidates(seeds, keys):
    """씨앗 5개씩 keywordstool에 넣어 {키워드: (월간 검색수, 광고 경쟁도)}를 모읍니다."""
    found = {}
    for group in chunks(seeds, keywordstool.MAX_HINTS):
        try:
            data = with_retry(keywordstool.fetch_keywords, group, keys)
        except ApiError as e:
            log(f"  [건너뜀] 씨앗 {', '.join(group)}: {e}")
            continue
        for item in data.get("keywordList", []):
            kw = "".join(str(item.get("relKeyword", "")).split())
            if not kw:
                continue
            volume = keywordstool.to_count(item.get("monthlyPcQcCnt", 0)) + \
                keywordstool.to_count(item.get("monthlyMobileQcCnt", 0))
            if kw not in found or volume > found[kw][0]:
                found[kw] = (volume, item.get("compIdx", ""))
        time.sleep(0.3)
    return found


def fetch_each(func, label, keywords, keys):
    """키워드마다 func(키워드, keys)를 불러 {키워드: 결과}로 모읍니다. 실패한 키워드는 빠집니다."""
    result = {}
    for kw in keywords:
        try:
            result[kw] = with_retry(func, kw, keys)
        except ApiError as e:
            log(f"  [건너뜀] {label} {kw}: {e}")
        time.sleep(0.1)
    return result


# ---------- 세부 키워드 ----------

# 키워드 끝에 붙는 말: 이걸 떼어 낸 앞부분(예: 에너지바우처)을 세부 키워드의 기준으로 씁니다.
DETAIL_SUFFIXES = ("신청방법", "신청기간", "신청자격", "신청대상", "자격조건", "잔액조회", "지급일", "사용처",
                   "계산기", "사이트", "신청", "대상", "조건", "자격", "조회", "방법", "기간", "금액")


def detail_base(keyword, seeds):
    """세부 키워드를 찾을 기준 단어: 키워드가 시작하는 가장 긴 씨앗, 없으면 끝말을 뗀 앞부분."""
    inside = [sd for sd in seeds if len(sd) >= 2 and keyword.startswith(sd)]
    if inside:
        return max(inside, key=len)
    for suf in DETAIL_SUFFIXES:
        if keyword.endswith(suf) and len(keyword) - len(suf) >= 2:
            return keyword[:-len(suf)]
    return keyword


# 연관 키워드에서 세부 키워드를 못 찾으면, 기준 단어 뒤에 이 말을 붙여 검색수를 직접 물어봅니다.
DETAIL_TRY = ("신청방법", "지급일", "금액", "대상", "조건", "자격", "신청", "조회", "한도",
              "계산기", "기간", "사용처", "잔액조회", "서류", "소득기준")


def _lookup_volumes(hints, keys, volumes):
    """검색광고 API에 hints를 5개씩 넣어, 응답에 나온 키워드의 검색수를 volumes에 더합니다."""
    for group in chunks(hints, keywordstool.MAX_HINTS):
        try:
            data = with_retry(keywordstool.fetch_keywords, group, keys)
        except ApiError as e:
            log(f"  [건너뜀] 세부 키워드 {', '.join(group)}: {e}")
            continue
        for i in data.get("keywordList", []):
            kw = normalize(i.get("relKeyword", "")).upper()
            volumes[kw] = max(volumes.get(kw, 0), keywordstool.to_count(i.get("monthlyPcQcCnt", 0))
                              + keywordstool.to_count(i.get("monthlyMobileQcCnt", 0)))
        time.sleep(0.3)


def _pick_details(keyword, base, volumes, n):
    kw_u, base_u = keyword.upper(), base.upper()
    picks = sorted((kw for kw, vol in volumes.items() if vol > 0 and base_u in kw and kw not in (kw_u, base_u)),
                   key=lambda kw: volumes[kw], reverse=True)[:n]
    return [(f"{base} {kw[len(base_u):]}" if kw.startswith(base_u) else kw, volumes[kw]) for kw in picks]


def add_details(top, found, seeds, keys, n=3):
    """추천 키워드마다 실제로 검색되는 세부 키워드 n개를 [(보여줄 이름, 현재 월 검색수), ...]로 붙입니다.

    1) 연관 키워드 목록에서 기준 단어(예: 에너지바우처)가 들어간 것을 검색수 순으로 고르고,
    2) 모자라면 '기준 단어 + 신청방법/지급일/금액…' 조합을 만들어 검색수를 직접 확인합니다.
    """
    volumes = {kw.upper(): vol for kw, (vol, _) in found.items()}
    _lookup_volumes([r["keyword"] for r in top], keys, volumes)
    for r in top:
        base = detail_base(r["keyword"], seeds)
        r["details"] = _pick_details(r["keyword"], base, volumes, n)
        if len(r["details"]) < n:
            _lookup_volumes([base + suf for suf in DETAIL_TRY if base + suf != r["keyword"]], keys, volumes)
            r["details"] = _pick_details(r["keyword"], base, volumes, n)


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def season_window(today, months_ahead):
    """작년 시즌 기간: 오늘의 1년 전에서 months_ahead 달 뒤부터 한 달."""
    start = add_months(today, months_ahead - 12)
    return start, add_months(start, 1)


def estimate_season(now_volumes, keys, today, start, end, per_month=False):
    """{키워드: (작년 시즌 검색수 추정, 작년 시즌 ÷ 최근 30일 비율)}을 돌려줍니다.
    per_month: 직접 뽑기처럼 기간 길이가 제각각이면 하루 평균으로 비교해 '한 달 검색수'로 맞춥니다."""
    yesterday = today - timedelta(days=1)
    recent = {(yesterday - timedelta(days=i)).isoformat() for i in range(30)}
    season = {(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)}
    result = {}
    for group in chunks(list(now_volumes), naver_api.DATALAB_MAX_GROUPS):
        try:
            series = with_retry(naver_api.datalab_daily, group, start.isoformat(), yesterday.isoformat(), keys)
        except ApiError as e:
            log(f"  [건너뜀] 추이 {', '.join(group)}: {e}")
            continue
        for kw in group:
            daily = series.get(kw, {})
            now_sum = sum(v for d, v in daily.items() if d in recent)
            past_sum = sum(v for d, v in daily.items() if d in season)
            if now_sum > 0:
                ratio = (past_sum / len(season)) / (now_sum / len(recent)) if per_month else past_sum / now_sum
                result[kw] = (round(now_volumes[kw] * ratio), ratio)
        time.sleep(0.3)
    return result


# ---------- 점수 ----------

def percentile(values):
    """값 목록을 0~100 백분위로 바꿉니다 (클수록 100)."""
    order = sorted(values)
    n = len(order)
    if n == 1:
        return [100.0]
    return [order.index(v) / (n - 1) * 100 for v in values]


def score_rows(rows, weights):
    for key, field in (("volume", "volume"), ("opportunity", "opportunity"), ("growth", "growth")):
        for r, p in zip(rows, percentile([r[field] for r in rows])):
            r[f"p_{key}"] = p
    for r in rows:
        r["score"] = round(
            weights["volume"] * r["p_volume"]
            + weights["opportunity"] * r["p_opportunity"]
            + weights["growth"] * r["p_growth"], 1)
    rows.sort(key=lambda r: r["score"], reverse=True)
    for r in rows:
        r["reason"] = make_reason(r)
    return rows


# 키워드에 이 말이 들어 있으면 어떤 글을 쓰면 좋을지 알려 줍니다 (앞에 있는 것이 우선).
WRITING_HINTS = (
    (("신청방법", "신청기간", "신청"), "신청 절차·준비물 정리글"),
    (("자격", "조건", "대상"), "자격·조건 체크리스트 글"),
    (("기준", "계산"), "기준·계산법 예시 글"),
    (("금액", "얼마", "지급액"), "금액표 정리글"),
    (("기간", "일정", "날짜", "지급일"), "일정 정리글"),
    (("조회", "확인", "사이트", "시스템"), "조회 방법 따라하기 글"),
)


def _man(n):
    return f"{n / 10000:.1f}만" if n >= 10000 else f"{n:,}"


def make_reason(r):
    """점수 데이터로 추천 이유를 한 줄로 만듭니다 (강점 최대 2개 + 주의점·글 방향)."""
    strengths = []
    growth = (r["growth"] - 1) * 100
    if growth >= 30:
        strengths.append(f"작년 이 시기엔 지금보다 검색 {r['growth']:.1f}배 → 곧 늘어날 시즌 키워드")
    if r["p_opportunity"] >= 99.5:
        strengths.append("검색 대비 경쟁 글이 후보 중 가장 적음")
    elif r["p_opportunity"] >= 80:
        strengths.append(f"검색 대비 경쟁 글이 적은 편(후보 중 상위 {100 - r['p_opportunity']:.0f}%)")
    if r["p_volume"] >= 80:
        strengths.append(f"작년 이 시기 월 {_man(r['volume'])}회로 찾는 사람이 많음")
    if 10 <= growth < 30 and len(strengths) < 2:
        strengths.append(f"작년 이 시기 검색이 지금보다 많았음({growth:+.0f}%)")
    if r["comp"] == "낮음" and len(strengths) < 2:
        strengths.append("광고 경쟁 낮음")
    if not strengths:
        strengths.append("검색수·경쟁·시즌성이 고르게 무난함")
    parts = strengths[:2]

    if r["blog_total"] >= 300000:
        parts.append("경쟁 글이 많아 세부 주제로 좁히길 권장")
    elif growth <= -10:
        parts.append(f"다만 작년 이 시기엔 지금보다 검색이 적었음({growth:+.0f}%)")
    for words, hint in WRITING_HINTS:
        if any(w in r["keyword"] for w in words):
            parts.append(f"추천 글: {hint}")
            break
    return " · ".join(parts)


def _common_len(a, b):
    """두 키워드가 겹치는 가장 긴 글자 수 (예: 내일배움카드신청 / 국민내일배움카드 → 6)."""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def _similar(a, b):
    return _common_len(a, b) >= 4


# 꼭 쓸 3개를 고르는 기준: (이름, 고르는 값, 선정 이유)
MUST_RULES = (
    ("경쟁 최저", lambda r: r["opportunity"], "검색 대비 경쟁 글이 가장 적어 상위 노출에 유리"),
    ("시즌 급증", lambda r: r["growth"], "작년 이 시기에 검색이 가장 크게 늘었던 키워드라 미리 써 두기 좋음"),
    ("종합 1위", lambda r: r["score"], "검색수·경쟁·추세를 합친 점수가 가장 높음"),
)


def pick_must(rows, n=3):
    """추천 목록에서 성격이 다른 '꼭 쓸 키워드' n개를 고릅니다.

    작년 이 시기 검색이 지금보다 적었던 키워드(시즌 변화 0% 미만)는 고르지 않고,
    경쟁 글이 30만 개 넘는 키워드는 되도록 빼며, 서로 비슷한 키워드는 함께 고르지 않습니다.
    """
    for r in rows:
        r["must"] = None
    picked = []
    for label, key, why in MUST_RULES[:n]:
        pool = [r for r in rows if r not in picked and r["growth"] >= 1.0
                and not any(_similar(r["keyword"], p["keyword"]) for p in picked)]
        easy = [r for r in pool if r["blog_total"] < 300000]
        pool = easy or pool
        if not pool:
            break
        best = max(pool, key=key)
        best["must"] = f"{label}: {why}"
        picked.append(best)
    return picked


# ---------- 결과물 ----------

def blog_search_url(keyword):
    return "https://search.naver.com/search.naver?" + urllib.parse.urlencode({"where": "blog", "query": keyword})


def write_csv(rows, path):
    # utf-8-sig: 엑셀에서 열었을 때 한글이 깨지지 않도록
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["순위", "키워드", "작년 시즌 검색수(추정)", "현재 월 검색수", "블로그 문서 수", "카페 글 수",
                    "기회 지수", "시즌 변화(%)", "점수", "광고 경쟁도", "추천 이유", "블로그 검색", "꼭 쓸 키워드",
                    "세부 키워드"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["keyword"], r["volume"], r.get("now_volume", ""), r["blog_total"], r.get("cafe_total", ""),
                        round(r["opportunity"], 2), round((r["growth"] - 1) * 100), r["score"], r["comp"],
                        r["reason"], blog_search_url(r["keyword"]), r.get("must") or "",
                        " / ".join(name for name, _ in r.get("details", []))])


def _details_html(r):
    ds = r.get("details", [])
    if not ds:
        return ""
    chips = "".join(f"<span class='chip'>{html.escape(name)} <em>{_man(vol)}</em></span>" for name, vol in ds)
    return f"<div class='details'><span class='lbl'>세부 키워드</span>{chips}</div>"


def post_keywords(r):
    """Blog Automator로 보낼 키워드: 1번 블로그는 메인 키워드, 2~4번은 세부 키워드."""
    return [r["keyword"]] + [name for name, _ in r.get("details", [])][:3]


def _post_button(r):
    kws = post_keywords(r)
    data = html.escape(json.dumps(kws, ensure_ascii=False), quote=True)
    return (f"<button class='p' type='button' data-kw='{html.escape(r['keyword'], quote=True)}' "
            f"data-post='{data}'>블로그 {len(kws)}곳에 보내기</button>")


def _write_button(keyword):
    return f"<button class='w' type='button' data-kw='{html.escape(keyword, quote=True)}'>오늘 썼어요</button>"


# 리포트의 '오늘 썼어요' 버튼: report_server.py 를 통해 history.db 에 기록합니다.
REPORT_SCRIPT = """<script>
const live = location.protocol.startsWith('http');
const buttons = () => document.querySelectorAll('button.w');
function render(list) {
  const done = new Set(list);
  buttons().forEach(b => {
    const on = done.has(b.dataset.kw);
    b.classList.toggle('on', on);
    b.textContent = on ? '\u2714 작성 완료' : '오늘 썼어요';
    b.closest('tr, .card').classList.toggle('done', on);
  });
}
async function save(kw, done) {
  const r = await fetch('/api/written', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Report-App': '1'},
    body: JSON.stringify({keyword: kw, done})});
  if (!r.ok) throw new Error(r.status);
  render((await r.json()).keywords);
}
document.addEventListener('click', async e => {
  const b = e.target.closest('button.w');
  if (!b || !live) return;
  const on = b.classList.contains('on');
  if (on && !confirm('"' + b.dataset.kw + '" 작성 기록을 취소할까요?')) return;
  try { await save(b.dataset.kw, !on); }
  catch (err) { alert('기록하지 못했습니다. open_report.bat으로 리포트를 다시 열어 주세요.'); }
});
// '블로그 N곳에 보내기': Blog Automator(127.0.0.1:37321)에 블로그별 키워드로 글 작성·임시저장을 요청합니다.
const ACCOUNTS = ['1번 lbkneon', '2번 guideruri', '3번 rbans56', '4번 cgm3854'];
const postButtons = () => document.querySelectorAll('button.p');
function renderSent(list) {
  const sent = new Set(list);
  postButtons().forEach(b => {
    const on = sent.has(b.dataset.kw);
    b.classList.toggle('sent', on);
    if (on) b.textContent = '\u2714 보냄 (다시 보내기)';
  });
}
document.addEventListener('click', async e => {
  const b = e.target.closest('button.p');
  if (!b || !live) return;
  const kws = JSON.parse(b.dataset.post);
  let phrase = '', button = '';
  const call = async (url) => {
    const r = await fetch(url, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Report-App': '1'},
      body: JSON.stringify({keywords: kws, phrase, button})});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    return d;
  };
  let site;
  const label = b.textContent;
  b.disabled = true; b.textContent = '썸네일 문구 만드는 중\u2026';
  try { site = await call('/api/post-plan'); }
  catch (err) { return alert('보내지 못했습니다: ' + err.message); }
  finally { b.disabled = false; b.textContent = label; }
  if (site.thumb) {
    phrase = prompt('썸네일 가운데 문구를 확인하세요. 고쳐도 됩니다 (5~6자 권장).', site.thumb.phrase);
    if (phrase === null) return;
    button = site.thumb.button;
  }
  const plan = '[네이버 블로그 \u2192 임시저장]\\n' + kws.map((k, i) => ACCOUNTS[i] + ' \u2190 ' + k).join('\\n')
    + (site.thumb ? '\\n\\n[썸네일 5장]\\n' + kws[0] + ' / ' + phrase + ' / 바로 ' + button : '')
    + (site.autopost ? '\\n\\n[사이트 자동 포스팅 \u2192 발행]\\nguidejung\u00b7gov \u2190 ' + kws[0] + '\\n이미지: '
       + (site.image || (site.thumb ? '워프 썸네일' : '없음 (이미지 없이 발행)')) : '')
    + (site.thumb_note ? '\\n\\n(썸네일은 만들지 않습니다: ' + site.thumb_note + ')' : '');
  const again = b.classList.contains('sent') ? '이미 보낸 키워드입니다. 다시 보낼까요?\\n\\n' : '';
  if (!confirm(again + plan)) return;
  b.disabled = true;
  try {
    const d = await call('/api/post');
    renderSent(d.sent);
    alert('네이버 블로그 ' + d.jobs + '곳에 보냈습니다 (진행 상황: 크롬 Blog Automator 사이드패널).'
      + (d.thumbs ? '\\n썸네일 ' + d.thumbs + '장을 만들어 함께 보냈습니다 (thumbnails 폴더).' : '')
      + (d.autopost ? '\\n사이트 자동 포스팅도 시작했습니다 (진행 상황: http://127.0.0.1:8777). '
        + (d.archived ? '쓴 이미지는 사용완료 폴더로 옮겼습니다.' : d.image ? '대표 이미지: ' + d.image : '(이미지 없이 발행)') : '')
      + (d.warning ? '\\n\\n' + d.warning : '')
      + '\\n\\n확인을 누르면 전체 진행 상황 페이지가 열립니다.');
    window.open('/status', 'guidejung-status');
  } catch (err) {
    alert('보내지 못했습니다: ' + (err.message === 'Failed to fetch'
      ? '리포트 서버와 연결이 끊겼습니다. open_report.bat으로 리포트를 다시 연 뒤 눌러 주세요. 계속되면 logs 폴더의 report_server.log를 보여 주세요.'
      : err.message));
  }
  finally { b.disabled = false; }
});
if (live) {
  fetch('/api/sent').then(r => r.json()).then(d => renderSent(d.keywords)).catch(() => {});
  fetch('/api/written').then(r => r.json()).then(d => render(d.keywords)).catch(() => {});
} else {
  buttons().forEach(b => b.disabled = true);
  postButtons().forEach(b => b.disabled = true);
  document.getElementById('notice').hidden = false;
}
</script>
"""


COPY_SCRIPT = """<script>
document.addEventListener('click', async e => {
  const kw = e.target.dataset && e.target.dataset.copy;
  if (!kw) return;
  try { await navigator.clipboard.writeText(kw); }
  catch { const t = document.createElement('textarea'); t.value = kw; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
  e.target.textContent = '복사됨 ✓'; setTimeout(() => { e.target.textContent = '키워드 복사'; }, 1500);
});
</script>"""


def write_html(rows, path, today, stats, buttons=True):
    """buttons=False (직접 뽑기): 블로그 4곳 보내기·오늘 썼어요 없이 '키워드 복사'만 — 다른 블로그용이라 매일 흐름과 섞지 않음."""
    acts = (lambda r: _post_button(r) + _write_button(r["keyword"])) if buttons else \
        (lambda r: f"<button class='w' data-copy='{html.escape(r['keyword'], quote=True)}'>키워드 복사</button>")
    period = stats.get("period")
    period_text = f"({period[0]} ~ {period[1]})" if period else ""
    musts = [r for r in rows if r.get("must")]
    cards = "\n".join(
        f"<div class='card'><div class='n'>{i}</div><div><div class='mk'>{html.escape(r['keyword'])}</div>"
        f"<div class='ml'>{html.escape(r['must'])}</div>"
        f"<div class='mm'>작년 시즌 월 {r['volume']:,}회 검색(추정) · 경쟁 글 {r['blog_total']:,}개 · "
        f"지금 대비 {(r['growth'] - 1) * 100:+.0f}% · "
        f"<a href='{html.escape(blog_search_url(r['keyword']))}' target='_blank'>상위 글 보기</a></div>"
        f"{_details_html(r)}</div>"
        f"<div class='btns'>{acts(r)}</div></div>"
        for i, r in enumerate(musts, 1)
    )
    body = "\n".join(
        f"<tr class='{'must' if r.get('must') else ''}'><td>{i}</td>"
        f"<td class='kw'>{'★ ' if r.get('must') else ''}{html.escape(r['keyword'])}{_details_html(r)}</td>"
        f"<td>{r['volume']:,}</td><td>{r.get('now_volume', 0):,}</td>"
        f"<td>{r['blog_total']:,}</td><td>{r.get('cafe_total', 0):,}</td><td>{r['opportunity']:.2f}</td>"
        f"<td class='{'up' if r['growth'] >= 1 else 'down'}'>{(r['growth'] - 1) * 100:+.0f}%</td>"
        f"<td><b>{r['score']}</b></td><td>{html.escape(str(r['comp']))}</td>"
        f"<td class='why'>{html.escape(r['reason'])}</td>"
        f"<td><a href='{html.escape(blog_search_url(r['keyword']))}' target='_blank'>열기</a></td>"
        f"<td><div class='btns'>{acts(r)}</div></td></tr>"
        for i, r in enumerate(rows, 1)
    )
    path.write_text(f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 블로그 키워드 {today}</title>
<style>
body {{ font-family: "Malgun Gothic", sans-serif; margin: 24px; color: #222; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }}
p.meta {{ color: #666; margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; max-width: 1400px; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: right; white-space: nowrap; }}
th {{ background: #f4f6f8; }}
td.kw, th.kw {{ text-align: left; font-weight: 600; }}
td.why, th.why {{ text-align: left; white-space: normal; min-width: 280px; color: #444; font-size: 14px; }}
.up {{ color: #c0392b; }} .down {{ color: #2c6fbb; }}
tr.must td {{ background: #fff8e1; }}
.picks {{ max-width: 1400px; margin: 16px 0 28px; }}
.picks h2 {{ font-size: 18px; margin: 0 0 10px; }}
.card {{ display: flex; gap: 14px; align-items: flex-start; border: 2px solid #f0b400; background: #fffdf5; border-radius: 10px; padding: 12px 16px; margin-bottom: 10px; }}
.card .n {{ flex: none; width: 30px; height: 30px; border-radius: 50%; background: #f0b400; color: #fff; font-weight: 700; display: flex; align-items: center; justify-content: center; }}
.card .mk {{ font-size: 19px; font-weight: 700; }}
.card .ml {{ color: #8a5a00; margin: 2px 0 4px; }}
.card .mm {{ color: #555; font-size: 14px; }}
.details {{ margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; white-space: normal; }}
.details .lbl {{ font-size: 12px; color: #888; font-weight: 400; margin-right: 2px; }}
.chip {{ font-size: 12.5px; font-weight: 500; background: #eef3fb; color: #1e4e8c; border-radius: 12px; padding: 2px 8px; }}
.chip em {{ font-style: normal; color: #7a8ca5; font-size: 11.5px; }}
td.kw {{ min-width: 230px; max-width: 300px; white-space: normal; }}

.card > div:nth-child(2) {{ flex: 1; }}
button.w {{ font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 8px; border: 1px solid #2e7d32; background: #fff; color: #2e7d32; cursor: pointer; white-space: nowrap; }}
button.w:hover {{ background: #e8f5e9; }}
.btns {{ display: flex; flex-direction: column; gap: 6px; align-items: stretch; }}
button.p {{ font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 8px; border: 1px solid #2b6cb0; background: #2b6cb0; color: #fff; cursor: pointer; white-space: nowrap; }}
button.p:hover {{ background: #1e4e8c; }}
button.p.sent {{ background: #fff; color: #2b6cb0; }}
button.p:disabled {{ border-color: #bbb; color: #999; background: #f5f5f5; cursor: default; }}
button.w.on {{ background: #2e7d32; color: #fff; }}
button.w:disabled {{ border-color: #bbb; color: #999; background: #f5f5f5; cursor: default; }}
.done .kw, .done .mk {{ text-decoration: line-through; color: #888; }}
.notice {{ max-width: 1400px; background: #fff3f3; border: 1px solid #f2b8b5; color: #8c1d18; border-radius: 8px; padding: 10px 14px; margin: 12px 0; }}
</style></head><body>
<h1>오늘의 블로그 키워드 · {today} <a href="/status" target="_blank" style="font-size:15px;font-weight:normal">전체 진행 상황 보기 →</a></h1>
<p class="meta"><b>작년 시즌 {period_text} 검색수 기준</b> · 후보 {stats['candidates']}개 중 점수 상위 {len(rows)}개<br>
작년 시즌 검색수 = 현재 월 검색수 × 데이터랩 추이 비율(추정) · 기회 지수 = 작년 시즌 검색수 ÷ (블로그 + 카페 글 수) · 시즌 변화 = 작년 시즌 ÷ 최근 30일</p>
<div class="picks"><h2>오늘 꼭 쓸 키워드 {len(musts)}개</h2>
{cards}
</div>
<h2 style="font-size:18px">전체 추천 {len(rows)}개 <span style="font-weight:400;color:#888;font-size:14px">(★ = 꼭 쓸 키워드)</span></h2>
<table><tr><th>순위</th><th class="kw">키워드</th><th>작년 시즌<br>검색수(추정)</th><th>현재<br>월 검색수</th><th>블로그<br>문서 수</th><th>카페<br>글 수</th><th>기회 지수</th><th>시즌 변화</th><th>점수</th><th>광고 경쟁도</th><th class="why">추천 이유</th><th>블로그 검색</th><th>{'포스팅 · 작성 기록' if buttons else '복사'}</th></tr>
{body}
</table>
""" + ("""<div id="notice" class="notice" hidden>'오늘 썼어요'·'보내기' 버튼을 쓰려면 key 폴더의 <b>open_report.bat</b>을 더블클릭해 리포트를 여세요.</div>
""" + REPORT_SCRIPT if buttons else COPY_SCRIPT) + "</body></html>\n", encoding="utf-8")


def send_telegram(rows, today, keys):
    musts = [r for r in rows if r.get("must")]
    text = f"오늘의 블로그 키워드 ({today})\n\n[오늘 꼭 쓸 {len(musts)}개]\n" + "\n".join(
        f"★ {r['keyword']} - {r['must']}" for r in musts) + "\n\n[전체 추천]\n" + "\n".join(
        f"{i}. {r['keyword']} · 작년 시즌 검색 {r['volume']:,} · 점수 {r['score']}" for i, r in enumerate(rows, 1))
    url = f"https://api.telegram.org/bot{keys['TELEGRAM_BOT_TOKEN']}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": keys["TELEGRAM_CHAT_ID"], "text": text}).encode("utf-8")
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15).close()
        log("텔레그램 전송 완료")
    except Exception as e:
        # 오류 메시지에 봇 토큰이 섞일 수 있어 내용은 출력하지 않습니다.
        log(f"[경고] 텔레그램 전송 실패 ({type(e).__name__})")


def print_rows(rows):
    for i, r in enumerate(rows, 1):
        print(f"  {i:>2}. {r['keyword']}  작년 시즌 {r['volume']:,} · 지금 {r.get('now_volume', 0):,} · "
              f"문서 {r['blog_total']:,} · 시즌 {(r['growth'] - 1) * 100:+.0f}% · 점수 {r['score']}")
        print(f"      └ {r['reason']}")
        if r.get("details"):
            print(f"      └ 세부: {', '.join(name for name, _ in r['details'])}")


# ---------- 실행 ----------

def normalize(keyword):
    return "".join(str(keyword).split())


def add_written(db, keyword):
    db.execute("INSERT OR REPLACE INTO written VALUES (?, ?)", (normalize(keyword), date.today().isoformat()))
    db.commit()


def remove_written(db, keyword):
    removed = db.execute("DELETE FROM written WHERE keyword = ?", (normalize(keyword),)).rowcount > 0
    db.commit()
    return removed


def add_sent(db, keyword):
    db.execute("INSERT OR REPLACE INTO sent VALUES (?, ?)", (normalize(keyword), date.today().isoformat()))
    db.commit()


def sent_keywords(db):
    return [r[0] for r in db.execute("SELECT keyword FROM sent")]


def written_keywords(db):
    return [r[0] for r in db.execute("SELECT keyword FROM written ORDER BY day DESC, keyword")]


def mark_written(words):
    db = open_db()
    for w in words:
        add_written(db, w)
    print(f"작성 완료로 기록했습니다 (이후 추천에서 제외): {', '.join(words)}")


def unmark_written(words):
    db = open_db()
    removed = [w for w in words if remove_written(db, w)]
    missing = [w for w in words if w not in removed]
    if removed:
        print(f"작성 기록을 취소했습니다: {', '.join(removed)}")
    if missing:
        print(f"작성 기록에 없는 키워드입니다: {', '.join(missing)}")


def run(today=None, refresh=False, seeds=None, period=None, open_browser=True):
    """seeds: 직접 뽑기 — 이 씨앗으로 따로 뽑아 reports\직접뽑기\에 저장합니다. 매일 리포트·기록(history.db)은 그대로 둡니다.
    period: 직접 뽑기의 기준 기간 (시작일, 종료일 date). 없으면 매일 리포트와 같은 '작년 시즌'."""
    today = today or date.today()
    config = load_config()
    custom = bool(seeds)
    result_path = REPORT_DIR / f"{today.isoformat()}.json"
    if result_path.exists() and not refresh and not custom:
        # 같은 날 다시 실행하면 아침 첫 결과를 그대로 보여 줍니다 (API를 다시 부르지 않음).
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        log("오늘 첫 결과를 그대로 보여 줍니다. 새로 뽑으려면 --refresh 를 붙여 실행하세요.")
        missing = [r for r in saved["top"] if len(r.get("details", [])) < 3]
        if missing:
            log(f"  세부 키워드가 모자란 {len(missing)}개만 다시 찾습니다.")
            keys = keywordstool.load_keys(required=keywordstool.REQUIRED_KEYS)
            add_details(missing, {}, load_seeds(), keys)
            result_path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        publish(saved["top"], today, saved["candidates"], config, saved.get("period"))
        return

    seeds = seeds or load_seeds()
    keys = keywordstool.load_keys(required=keywordstool.REQUIRED_KEYS + naver_api.OPENAPI_KEYS)
    db = open_db()

    start, end = period if custom and period else season_window(today, config["season_months_ahead"])
    period = [start.isoformat(), end.isoformat()]

    log(f"1/5 연관 키워드 수집 (씨앗 {len(seeds)}개)")
    found = collect_candidates(seeds, keys)
    banned = [b for b in config["banned_words"] if b]
    # 직접 뽑기는 다른 블로그용이라 매일 리포트의 추천·작성 기록과 상관없이 모두 보여 줍니다.
    skip = set() if custom else excluded_keywords(db, today, config["exclude_recent_days"])
    scan = sorted(
        ((kw, vol) for kw, (vol, _) in found.items()
         if vol >= config["min_now_volume"] and normalize(kw).upper() not in skip and not any(b in kw for b in banned)),
        key=lambda x: x[1], reverse=True)[:config["scan_limit"]]
    log(f"  연관 키워드 {len(found)}개 → 추정 대상 {len(scan)}개")

    log(f"2/5 작년 시즌({period[0]} ~ {period[1]}) 검색수 추정 (데이터랩)")
    season = estimate_season(dict(scan), keys, today, start, end, per_month=custom)
    pool = sorted(
        (kw for kw, (est, _) in season.items() if config["min_volume"] <= est <= config["max_volume"]),
        key=lambda kw: season[kw][0], reverse=True)[:config["candidate_limit"]]
    log(f"  추정 {len(season)}개 → 작년 시즌 검색수 {config['min_volume']:,}~{config['max_volume']:,} 후보 {len(pool)}개")
    if not pool:
        sys.exit("[오류] 조건에 맞는 후보가 없습니다. config.json의 검색수 범위나 seeds.txt를 확인해 주세요.")

    log(f"3/5 블로그·카페 글 수 조회 ({len(pool)}개)")
    totals = fetch_each(naver_api.blog_total, "블로그 문서 수", pool, keys)
    cafes = fetch_each(naver_api.cafe_total, "카페 글 수", pool, keys)

    rows = [
        {"keyword": kw, "volume": season[kw][0], "now_volume": found[kw][0], "comp": found[kw][1],
         "blog_total": totals[kw], "cafe_total": cafes.get(kw, 0),
         "opportunity": season[kw][0] / max(totals[kw] + cafes.get(kw, 0), 1), "growth": season[kw][1]}
        for kw in pool if kw in totals
    ]
    if not rows:
        sys.exit("[오류] 블로그 문서 수를 하나도 가져오지 못했습니다. NAVER_CLIENT_ID/SECRET을 확인해 주세요.")
    top = score_rows(rows, config["weights"])[:config["top_n"]]

    log("4/5 세부 키워드 수집")
    add_details(top, found, seeds, keys)

    log("5/5 리포트 저장")
    if custom:
        return publish_custom(top, today, len(rows), config, period, seeds, open_browser)
    REPORT_DIR.mkdir(exist_ok=True)
    result_path.write_text(json.dumps({"top": top, "candidates": len(rows), "period": period},
                                      ensure_ascii=False, indent=1),
                           encoding="utf-8")
    # 같은 날 --refresh 로 다시 뽑으면 그날 기록을 새 결과로 바꿉니다.
    db.execute("DELETE FROM recommendations WHERE day = ?", (today.isoformat(),))
    db.executemany(
        "INSERT OR REPLACE INTO recommendations VALUES (?, ?, ?, ?, ?, ?)",
        [(today.isoformat(), r["keyword"], r["score"], r["volume"], r["blog_total"], r["growth"]) for r in top],
    )
    db.commit()

    publish(top, today, len(rows), config, period)
    if all(keys.get(k) for k in TELEGRAM_KEYS):
        send_telegram(top, today.isoformat(), keys)


def publish(top, today, candidates, config, period=None):
    """꼭 쓸 키워드를 고르고, 리포트(HTML·CSV)를 쓰고 화면에 보여 준 뒤 브라우저로 엽니다.

    이미 블로그로 보냈거나 '오늘 썼어요'로 기록한 키워드는 꼭 쓸 키워드에서 빼고(전체 추천 목록에는 남김),
    리포트를 다시 열 때마다 다시 고릅니다."""
    db = open_db()
    try:
        done = {normalize(k) for k in sent_keywords(db) + written_keywords(db)}
    finally:
        db.close()
    for r in top:
        r["must"] = None
    musts = pick_must([r for r in top if normalize(r["keyword"]) not in done], config["must_n"])
    html_path = REPORT_DIR / f"{today.isoformat()}.html"
    csv_path = REPORT_DIR / f"{today.isoformat()}.csv"
    write_html(top, html_path, today.isoformat(), {"candidates": candidates, "period": period})
    write_csv(top, csv_path)

    print(f"\n★ 오늘 꼭 쓸 키워드 {len(musts)}개")
    for r in musts:
        print(f"  ★ {r['keyword']}  ({r['must']})")
    print(f"\n오늘의 추천 키워드 {len(top)}개")
    print_rows(top)
    print(f"\n리포트: {html_path}\nCSV:    {csv_path}")
    if config["open_report"]:
        import report_server
        report_server.open_report(html_path.name)


# 직접 뽑기 결과 페이지는 매일 리포트와 헷갈리지 않게 제목·문구·색을 바꿉니다.
CUSTOM_WORDS = (("오늘의 블로그 키워드", "직접 뽑은 키워드"), ("오늘 꼭 쓸 키워드", "꼭 쓸 키워드"),
                ("작년 시즌", "선택 기간"), ("작년 이 시기", "선택 기간"), ("시즌 변화", "기간 변화"),
                (' <a href="/status" target="_blank" style="font-size:15px;font-weight:normal">전체 진행 상황 보기 →</a>', ""))
CUSTOM_STYLE = ("<style>body{background:#f3f6ff} h1{color:#1e4e8c} h1::before{content:'직접 뽑기 결과';display:block;"
                "font-size:13px;font-weight:700;color:#fff;background:#2b6cb0;border-radius:6px;padding:3px 10px;width:max-content;margin-bottom:6px}</style>")


def publish_custom(top, today, candidates, config, period, seeds, open_browser=True):
    """직접 뽑기 결과: reports\직접뽑기\날짜_시각_첫씨앗.html·.csv (매일 리포트와 따로). 파일 이름(확장자 없이)을 돌려줍니다."""
    out = REPORT_DIR / "직접뽑기"
    out.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now():%Y-%m-%d_%H%M}_{re.sub(r'[^0-9A-Za-z가-힣]+', '', seeds[0])[:20] or '키워드'}"
    musts = pick_must(top, config["must_n"])
    write_html(top, out / f"{name}.html", f"{today.isoformat()} · 씨앗: {', '.join(seeds)}",
               {"candidates": candidates, "period": period}, buttons=False)
    page = (out / f"{name}.html").read_text(encoding="utf-8")
    for old, new in CUSTOM_WORDS:
        page = page.replace(old, new)
    (out / f"{name}.html").write_text(page.replace("</head>", CUSTOM_STYLE + "</head>", 1), encoding="utf-8")
    write_csv(top, out / f"{name}.csv")
    print(f"\n★ 꼭 쓸 키워드 {len(musts)}개")
    for r in musts:
        print(f"  ★ {r['keyword']}  ({r['must']})")
    print(f"\n추천 키워드 {len(top)}개")
    print_rows(top)
    print(f"\n리포트: {out / (name + '.html')}\nCSV:    {out / (name + '.csv')}")
    if open_browser and config["open_report"]:  # through the report server, so its 보내기·썼어요 buttons work
        import report_server
        report_server.open_report(f"직접뽑기/{name}.html")
    return name


def main():
    keywordstool.setup_console()
    parser = argparse.ArgumentParser(description="매일 블로그 추천 키워드 리포트")
    parser.add_argument("--written", nargs="+", metavar="키워드", help="이미 글을 쓴 키워드로 기록 (이후 추천 제외)")
    parser.add_argument("--unwritten", nargs="+", metavar="키워드", help="잘못 기록한 작성 키워드 취소")
    parser.add_argument("--skip-if-done", action="store_true", help="오늘 리포트가 이미 있으면 실행하지 않음")
    parser.add_argument("--refresh", action="store_true", help="오늘 결과를 버리고 새로 뽑기")
    parser.add_argument("--seeds", nargs="*", metavar="씨앗", help="직접 뽑기: 이 씨앗 키워드로 따로 뽑기 (쉼표로 구분, 비우면 물어봄)")
    args = parser.parse_args()
    if args.seeds is not None:
        text = " ".join(args.seeds) or input("씨앗 키워드를 쉼표로 구분해 입력하세요 (예: 청년지원금, 전세대출): ")
        seeds = [s.strip() for s in re.split(r"[,\n]", text) if s.strip()]
        if not seeds:
            sys.exit("씨앗 키워드가 없습니다.")
        return run(seeds=seeds)
    if args.written:
        mark_written(args.written)
    elif args.unwritten:
        unmark_written(args.unwritten)
    elif args.skip_if_done and (REPORT_DIR / f"{date.today().isoformat()}.html").exists():
        log("오늘 리포트가 이미 있어 건너뜁니다.")
    else:
        run(refresh=args.refresh)


if __name__ == "__main__":
    main()
