#!/usr/bin/env python3
"""블로그 썸네일 5장(블로그 1~4번 1080×1080, 워프 1400×800)을 만듭니다.

사용자가 만든 원본 썸네일 5장을 틀로 써서, 글자 부분만 지우고 새 글자를 원본과 같은
글씨체·색·크기·위치로 그립니다.
    상단: 메인 키워드 / 중앙: 클릭 유도 문구(5~6자) / 버튼: 바로 확인하기 · 바로 신청하기

준비 (thumbnail 폴더, git에는 올리지 않음):
    thumbnail/농업경영체등록_블로그 1번.png … _블로그 4번.png, _워프.png  (원본 틀, 이름 앞부분은 아무거나)
    thumbnail/Jalnan2.otf (여기어때 잘난체), thumbnail/BMDOHYEON_ttf.ttf (배달의민족 도현)

사용법:
    python thumbnail.py 농업경영체등록                # 중앙 문구는 Claude Code가 작성
    python thumbnail.py 농업경영체등록 "직장인도 가능?" 확인하기
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
ASSET_DIR = BASE_DIR / "thumbnail"
NAVY = "#141d50"

# 원본 틀에 들어 있는 글자 (지울 자리와 글자 크기를 재는 기준)
TEMPLATE_TEXT = {"top": "농업경영체등록", "mid": "직장인도 가능?", "btn": "바로 확인하기"}

# 원본에서 잰 값. box = 원본 글자(테두리 제외)의 왼쪽·위·오른쪽·아래 끝 픽셀.
# erase = 지울 줄의 위·아래 (그 줄은 배경색으로 칠함), outline = (테두리 색, 두께)
TEMPLATES = {
    "블로그 1번": {"size": (1080, 1080), "bg": "#feebb6", "font": "jalnan",
                "top": {"color": "#58ccff", "outline": (NAVY, 13), "box": (14, 83, 1072, 226), "erase": (60, 250)},
                "mid": {"color": "#fff200", "outline": (NAVY, 13), "box": (25, 398, 1072, 541), "erase": (375, 565)},
                "btn": {"color": "#ffffff", "fill": "#1187cf", "box": (44, 744, 812, 880)}},
    "블로그 2번": {"size": (1080, 1080), "bg": "#000000", "font": "jalnan",
                "top": {"color": "#ffffff", "outline": (NAVY, 14), "box": (19, 75, 1068, 216), "erase": (52, 240)},
                "mid": {"color": "#fcf630", "outline": None, "box": (21, 400, 1068, 543), "erase": (385, 560)},
                "btn": {"color": "#ffffff", "fill": "#fc5230", "box": (45, 783, 799, 915)}},
    "블로그 3번": {"size": (1080, 1080), "bg": "#b8e9ff", "font": "dohyeon",
                "top": {"color": "#0d33f6", "outline": None, "box": (19, 67, 1067, 224), "erase": (50, 245)},
                "mid": {"color": "#000000", "outline": None, "box": (20, 400, 1072, 553), "erase": (385, 570)},
                "btn": {"color": "#0d33f6", "fill": "#fd8a69", "box": (49, 758, 819, 895)}},
    "블로그 4번": {"size": (1080, 1080), "bg": "#e4f0d5", "font": "dohyeon",
                "top": {"color": "#9a30ae", "outline": None, "box": (15, 62, 1072, 220), "erase": (45, 240)},
                "mid": {"color": "#f63008", "outline": None, "box": (22, 402, 1074, 555), "erase": (385, 575)},
                "btn": {"color": "#9a30ae", "fill": "#ffff4a", "box": (48, 744, 819, 883)}},
    "워프": {"size": (1400, 800), "bg": "#b8e9ff", "font": "jalnan",
           "top": {"color": "#fff200", "outline": (NAVY, 18), "box": (25, 14, 1374, 196), "erase": (0, 228)},
           "mid": {"color": "#fd6f22", "outline": (NAVY, 17), "box": (78, 259, 1324, 429), "erase": (236, 455)},
           "btn": {"color": "#000000", "fill": "#fff16c", "box": (91, 517, 1023, 692)}},
}
MIN_SQUEEZE = 0.75   # 글자가 길면 가로로 이만큼까지 좁히고, 그래도 길면 글자 크기를 줄입니다.
MAX_GROW = 1.25      # 글자가 짧으면 원본처럼 가로를 채우도록 키우되, 원본 높이의 이 배수까지만.


def find_assets(asset_dir=ASSET_DIR):
    """틀 5장과 글씨체 2개를 찾습니다. 없으면 무엇이 없는지 알려 줍니다."""
    asset_dir = Path(asset_dir)
    templates = {}
    for name in TEMPLATES:
        hits = sorted(asset_dir.glob(f"*{name}.png"))
        if hits:
            templates[name] = hits[0]
    fonts = {
        "jalnan": next(iter(sorted(asset_dir.glob("*Jalnan2*.otf")) + sorted(asset_dir.glob("*Jalnan2*.ttf"))), None),
        "dohyeon": next(iter(sorted(asset_dir.glob("*DOHYEON*.tt*"))), None),
    }
    missing = [f"*{n}.png" for n in TEMPLATES if n not in templates] + \
              [{"jalnan": "Jalnan2.otf (잘난체)", "dohyeon": "BMDOHYEON_ttf.ttf (도현)"}[k] for k, v in fonts.items() if not v]
    if missing:
        raise FileNotFoundError(f"{asset_dir} 폴더에 다음 파일이 필요합니다: {', '.join(missing)}")
    return templates, fonts


def _font_size_for(font_path, text, height):
    """text의 글자 높이가 height가 되는 글씨 크기."""
    lo, hi = 10, 600
    while lo < hi:
        mid = (lo + hi) // 2
        b = ImageFont.truetype(str(font_path), mid).getbbox(text)
        lo, hi = (mid + 1, hi) if b[3] - b[1] < height else (lo, mid)
    return lo


def _text_layer(text, font, color, outline):
    """글자(+테두리)만 그린 투명 이미지와, 그 안에서 글자 본체가 차지하는 칸."""
    stroke_color, stroke = outline or (None, 0)
    b = font.getbbox(text)
    pad = stroke + 4
    layer = Image.new("RGBA", (b[2] - b[0] + pad * 2, b[3] - b[1] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((pad - b[0], pad - b[1]), text, font=font, fill=color,
                               stroke_width=stroke, stroke_fill=stroke_color)
    return layer, (pad, pad, pad + b[2] - b[0], pad + b[3] - b[1])


def _draw_line(img, text, ref_text, font_path, spec, align="center"):
    """원본 글자(ref_text)와 같은 글씨 크기·기준선으로 text를 그립니다."""
    x0, y0, x1, y1 = spec["box"]
    ref_w = x1 - x0
    size = _font_size_for(font_path, ref_text, y1 - y0)
    ref_font = ImageFont.truetype(str(font_path), size)
    rb = ref_font.getbbox(ref_text)
    ref_natural = rb[2] - rb[0]
    squeeze = min(1.0, ref_w / ref_natural)      # 원본도 가로로 살짝 좁혀져 있습니다
    baseline = y0 - rb[1]                        # 원본 글자 위끝 = 기준선 + bbox 위쪽
    center_y = (y0 + y1) / 2

    font = ref_font
    width = font.getbbox(text)[2] - font.getbbox(text)[0]
    fx = squeeze
    if width * fx > ref_w:                       # 원본보다 길면: 더 좁히고, 그래도 길면 작게
        fx = max(MIN_SQUEEZE, ref_w / width)
        if width * fx > ref_w:
            size = int(size * ref_w / (width * fx))
            font = ImageFont.truetype(str(font_path), size)
    elif align == "center" and width * fx < ref_w * 0.98:   # 원본보다 짧으면: 가로를 채우도록 키움
        grow = min(MAX_GROW, ref_w / (width * fx))
        size = int(size * grow)
        font = ImageFont.truetype(str(font_path), size)
    layer, inner = _text_layer(text, font, spec["color"], spec.get("outline"))
    tb = font.getbbox(text)
    if fx != 1.0:
        layer = layer.resize((max(1, round(layer.width * fx)), layer.height), Image.LANCZOS)
        inner = (inner[0] * fx, inner[1], inner[2] * fx, inner[3])
    # 세로: 원본과 같은 기준선(크기를 줄였으면 같은 가운데)에 맞춥니다.
    top = baseline + tb[1] if font is ref_font else center_y - (tb[3] - tb[1]) / 2
    if align == "left":
        left = x0
    else:
        left = (x0 + x1) / 2 - (inner[2] - inner[0]) / 2
    img.alpha_composite(layer, (round(left - inner[0]), round(top - inner[1])))


def render(keyword, phrase, button, out_dir, asset_dir=ASSET_DIR):
    """5장을 만들어 out_dir에 '{키워드}_블로그 N번.png', '{키워드}_워프.png'로 저장하고 경로를 돌려줍니다."""
    templates, fonts = find_assets(asset_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    button_text = f"바로 {button}"
    saved = {}
    for name, spec in TEMPLATES.items():
        img = Image.open(templates[name]).convert("RGBA")
        if img.size != spec["size"]:
            img = img.resize(spec["size"], Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        w = img.width
        for part in ("top", "mid"):                 # 원본 글자 줄을 배경색으로 지우기
            e0, e1 = spec[part]["erase"]
            draw.rectangle((0, e0, w, e1), fill=spec["bg"])
        bx0, by0, bx1, by1 = spec["btn"]["box"]     # 버튼 글자만 버튼색으로 지우기 (손가락은 그대로)
        draw.rectangle((bx0 - 6, by0 - 6, bx1 + 6, by1 + 6), fill=spec["btn"]["fill"])
        title_font, button_font = fonts[spec["font"]], fonts["dohyeon"]
        _draw_line(img, keyword, TEMPLATE_TEXT["top"], title_font, spec["top"])
        _draw_line(img, phrase, TEMPLATE_TEXT["mid"], title_font, spec["mid"])
        _draw_line(img, button_text, TEMPLATE_TEXT["btn"], button_font, spec["btn"], align="left")
        path = out_dir / f"{keyword}_{name}.png"
        img.convert("RGB").save(path)
        saved[name] = path
    return saved


# ---------- 중앙 문구 (Claude Code) ----------

PHRASE_PROMPT = """네이버 블로그 썸네일 문구를 만듭니다. 키워드: {keyword}
- phrase: 썸네일 가운데 줄. 사람들이 궁금해서 클릭하게 만드는 한국어 문구, 공백 제외 5~6자.
  예) 직장인도 가능?, 최대 얼마?, 놓치면 손해, 신청 전 필독, 이것만 확인
  키워드를 반복하지 말고, 사실과 다른 과장(무조건, 100% 등)은 쓰지 마세요.
