#!/usr/bin/env python3
"""네이버 검색광고 API(keywordstool)로 키워드 월간 검색수를 조회합니다.

사용법:
    python keywordstool.py "사주풀이,전생,궁합,신년운세,관상"
    python keywordstool.py 사주풀이 전생 궁합 -o result.json

키 파일: ~/.config/naver-searchad.env
    NAVER_SEARCHAD_API_KEY=...
    NAVER_SEARCHAD_SECRET_KEY=...
    NAVER_SEARCHAD_CUSTOMER_ID=...

외부 패키지 없이 파이썬 표준 라이브러리만 사용합니다.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_URL = "https://api.searchad.naver.com"
URI = "/keywordstool"
ENV_PATH = Path.home() / ".config" / "naver-searchad.env"
REQUIRED_KEYS = (
    "NAVER_SEARCHAD_API_KEY",
    "NAVER_SEARCHAD_SECRET_KEY",
    "NAVER_SEARCHAD_CUSTOMER_ID",
)
MAX_HINTS = 5
TOP_N = 20


class ApiError(Exception):
    """API 요청 실패. 메시지에 키 값은 들어가지 않습니다."""


def setup_console():
    """윈도우 콘솔에서 한글이 깨지지 않도록 UTF-8로 맞춥니다."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_keys(path=ENV_PATH, required=REQUIRED_KEYS):
    """env 파일에서 키를 읽습니다. 값은 절대 출력하지 않습니다."""
    if not path.exists():
        sys.exit(f"[오류] 키 파일이 없습니다: {path}")
    keys = {}
    # utf-8-sig: 메모장으로 저장해 BOM이 붙은 경우도 처리
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        keys[name] = value.strip().strip('"').strip("'")
    missing = [k for k in required if not keys.get(k)]
    if missing:
        sys.exit(f"[오류] 키 파일에 다음 항목이 없습니다: {', '.join(missing)}")
    return keys


def sign(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def normalize_hints(raw_args):
    """쉼표/공백으로 받은 키워드를 띄어쓰기 없이 정리하고 최대 5개로 제한합니다."""
    hints = []
    for arg in raw_args:
        for word in arg.split(","):
            word = "".join(word.split())
            if word and word not in hints:
                hints.append(word)
    if not hints:
        sys.exit("[오류] 키워드를 1개 이상 입력해 주세요.")
    if len(hints) > MAX_HINTS:
        print(f"[안내] 키워드는 최대 {MAX_HINTS}개까지 가능해 앞의 {MAX_HINTS}개만 사용합니다: {', '.join(hints[:MAX_HINTS])}")
        hints = hints[:MAX_HINTS]
    return hints


def fetch_keywords(hints, keys):
    timestamp = str(int(time.time() * 1000))
    headers = {
        "X-Timestamp": timestamp,
        "X-API-KEY": keys["NAVER_SEARCHAD_API_KEY"],
        "X-Customer": str(keys["NAVER_SEARCHAD_CUSTOMER_ID"]),
        "X-Signature": sign(timestamp, "GET", URI, keys["NAVER_SEARCHAD_SECRET_KEY"]),
    }
    query = urllib.parse.urlencode({"hintKeywords": ",".join(hints), "showDetail": "1"})
    req = urllib.request.Request(f"{BASE_URL}{URI}?{query}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ApiError(f"API 요청 실패 (HTTP {e.code}): {body}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"네트워크 오류: {e.reason}") from None


def to_count(value):
    """'<10'은 5로, 숫자/문자열 숫자는 int로 변환합니다."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if text.startswith("<"):
        return 5
    try:
        return int(float(text))
    except ValueError:
        return 0


def display_width(text):
    """한글 등 전각 문자는 2칸으로 계산합니다."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(text))


def pad(text, width, align="left"):
    text = str(text)
    space = " " * max(0, width - display_width(text))
    return text + space if align == "left" else space + text


def print_table(rows):
    headers = ["순위", "키워드", "PC", "모바일", "합계", "경쟁도"]
    aligns = ["right", "left", "right", "right", "right", "left"]
    table = [
        [str(i), r["keyword"], f"{r['pc']:,}", f"{r['mobile']:,}", f"{r['total']:,}", r["comp"]]
        for i, r in enumerate(rows, 1)
    ]
    widths = [max(display_width(h), *(display_width(row[c]) for row in table)) for c, h in enumerate(headers)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(sep)
    print("| " + " | ".join(pad(h, widths[c], aligns[c]) for c, h in enumerate(headers)) + " |")
    print(sep)
    for row in table:
        print("| " + " | ".join(pad(v, widths[c], aligns[c]) for c, v in enumerate(row)) + " |")
    print(sep)


def main():
    setup_console()
    parser = argparse.ArgumentParser(description="네이버 검색광고 키워드 검색수 조회")
    parser.add_argument("keywords", nargs="+", help='키워드 (예: "사주풀이,전생,궁합")')
    parser.add_argument("-o", "--output", help="저장할 JSON 파일 경로 (기본: keywords_날짜시간.json)")
    args = parser.parse_args()

    hints = normalize_hints(args.keywords)
    keys = load_keys()
    print(f"조회 키워드: {', '.join(hints)}")

    try:
        data = fetch_keywords(hints, keys)
    except ApiError as e:
        sys.exit(f"[오류] {e}")

    output = Path(args.output or f"keywords_{datetime.now():%Y%m%d_%H%M%S}.json")
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = []
    for item in data.get("keywordList", []):
        pc = to_count(item.get("monthlyPcQcCnt", 0))
        mobile = to_count(item.get("monthlyMobileQcCnt", 0))
        rows.append({
            "keyword": item.get("relKeyword", ""),
            "pc": pc,
            "mobile": mobile,
            "total": pc + mobile,
            "comp": item.get("compIdx", ""),
        })
    rows.sort(key=lambda r: r["total"], reverse=True)

    print(f"전체 {len(rows)}개 연관 키워드 중 상위 {min(TOP_N, len(rows))}개 (PC+모바일 월간 검색수, '<10'은 5로 계산)")
    print_table(rows[:TOP_N])
    print(f"JSON 저장 완료: {output.resolve()}")


if __name__ == "__main__":
    main()
