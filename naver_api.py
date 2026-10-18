"""NAVER API HUB(네이버 클라우드 플랫폼)의 블로그 검색·검색어 트렌드 호출 모듈.

2026년 7월부터 신규 신청은 개발자센터가 아닌 NAVER API HUB에서 받습니다.
키 파일(~/.config/naver-searchad.env)에 API HUB에서 발급받은 값 두 줄이 필요합니다.
    NAVER_CLIENT_ID=...
    NAVER_CLIENT_SECRET=...

문서: https://api.ncloud-docs.com/docs/naver-api-hub-overview
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from keywordstool import ApiError

API_HUB = "https://naverapihub.apigw.ntruss.com"
DATALAB_URL = f"{API_HUB}/search-trend/v1/search"
BLOG_URL = f"{API_HUB}/search/v1/blog"
OPENAPI_KEYS = ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
DATALAB_MAX_GROUPS = 5


def _request(req):
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ApiError(f"API 요청 실패 (HTTP {e.code}): {body}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"네트워크 오류: {e.reason}") from None


def _headers(keys):
    return {
        "X-NCP-APIGW-API-KEY-ID": keys["NAVER_CLIENT_ID"],
        "X-NCP-APIGW-API-KEY": keys["NAVER_CLIENT_SECRET"],
    }


def blog_total(query, keys):
    """네이버 블로그 검색 결과의 전체 문서 수를 돌려줍니다."""
    url = f"{BLOG_URL}?{urllib.parse.urlencode({'query': query, 'display': 1})}"
    data = _request(urllib.request.Request(url, headers=_headers(keys)))
    return int(data.get("total", 0))


def datalab_daily(keywords, start_date, end_date, keys):
    """키워드별 일별 상대 검색량을 {키워드: {"YYYY-MM-DD": ratio}}로 돌려줍니다.

    한 번에 최대 5개. 값은 같은 요청 안에서의 상대값(최댓값 100)이며,
    검색량이 없는 날은 응답에서 빠질 수 있습니다.
    """
    if len(keywords) > DATALAB_MAX_GROUPS:
        raise ValueError(f"데이터랩은 한 번에 {DATALAB_MAX_GROUPS}개까지만 조회할 수 있습니다.")
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",
        "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
    }
    headers = {**_headers(keys), "Content-Type": "application/json"}
    req = urllib.request.Request(
        DATALAB_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    data = _request(req)
    return {
        r["title"]: {d["period"]: float(d["ratio"]) for d in r.get("data", [])}
        for r in data.get("results", [])
    }
