"""python test_seeds.py — 씨앗 읽기(월별 구역)와 RSS 제목 → 씨앗 변환 확인. 네트워크·API 안 씀."""
import daily_keywords as dk

text = "증여세\n# 메모\n#@11\n김장\n#@12\n크리스마스\n#@1\n설날\n"
assert dk.parse_seeds(text, 11) == ["증여세", "김장", "크리스마스"]
assert dk.parse_seeds(text, 12) == ["증여세", "크리스마스", "설날"]   # 12월 → 1월로 넘어감
assert dk.parse_seeds(text, 6) == ["증여세"]
assert dk.parse_seeds("정부지원금\n청년 지원금\n", 11) == ["정부지원금", "청년지원금"]  # 기존 seeds.txt 형식 그대로

assert dk.rss_title_seed("결혼자금 증여세, 1억5천만원 공제받는 조건") == "결혼자금증여세"
assert dk.rss_title_seed("11월초 터키 날씨, 지역별 기온") == "11월초터키날씨"
assert dk.rss_title_seed("?") is None

dk.use_profile("life")
assert dk.SEEDS_PATH.name == "seeds_life.txt" and dk.DB_PATH.name == "history_life.db"
config = dk.load_config()
assert config["top_n"] == 15
banned = config["banned_words"]
blocked = lambda kw: any(b in kw for b in banned)  # same test run() applies
assert all(blocked(k) for k in ["오늘주식시세", "실시간나스닥선물지수", "KODEX200선물인버스2X", "VOO", "홍콩달러환율"])
assert not any(blocked(k) for k in ["추석선물세트", "상속세면제한도", "코다리찜", "코인세탁방", "IRP"])
print("ok")
