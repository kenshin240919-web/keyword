# keyword

네이버 API로 블로그 키워드를 찾는 도구입니다. 파이썬 표준 라이브러리만 사용합니다.

## 준비
`%USERPROFILE%\.config\naver-searchad.env`
```
NAVER_SEARCHAD_API_KEY=...       # 검색광고 API
NAVER_SEARCHAD_SECRET_KEY=...
NAVER_SEARCHAD_CUSTOMER_ID=...
NAVER_CLIENT_ID=...              # NAVER API HUB (네이버 클라우드 플랫폼: 블로그·카페 검색, 검색어 트렌드)
NAVER_CLIENT_SECRET=...
TELEGRAM_BOT_TOKEN=...           # 선택: 텔레그램 알림
TELEGRAM_CHAT_ID=...
```

## 사용법
| 명령 | 설명 |
| --- | --- |
| `python keywordstool.py "사주풀이,궁합"` | 키워드 검색수 조회 (최대 5개) |
| `python daily_keywords.py` | 작년 시즌(1년 전 기준 한 달 뒤 한 달) 검색수로 추천 10개 + 꼭 쓸 3개(★) → `reports\날짜.html`, `.csv` |
| `open_report.bat` 더블클릭 | 오늘 리포트 열기 (없으면 먼저 만듦) — **'오늘 썼어요' 버튼으로 작성 기록** |
| `python daily_keywords.py --refresh` | 오늘 결과를 버리고 새로 뽑기 (같은 날 다시 실행하면 첫 결과 유지) |
| `python daily_keywords.py --written 궁합` | 이미 쓴 키워드로 기록 (이후 추천 제외) |
| `python daily_keywords.py --unwritten 궁합` | 잘못 기록한 키워드 취소 |
| `setup_task.bat` 더블클릭 | 자동 실행 등록: 로그인할 때 + 매일 07:50 (하루 1번만) |

- 씨앗 키워드: `seeds.txt` (한 줄에 하나)
- 작년 시즌 검색수 = 현재 월 검색수 × 데이터랩 추이 비율 (추정값)
- 기회 지수 = 작년 시즌 검색수 ÷ (블로그 + 카페 글 수)
- 추천 키워드마다 실제로 검색되는 세부 키워드 3개를 함께 보여 줍니다
- 검색수 범위·가중치·추천 개수·꼭 쓸 개수(must_n)·금칙어: `config.json`
- 자동 실행 로그: `logs\daily.log`
- 리포트의 기록 버튼은 이 PC 안에서만 도는 작은 서버(`report_server.py`, 127.0.0.1:8765)를 통해 `history.db`에 저장됩니다. 6시간 동안 쓰지 않으면 스스로 꺼집니다.
