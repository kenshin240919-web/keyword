#!/usr/bin/env python3
"""매일 블로그에 쓸 추천 키워드를 골라 리포트로 만듭니다.

사용법:
    python daily_keywords.py                 # 오늘의 추천 키워드 리포트 생성
    python daily_keywords.py --written 궁합   # 이미 글을 쓴 키워드로 기록 (이후 추천 제외)

흐름: seeds.txt → 연관 키워드(검색광고) → 1차 필터 → 블로그 문서 수(검색 API)
      → 일별 추세(데이터랩) → 점수 → reports/날짜.html, .csv + history.db 기록
"""
import argparse
import csv
import html
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, timedelta
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
    "min_volume": 1000,
    "max_volume": 50000,
    "candidate_limit": 100,
    "top_n": 10,
    "exclude_recent_days": 30,
    "weights": {"volume": 0.3, "opportunity": 0.5, "growth": 0.2},
    "banned_words": [],
    "open_report": True,
}
TELEGRAM_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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
            log(f"  재시도 {attempt}/{tries - 1}: {e}")
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
    return db


def excluded_keywords(db, today, recent_days):
    since = (today - timedelta(days=recent_days)).isoformat()
    rows = db.execute(
        "SELECT keyword FROM recommendations WHERE day >= ? AND day < ? "
        "UNION SELECT keyword FROM written",
        (since, today.isoformat()),
    )
    return {r[0] for r in rows}


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


def fetch_blog_totals(keywords, keys):
    totals = {}
    for kw in keywords:
        try:
            totals[kw] = with_retry(naver_api.blog_total, kw, keys)
        except ApiError as e:
            log(f"  [건너뜀] 블로그 문서 수 {kw}: {e}")
        time.sleep(0.1)
    return totals


def fetch_growth(keywords, keys, today):
    """최근 7일 평균 ÷ 이전 28일 평균. 오늘은 집계가 덜 됐으므로 어제까지 봅니다."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=34)
    days = [(start + timedelta(days=i)).isoformat() for i in range(35)]
    growth = {}
    for group in chunks(keywords, naver_api.DATALAB_MAX_GROUPS):
        try:
            series = with_retry(naver_api.datalab_daily, group, start.isoformat(), end.isoformat(), keys)
        except ApiError as e:
            log(f"  [건너뜀] 추세 {', '.join(group)}: {e}")
            continue
        for kw in group:
            values = [series.get(kw, {}).get(d, 0.0) for d in days]
            prior, recent = sum(values[:28]) / 28, sum(values[28:]) / 7
            if prior > 0:
                growth[kw] = recent / prior
            else:
                growth[kw] = 2.0 if recent > 0 else 1.0
        time.sleep(0.3)
    return growth


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
    return rows


# ---------- 결과물 ----------

def blog_search_url(keyword):
    return "https://search.naver.com/search.naver?" + urllib.parse.urlencode({"where": "blog", "query": keyword})


def write_csv(rows, path):
    # utf-8-sig: 엑셀에서 열었을 때 한글이 깨지지 않도록
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["순위", "키워드", "월간 검색수", "블로그 문서 수", "기회 지수", "7일 상승률(%)", "점수", "광고 경쟁도", "블로그 검색"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["keyword"], r["volume"], r["blog_total"], round(r["opportunity"], 2),
                        round((r["growth"] - 1) * 100), r["score"], r["comp"], blog_search_url(r["keyword"])])


def write_html(rows, path, today, stats):
    body = "\n".join(
        f"<tr><td>{i}</td><td class='kw'>{html.escape(r['keyword'])}</td>"
        f"<td>{r['volume']:,}</td><td>{r['blog_total']:,}</td><td>{r['opportunity']:.2f}</td>"
        f"<td class='{'up' if r['growth'] >= 1 else 'down'}'>{(r['growth'] - 1) * 100:+.0f}%</td>"
        f"<td><b>{r['score']}</b></td><td>{html.escape(str(r['comp']))}</td>"
        f"<td><a href='{html.escape(blog_search_url(r['keyword']))}' target='_blank'>열기</a></td></tr>"
        for i, r in enumerate(rows, 1)
    )
    path.write_text(f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 블로그 키워드 {today}</title>
<style>
body {{ font-family: "Malgun Gothic", sans-serif; margin: 24px; color: #222; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }}
p.meta {{ color: #666; margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; max-width: 1000px; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: right; white-space: nowrap; }}
th {{ background: #f4f6f8; }}
td.kw, th.kw {{ text-align: left; font-weight: 600; }}
.up {{ color: #c0392b; }} .down {{ color: #2c6fbb; }}
</style></head><body>
<h1>오늘의 블로그 키워드 · {today}</h1>
<p class="meta">후보 {stats['candidates']}개 중 점수 상위 {len(rows)}개 · 기회 지수 = 월간 검색수 ÷ 블로그 문서 수 · 상승률 = 최근 7일 ÷ 이전 28일</p>
<table><tr><th>순위</th><th class="kw">키워드</th><th>월간 검색수</th><th>블로그 문서 수</th><th>기회 지수</th><th>7일 상승률</th><th>점수</th><th>광고 경쟁도</th><th>블로그 검색</th></tr>
{body}
</table></body></html>
""", encoding="utf-8")


