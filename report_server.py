#!/usr/bin/env python3
"""리포트를 보여 주고 '오늘 썼어요'·'블로그에 보내기' 버튼을 처리하는, 이 PC 전용 작은 웹 서버.

'블로그에 보내기'는 Blog Automator 허브(127.0.0.1:37321)의 POST /api/jobs 로
블로그별 키워드를 넘깁니다. 사이드패널의 '블로그별 글 작성 → 임시저장'과 같은 요청입니다.
같은 버튼은 자동 포스팅 프로그램(autopost, 127.0.0.1:8777)의 POST /api/jobs 로도 메인 키워드와
이미지 폴더의 이미지를 넘겨 guidejung·gov 사이트 포스팅을 시작합니다 (화면의 '포스팅 시작'과 같은 요청).

사용법:
    python report_server.py          # (서버가 꺼져 있으면 켜고) 최신 리포트를 브라우저로 엽니다
    python report_server.py --serve  # 서버만 실행 (보통 직접 쓸 일 없음)

127.0.0.1(이 PC)에서만 접속되며, 6시간 동안 사용이 없으면 스스로 꺼집니다.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import daily_keywords as dk

try:
    import thumbnail      # Pillow가 없으면 썸네일만 빼고 나머지는 그대로 동작합니다.
except ImportError:
    thumbnail = None
import keywordstool

HOST = "127.0.0.1"
PORT = 8765
IDLE_LIMIT = 6 * 3600
REPORT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.(html|csv)$")
BASE_URL = f"http://{HOST}:{PORT}"
# 서버 코드를 바꾸면 올립니다. 예전 버전 서버가 떠 있으면 끄고 새로 켭니다.
SERVER_VERSION = 5
BLOGAUTO_URL = "http://127.0.0.1:37321"
BLOGAUTO_JOBS_URL = f"{BLOGAUTO_URL}/api/jobs"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def find_image(keyword, image_dir):
    """키워드와 이름이 같은 이미지, 없으면 폴더에 이미지가 딱 1장일 때 그 이미지."""
    folder = Path(image_dir)
    if not folder.is_dir():
        return None
    images = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    named = [p for p in images if dk.normalize(p.stem) == dk.normalize(keyword)]
    if named:
        return named[0]
    return images[0] if len(images) == 1 else None


def archive_image(path):
    """쓴 이미지는 다음에 다시 잡히지 않도록 '사용완료' 폴더로 옮깁니다."""
    done = path.parent / "사용완료"
    done.mkdir(exist_ok=True)
    target = done / path.name
    if target.exists():
        target = done / f"{path.stem}_{time.strftime('%Y%m%d%H%M%S')}{path.suffix}"
    path.replace(target)


def _get_json(url, headers=None, down_message=""):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        raise RuntimeError(down_message) from None


def check_blogauto():
    _get_json(f"{BLOGAUTO_URL}/api/status", {"X-Blogauto": "1"},
              "Blog Automator 프로그램이 꺼져 있습니다. 실행.bat으로 켠 뒤 다시 눌러 주세요.")


def autopost_settings(url):
    """autopost에 저장된 기본값(사이트·발행 방식·실행 방식). 꺼져 있으면 RuntimeError."""
    state = _get_json(f"{url}/api/state", down_message="자동 포스팅 프로그램(8777)이 꺼져 있습니다. "
                                                     "autopost 폴더의 start.bat으로 켠 뒤 다시 눌러 주세요.")
    return state.get("settings") or {}


def send_to_autopost(url, keyword, image, settings):
    """메인 키워드 하나를 포스팅 대기열에 넣습니다. image가 없으면 이미지 없이 올라갑니다.
    A·B 버튼은 비워서 AI가 만들게 합니다."""
    body = {
        "keywords": keyword,
        "images": [{"name": image.name, "data": base64.b64encode(image.read_bytes()).decode("ascii")}] if image else [],
        "a_buttons": [], "b_buttons": [], "b_common": False,
        "b_site": settings.get("b_site") or "guidejung|publish",
        "a_site": settings.get("a_site") or "gov|publish",
        # 예약 실행은 시각이 필요하므로, 키워드 리포트에서 보낼 때는 즉시 실행합니다.
        "mode": settings.get("mode") if settings.get("mode") in ("now", "sequential") else "now",
        "interval": settings.get("interval") or 0,
    }
    req = urllib.request.Request(f"{url}/api/jobs", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")).get("queued", 0)
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read().decode("utf-8")).get("error", "")
        except ValueError:
            message = ""
        raise RuntimeError(message or f"자동 포스팅 프로그램 오류 (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError):
        raise RuntimeError("자동 포스팅 프로그램(8777)에 연결하지 못했습니다.") from None


def send_to_blogauto(keywords, thumbnails=None):
    """블로그 1~4번에 키워드를 하나씩 넘깁니다. thumbnails = {블로그 번호: 썸네일 경로} (노란 표 바로 아래에 들어감).
    만들어진 작업 수를 돌려줍니다."""
    payload = {"keywords": {str(i): k for i, k in enumerate(keywords, 1)}}
    if thumbnails:
        payload["thumbnails"] = {str(i): str(p) for i, p in thumbnails.items()}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # 허브는 크롬 확장 요청만 받습니다. Origin 없이 X-Blogauto 헤더를 붙이면 확장과 같은 방식으로 받아 줍니다.
    req = urllib.request.Request(BLOGAUTO_JOBS_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Blogauto": "1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return len(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read().decode("utf-8")).get("error", "")
        except ValueError:
            message = ""
        raise RuntimeError(message or f"Blog Automator 오류 (HTTP {e.code})") from None
    except urllib.error.URLError:
        raise RuntimeError("Blog Automator 프로그램이 꺼져 있습니다. 실행.bat으로 켠 뒤 다시 눌러 주세요.") from None


def latest_report():
    reports = sorted(dk.REPORT_DIR.glob("*.html"))
    return reports[-1].name if reports else None


class Handler(BaseHTTPRequestHandler):
    last_seen = time.time()

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _written(self):
        db = dk.open_db()
        try:
            return dk.written_keywords(db)
        finally:
            db.close()

    def _sent(self):
        db = dk.open_db()
        try:
            return dk.sent_keywords(db)
        finally:
            db.close()

    def _check_keywords(self, body):
        keywords = body.get("keywords")
        if (not isinstance(keywords, list) or not 1 <= len(keywords) <= 4
                or not all(isinstance(k, str) and 0 < len(k.strip()) <= 100 for k in keywords)):
            return None
        return [k.strip() for k in keywords]

    def _plan(self, keywords, with_copy=False):
        """보내기 전에 확인할 것: 사이트 자동 포스팅 이미지, 썸네일을 만들 수 있는지와 그 문구."""
        config = dk.load_config()
        plan, image = {"autopost": False}, None
        if config["autopost_enabled"]:
            # 직접 넣은 이미지가 있으면 그걸 쓰고, 없으면 만든 워프 썸네일(또는 이미지 없이)로 발행합니다.
            image = find_image(keywords[0], config["image_dir"])
            plan = {"autopost": True, "image": image.name if image else "", "image_dir": str(config["image_dir"])}
        plan["thumb"] = None
        if config["thumbnails_enabled"] and thumbnail is None:
            plan["thumb_note"] = "Pillow가 설치되어 있지 않습니다. 명령 프롬프트에서 'pip install pillow'를 실행하세요."
        elif config["thumbnails_enabled"]:
            try:
                thumbnail.find_assets(config["thumbnail_dir"])
                if with_copy:
                    phrase, button = thumbnail.make_copy(keywords[0])
                    plan["thumb"] = {"phrase": phrase, "button": button}
                else:
                    plan["thumb"] = {}
            except FileNotFoundError as e:
                plan["thumb_note"] = str(e)
        return plan, image

    def _post(self, body, preview=False):
        keywords = self._check_keywords(body)
        if not keywords:
            return self._json(400, {"error": "키워드는 1~4개여야 합니다."})
        config = dk.load_config()
        try:
            plan, image = self._plan(keywords, with_copy=preview)
            if preview:
                return self._json(200, plan)
            use_autopost = plan["autopost"]
            # 둘 중 하나만 올라가는 일이 없도록, 보내기 전에 두 프로그램이 켜져 있는지 먼저 확인합니다.
            check_blogauto()
            settings = autopost_settings(config["autopost_url"]) if use_autopost else None
            thumbs = {}
            if plan["thumb"] is not None:
                phrase = str(body.get("phrase") or "").strip()
                button = "신청하기" if body.get("button") == "신청하기" else "확인하기"
                if not phrase:
                    phrase, button = thumbnail.fallback_copy(keywords[0])
                thumbs = thumbnail.render(keywords[0], phrase, button, config["thumbnail_out"], config["thumbnail_dir"])
            naver_thumbs = {i: thumbs[f"블로그 {i}번"] for i in range(1, len(keywords) + 1) if f"블로그 {i}번" in thumbs}
            jobs = send_to_blogauto(keywords, naver_thumbs)
        except RuntimeError as e:
            return self._json(502, {"error": str(e)})
        except (OSError, ValueError) as e:
            return self._json(500, {"error": f"썸네일을 만들지 못했습니다: {e}"})
        db = dk.open_db()
        try:
            dk.add_sent(db, keywords[0])
        finally:
            db.close()
        result = {"jobs": jobs, "sent": self._sent(), "autopost": 0, "thumbs": len(thumbs)}
        if use_autopost:
            site_image = image or thumbs.get("워프")
            try:
                result["autopost"] = send_to_autopost(config["autopost_url"], keywords[0], site_image, settings)
                result["image"] = site_image.name if site_image else ""
                if image:
                    archive_image(image)
                    result["archived"] = True
            except RuntimeError as e:
                result["warning"] = f"네이버 블로그로는 보냈지만, 사이트 자동 포스팅은 실패했습니다: {e}"
        self._json(200, result)

    def do_GET(self):
        Handler.last_seen = time.time()
        path = self.path.split("?", 1)[0]
        if path == "/api/ping":
            return self._json(200, {"ok": True, "version": SERVER_VERSION})
        if path == "/api/written":
            return self._json(200, {"keywords": self._written()})
        if path == "/api/sent":
            return self._json(200, {"keywords": self._sent()})
        if path == "/":
            name = latest_report()
            if not name:
                return self._send(200, "<meta charset='utf-8'>아직 리포트가 없습니다.", "text/html; charset=utf-8")
            return self._send(302, b"", extra={"Location": f"/reports/{name}"})
        if path.startswith("/reports/"):
            name = path[len("/reports/"):]
            file = dk.REPORT_DIR / name
            if REPORT_NAME.match(name) and file.is_file():
                ctype = "text/html; charset=utf-8" if name.endswith(".html") else "text/csv; charset=utf-8"
                return self._send(200, file.read_bytes(), ctype)
        self._json(404, {"error": "not found"})

    def do_POST(self):
        Handler.last_seen = time.time()
        # 다른 웹사이트가 몰래 기록을 바꾸지 못하도록, 리포트 페이지만 붙이는 헤더를 요구합니다.
        if self.path not in ("/api/written", "/api/post", "/api/post-plan", "/api/shutdown") or self.headers.get("X-Report-App") != "1":
            return self._json(403, {"error": "forbidden"})
        if self.path == "/api/shutdown":
            self._json(200, {"ok": True})
            return threading.Thread(target=self.server.shutdown, daemon=True).start()
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path in ("/api/post", "/api/post-plan"):
                return self._post(body, preview=self.path == "/api/post-plan")
            keyword = dk.normalize(body.get("keyword", ""))
        except (ValueError, AttributeError):
            return self._json(400, {"error": "bad request"})
        if not keyword or len(keyword) > 100:
            return self._json(400, {"error": "bad keyword"})
        db = dk.open_db()
        try:
            if body.get("done"):
                dk.add_written(db, keyword)
            else:
                dk.remove_written(db, keyword)
        finally:
            db.close()
        self._json(200, {"keywords": self._written()})


def serve():
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    def watchdog():
        while time.time() - Handler.last_seen < IDLE_LIMIT:
            time.sleep(60)
        server.shutdown()

    threading.Thread(target=watchdog, daemon=True).start()
    server.serve_forever()


def running_version():
    """떠 있는 서버의 버전 (예전 서버는 0). 서버가 없으면 None."""
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/ping", timeout=1) as resp:
            return json.loads(resp.read().decode("utf-8")).get("version", 0)
    except Exception:
        return None


def is_running():
    return running_version() == SERVER_VERSION


def stop_old_server():
    req = urllib.request.Request(f"{BASE_URL}/api/shutdown", data=b"{}", method="POST",
                                 headers={"X-Report-App": "1", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).close()
    except Exception:
        pass
    for _ in range(30):
        if running_version() is None:
            return True
        time.sleep(0.1)
    return False


def start_background():
    """서버가 꺼져 있으면 창 없이 백그라운드로 켭니다. 켜져 있으면 True."""
    version = running_version()
    if version == SERVER_VERSION:
        return True
    if version is not None and not stop_old_server():
        dk.log("[경고] 예전 리포트 서버가 꺼지지 않습니다. PC를 다시 시작하거나 "
               "'taskkill /f /im pythonw.exe'를 실행한 뒤 다시 열어 주세요.")
        return False
    script = str(Path(__file__).resolve())
    if sys.platform == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw if pythonw.exists() else sys.executable)
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        # 작업 스케줄러가 끝날 때 함께 꺼지지 않도록 가능하면 작업 그룹에서 분리합니다.
        for flags in (base | subprocess.CREATE_BREAKAWAY_FROM_JOB, base):
            try:
                subprocess.Popen([exe, script, "--serve"], cwd=str(dk.BASE_DIR), creationflags=flags,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except OSError:
                continue
    else:
        subprocess.Popen([sys.executable, script, "--serve"], cwd=str(dk.BASE_DIR), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if is_running():
            return True
        time.sleep(0.1)
    return False


def open_report(name=None):
    """리포트를 엽니다. 서버를 켤 수 없으면 기록 버튼 없이 파일로 엽니다."""
    name = name or latest_report()
    if start_background():
        webbrowser.open(f"{BASE_URL}/reports/{name}" if name else BASE_URL)
    elif name:
        dk.log("[경고] 기록 서버를 켜지 못해 리포트를 파일로 엽니다 ('오늘 썼어요' 버튼은 동작하지 않음).")
        webbrowser.open((dk.REPORT_DIR / name).as_uri())


def main():
    keywordstool.setup_console()
    parser = argparse.ArgumentParser(description="리포트 보기 + '오늘 썼어요' 기록 서버")
    parser.add_argument("--serve", action="store_true", help="서버만 실행")
    args = parser.parse_args()
    if args.serve:
        serve()
    else:
        open_report()


if __name__ == "__main__":
    main()
