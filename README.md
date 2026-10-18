# keyword

네이버 API로 블로그 키워드를 찾는 도구입니다. 파이썬 표준 라이브러리만 사용합니다.

## 준비
`%USERPROFILE%\.config\naver-searchad.env`
```
NAVER_SEARCHAD_API_KEY=...       # 검색광고 API
NAVER_SEARCHAD_SECRET_KEY=...
NAVER_SEARCHAD_CUSTOMER_ID=...
NAVER_CLIENT_ID=...              # NAVER API HUB (네이버 클라우드 플랫폼)
NAVER_CLIENT_SECRET=...
TELEGRAM_BOT_TOKEN=...           # 선택: 텔레그램 알림
TELEGRAM_CHAT_ID=...
```

## 사용법
| 명령 | 설명 |
| --- | --- |
| `python keywordstool.py "사주풀이,궁합"` | 키워드 검색수 조회 (최대 5개) |
| `python daily_keywords.py` | 오늘의 추천 키워드 10개 → `reports\날짜.html`, `.csv` |
| `python daily_keywords.py --written 궁합` | 이미 쓴 키워드로 기록 (이후 추천 제외) |
| `python daily_keywords.py --unwritten 궁합` | 잘못 기록한 키워드 취소 |
| `setup_task.bat` 더블클릭 | 매일 07:50 자동 실행 등록 (작업 스케줄러) |

- 씨앗 키워드: `seeds.txt` (한 줄에 하나)
- 검색수 범위·가중치·추천 개수·금칙어: `config.json`
- 자동 실행 로그: `logs\daily.log`
