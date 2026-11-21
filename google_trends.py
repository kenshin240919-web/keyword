#!/usr/bin/env python3
"""구글 트렌드 '지금 뜨는 검색어'(trends.google.com/trending)를 읽습니다.

따로 쓰기 (google_trends.bat 더블클릭과 같음):
    python google_trends.py                # 한국, 최근 48시간 → trends\\날짜_시각_KR_48h.html·.csv 저장 후 열기
    python google_trends.py --hours 168    # 최근 7일 (4, 24, 48, 168 가능)
    python google_trends.py --active       # 지금도 오르는 중인 것만
    python google_trends.py --all          # 글감 분야(GOOD_CATEGORIES) 말고 모든 분야
    python google_trends.py --no-open      # 파일만 저장

매일 리포트 연결: daily_keywords.py가 trend_seeds()로 글감 분야 트렌드를 씨앗에 더하고,
리포트에 '구글 트렌드 지금 뜨는 검색어' 칸을 붙입니다 (config.json "google_trends").

어떻게 가져오나:
    trending 페이지 HTML 안의 AF_initDataCallback({key: 'ds:0', ...}) 에 목록 전체가 들어 있습니다
    (REA로 페이지 네트워크를 잡아 확인, 2026-11-21). 로그인·API 키 없이 페이지 한 번만 받습니다.
    항목: [키워드, null, 나라, [시작 시각], [끝난 시각 또는 null=진행 중], null,
           검색량, null, 상승률(%), [연관 검색어...], [분야 번호...], [[뉴스 id, 언어, 나라]...], 키워드]
    구글이 페이지 구조를 바꾸면 깨질 수 있습니다. 그때는 공개 RSS(10개 정도, 분야 정보 없음)로 대신합니다.
"""
import argparse
import csv
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "trends"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"

# 구글 트렌드 분야 번호 (페이지의 '모든 카테고리' 메뉴)
CATEGORIES = {
    1: "자동차", 2: "뷰티·패션", 3: "비즈니스·금융", 4: "엔터테인먼트", 5: "음식·음료", 6: "게임",
    7: "건강", 8: "취미·여가", 9: "직업·교육", 10: "법·정부", 11: "기타", 13: "반려동물",
    14: "정치", 15: "과학", 16: "쇼핑", 17: "스포츠", 18: "기술", 19: "여행·교통", 20: "기후",
}
# 정보 글로 답할 수 있는 분야. 엔터·스포츠·정치·게임·기타는 사람 이름·경기·뉴스가 많아 하루 이틀이면 검색이 사라짐.
GOOD_CATEGORIES = ["자동차", "뷰티·패션", "비즈니스·금융", "음식·음료", "건강", "취미·여가", "직업·교육",
                   "법·정부", "반려동물", "쇼핑", "기술", "여행·교통", "기후"]


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def _ts(v):
    return datetime.fromtimestamp(v[0]).strftime("%Y-%m-%d %H:%M") if v else ""


def _from_page(geo, hours, hl):
    page = _fetch(f"https://trends.google.com/trending?geo={geo}&hl={hl}&hours={hours}")
    m = re.search(r"AF_initDataCallback\(\{key: 'ds:0', hash: '\d+', data:(.*?), sideChannel: \{\}\}\);</script>",
                  page, re.S)
    if not m:
        raise ValueError("페이지에서 트렌드 목록(ds:0)을 못 찾음 — 구글이 구조를 바꿨을 수 있음")
    out = []
    for it in json.loads(m.group(1))[1] or []:
        out.append({
            "keyword": it[0],
            "volume": it[6] or 0,
            "growth_pct": it[8] or 0,
            "active": it[4] is None,
            "started": _ts(it[3]),
            "categories": [CATEGORIES.get(c, str(c)) for c in it[10] or []],
            "related": it[9] or [],
        })
    return out


def _from_rss(geo):
    ns = {"ht": "https://trends.google.com/trending/rss"}
    root = ET.fromstring(_fetch(f"https://trends.google.com/trending/rss?geo={geo}"))
    return [{"keyword": i.findtext("title") or "",
             "volume": int(re.sub(r"\D", "", i.findtext("ht:approx_traffic", "", ns)) or 0),
             "growth_pct": 0, "active": True, "started": i.findtext("pubDate", ""), "categories": [], "related": []}
            for i in root.iter("item")]


def fetch_trends(geo="KR", hours=48, hl="ko"):
    """(트렌드 목록, 'page' 또는 'rss'). 검색량·상승률 큰 순. 둘 다 실패하면 예외."""
    try:
        rows, source = _from_page(geo, hours, hl), "page"
    except Exception:  # 페이지 구조가 바뀌었거나 일시 오류: RSS로
        rows, source = _from_rss(geo), "rss"
    rows.sort(key=lambda r: (r["volume"], r["growth_pct"]), reverse=True)
    return rows, source


def good(rows, categories=None, banned=()):
    """글감 분야에 하나라도 걸리고 금지어가 없는 트렌드."""
    cats = set(categories or GOOD_CATEGORIES)
    return [r for r in rows if cats & set(r["categories"]) and not any(b in r["keyword"] for b in banned if b)]


def trend_seeds(rows, limit=30):
    """씨앗용 키워드: 띄어쓰기를 붙이고(검색광고 API 형식) 한글·영문·숫자만, 2~20자."""
    seeds = []
    for r in rows:
        word = re.sub(r"[^0-9A-Za-z가-힣]", "", r["keyword"])
        if 2 <= len(word) <= 20 and word not in seeds:
            seeds.append(word)
        if len(seeds) >= limit:
            break
    return seeds