def send_telegram(rows, today, keys):
    text = f"오늘의 블로그 키워드 ({today})\n" + "\n".join(
        f"{i}. {r['keyword']} · 검색 {r['volume']:,} · 점수 {r['score']}" for i, r in enumerate(rows, 1))
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
        print(f"  {i:>2}. {r['keyword']}  검색 {r['volume']:,} · 문서 {r['blog_total']:,} · "
              f"상승 {(r['growth'] - 1) * 100:+.0f}% · 점수 {r['score']}")


# ---------- 실행 ----------

def mark_written(words):
    db = open_db()
    today = date.today().isoformat()
    for w in words:
        db.execute("INSERT OR REPLACE INTO written VALUES (?, ?)", ("".join(w.split()), today))
    db.commit()
    print(f"작성 완료로 기록했습니다 (이후 추천에서 제외): {', '.join(words)}")


def run(today=None):
    today = today or date.today()
    config = load_config()
    seeds = load_seeds()
    keys = keywordstool.load_keys(required=keywordstool.REQUIRED_KEYS + naver_api.OPENAPI_KEYS)
    db = open_db()

    log(f"1/4 연관 키워드 수집 (씨앗 {len(seeds)}개)")
    found = collect_candidates(seeds, keys)
    banned = [b for b in config["banned_words"] if b]
    skip = excluded_keywords(db, today, config["exclude_recent_days"])
    pool = [
        (kw, vol, comp) for kw, (vol, comp) in found.items()
        if config["min_volume"] <= vol <= config["max_volume"]
        and kw not in skip and not any(b in kw for b in banned)
    ]
    pool.sort(key=lambda x: x[1], reverse=True)
    pool = pool[:config["candidate_limit"]]
    log(f"  연관 키워드 {len(found)}개 → 1차 필터 통과 {len(pool)}개")
    if not pool:
        sys.exit("[오류] 조건에 맞는 후보가 없습니다. config.json의 검색수 범위나 seeds.txt를 확인해 주세요.")

    words = [kw for kw, _, _ in pool]
    log(f"2/4 블로그 문서 수 조회 ({len(words)}개)")
    totals = fetch_blog_totals(words, keys)
    log("3/4 데이터랩 추세 조회")
    growth = fetch_growth(words, keys, today)

    rows = [
        {"keyword": kw, "volume": vol, "comp": comp, "blog_total": totals[kw],
         "opportunity": vol / max(totals[kw], 1), "growth": growth.get(kw, 1.0)}
        for kw, vol, comp in pool if kw in totals
    ]
    if not rows:
        sys.exit("[오류] 블로그 문서 수를 하나도 가져오지 못했습니다. NAVER_CLIENT_ID/SECRET을 확인해 주세요.")
    top = score_rows(rows, config["weights"])[:config["top_n"]]

    log("4/4 리포트 저장")
    REPORT_DIR.mkdir(exist_ok=True)
    html_path = REPORT_DIR / f"{today.isoformat()}.html"
    csv_path = REPORT_DIR / f"{today.isoformat()}.csv"
    write_html(top, html_path, today.isoformat(), {"candidates": len(rows)})
    write_csv(top, csv_path)
    db.executemany(
        "INSERT OR REPLACE INTO recommendations VALUES (?, ?, ?, ?, ?, ?)",
        [(today.isoformat(), r["keyword"], r["score"], r["volume"], r["blog_total"], r["growth"]) for r in top],
    )
    db.commit()

    print(f"\n오늘의 추천 키워드 {len(top)}개")
    print_rows(top)
    print(f"\n리포트: {html_path}\nCSV:    {csv_path}")

    if all(keys.get(k) for k in TELEGRAM_KEYS):
        send_telegram(top, today.isoformat(), keys)
    if config["open_report"]:
        webbrowser.open(html_path.as_uri())


def main():
    keywordstool.setup_console()
    parser = argparse.ArgumentParser(description="매일 블로그 추천 키워드 리포트")
    parser.add_argument("--written", nargs="+", metavar="키워드", help="이미 글을 쓴 키워드로 기록 (이후 추천 제외)")
    args = parser.parse_args()
    if args.written:
        mark_written(args.written)
    else:
        run()


if __name__ == "__main__":
    main()
