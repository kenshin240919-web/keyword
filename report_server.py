#!/usr/bin/env python3
"""리포트를 보여 주고 '오늘 썼어요' 버튼 기록을 받는, 이 PC 전용 작은 웹 서버.

사용법:
    python report_server.py          # (서버가 꺼져 있으면 켜고) 최신 리포트를 브라우저로 엽니다
    python report_server.py --serve  # 서버만 실행 (보통 직접 쓸 일 없음)

127.0.0.1(이 PC)에서만 접속되며, 6시간 동안 사용이 없으면 스스로 꺼집니다.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import daily_keywords as dk
import keywordstool

HOST = "127.0.0.1"
PORT = 8765
IDLE_LIMIT = 6 * 3600
REPORT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.(html|csv)$")
BASE_URL = f"http://{HOST}:{PORT}"


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

    def do_GET(self):
        Handler.last_seen = time.time()
        path = self.path.split("?", 1)[0]
        if path == "/api/ping":
            return self._json(200, {"ok": True})
        if path == "/api/written":
            return self._json(200, {"keywords": self._written()})
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
        if self.path != "/api/written" or self.headers.get("X-Report-App") != "1":
            return self._json(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
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


def is_running():
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/ping", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_background():
    """서버가 꺼져 있으면 창 없이 백그라운드로 켭니다. 켜져 있으면 True."""
    if is_running():
        return True
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