- button: 신청·접수·지원을 받는 주제면 "신청하기", 조회·계산·정보 주제면 "확인하기".
JSON 한 줄만 출력하세요: {{"phrase": "...", "button": "확인하기"}}"""


def fallback_copy(keyword):
    button = "신청하기" if re.search(r"신청|접수|지원금|바우처|장려금|수당|대출|쿠폰", keyword) else "확인하기"
    return ("신청 전 필독" if button == "신청하기" else "이것만 확인"), button


def make_copy(keyword, claude_cmd="claude", timeout=120):
    """(중앙 문구, 버튼 말)을 Claude Code로 만듭니다. 실패하면 기본 문구를 씁니다."""
    exe = shutil.which(claude_cmd)
    if exe:
        try:
            p = subprocess.run([exe, "-p", "--output-format", "json"], input=PHRASE_PROMPT.format(keyword=keyword),
                               capture_output=True, text=True, encoding="utf-8", timeout=timeout)
            text = json.loads(p.stdout).get("result", "")
            data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            phrase = str(data.get("phrase", "")).strip()
            button = "신청하기" if str(data.get("button", "")).strip() == "신청하기" else "확인하기"
            if 4 <= len(phrase.replace(" ", "")) <= 7:
                return phrase, button
        except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
            pass
    return fallback_copy(keyword)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    keyword = "".join(sys.argv[1].split())
    if len(sys.argv) >= 4:
        phrase, button = sys.argv[2], sys.argv[3]
    else:
        phrase, button = make_copy(keyword)
    for name, path in render(keyword, phrase, button, BASE_DIR / "thumbnails").items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