def naver_url(keyword):
    return "https://search.naver.com/search.naver?ssc=tab.blog.all&query=" + urllib.parse.quote(keyword)


def trends_url(keyword, geo="KR"):
    return f"https://trends.google.com/explore?geo={geo}&date=now%207-d&q=" + urllib.parse.quote(keyword)


def rows_html(rows, geo="KR"):
    """<table> 한 개: 키워드·검색량·상승률·분야·연관 검색어·링크. 매일 리포트와 따로 쓰기에서 같이 씀."""
    tr = "\n".join(
        f"<tr><td>{i}</td><td class='kw'>{'<span class=up title=지금도 오르는 중>▲</span> ' if r['active'] else ''}"
        f"{html.escape(r['keyword'])}<div class='details'>"
        + "".join(f"<span class='chip'>{html.escape(q)}</span>" for q in r["related"][1:9]) +
        f"</div></td><td>{r['volume']:,}+</td><td>{r['growth_pct']:,}%</td>"
        f"<td style='text-align:left'>{html.escape('/'.join(r['categories']))}</td><td>{html.escape(r['started'])}</td>"
        f"<td><a href='{html.escape(naver_url(r['keyword']))}' target='_blank'>네이버 블로그</a> · "
        f"<a href='{html.escape(trends_url(r['keyword'], geo))}' target='_blank'>구글 추이</a></td></tr>"
        for i, r in enumerate(rows, 1))
    return ("<table><tr><th>순위</th><th class='kw'>키워드 · 연관 검색어</th><th>구글 검색량</th><th>상승률</th>"
            "<th style='text-align:left'>분야</th><th>뜨기 시작</th><th>보기</th></tr>\n" + tr + "\n</table>")


PAGE_STYLE = """<style>
body { font-family: "Malgun Gothic", sans-serif; margin: 24px; color: #222; }
h1 { font-size: 22px; margin-bottom: 4px; } p.meta { color: #666; margin-top: 0; }
table { border-collapse: collapse; width: 100%; max-width: 1400px; }
th, td { border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: right; white-space: nowrap; }
th { background: #f4f6f8; } td.kw, th.kw { text-align: left; font-weight: 600; white-space: normal; min-width: 260px; }
.up { color: #c0392b; } .details { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.chip { font-size: 12.5px; font-weight: 500; background: #eef3fb; color: #1e4e8c; border-radius: 12px; padding: 2px 8px; }
</style>"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="구글 트렌드 지금 뜨는 검색어")
    p.add_argument("--geo", default="KR")
    p.add_argument("--hours", type=int, default=48, choices=[4, 24, 48, 168])
    p.add_argument("--hl", default="ko")
    p.add_argument("--active", action="store_true", help="지금도 오르는 중인 것만")
    p.add_argument("--all", action="store_true", help="모든 분야 (기본: 글감 분야만)")
    p.add_argument("--top", type=int, default=30, help="화면에 보여줄 개수")
    p.add_argument("--no-open", action="store_true", help="HTML을 브라우저로 열지 않음")
    a = p.parse_args()

    rows, source = fetch_trends(a.geo, a.hours, a.hl)
    total = len(rows)
    if not a.all:
        rows = good(rows)
    if a.active:
        rows = [r for r in rows if r["active"]]

    OUT_DIR.mkdir(exist_ok=True)
    stem = OUT_DIR / f"{datetime.now():%Y%m%d_%H%M}_{a.geo}_{a.hours}h"
    with open(stem.with_suffix(".csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["키워드", "구글 검색량", "상승률%", "진행중", "뜨기 시작", "분야", "연관 검색어"])
        for r in rows:
            w.writerow([r["keyword"], r["volume"], r["growth_pct"], "Y" if r["active"] else "",
                        r["started"], "/".join(r["categories"]), ", ".join(r["related"])])
    scope = "모든 분야" if a.all else "글감 분야(" + ", ".join(GOOD_CATEGORIES) + ")"
    note = "" if source == "page" else "<p class='meta' style='color:#c0392b'>페이지를 못 읽어 RSS로 대신했습니다 (분야 정보 없음 — --all 로 보세요).</p>"
    stem.with_suffix(".html").write_text(
        f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>구글 트렌드 {a.geo} {a.hours}시간</title>"
        f"{PAGE_STYLE}</head><body><h1>구글 트렌드 지금 뜨는 검색어 · {a.geo} 최근 {a.hours}시간</h1>"
        f"<p class='meta'>{datetime.now():%Y-%m-%d %H:%M} 기준 · 전체 {total}개 중 {scope} {len(rows)}개"
        f"{' · 지금도 오르는 것만' if a.active else ''} · ▲ = 지금도 오르는 중</p>{note}"
        f"{rows_html(rows, a.geo)}</body></html>\n", encoding="utf-8")

    print(f"{a.geo} 최근 {a.hours}시간 트렌드 {total}개 중 {len(rows)}개 ({source}) → {stem}.html\n")
    for r in rows[:a.top]:
        print(f"{'▲' if r['active'] else ' '} {r['volume']:>9,}+  {r['growth_pct']:>5}%  {r['keyword']}  "
              f"[{'/'.join(r['categories'])}]  {', '.join(r['related'][1:5])}")
    if not a.no_open:
        webbrowser.open(stem.with_suffix(".html").as_uri())


if __name__ == "__main__":
    main()
