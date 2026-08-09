# -*- coding: utf-8 -*-
"""
站台照片伺服器 (Photo Server)
=============================
在 OneDrive 資料夾內提供站台照片的上傳與瀏覽。

運作方式：
  - 照片存放在本機 OneDrive 資料夾「站台照片/<站台名>/」底下，
    因所在目錄本身就是 OneDrive 同步資料夾，上傳後會自動同步上雲端。
  - 前端（index.html）透過 CORS 呼叫本伺服器：
      GET  /api/photos?station=<站台名>   -> 列出照片
      GET  /photos/<站台名>/<檔名>        -> 讀取照片檔
      POST /api/upload                     -> 上傳照片（multipart）
  - 也可直接開 http://localhost:8000 瀏覽站台（伺服器同時提供頁面與資料）。

未來改用 Microsoft Graph（需 Azure App 憑證）時，只要把 _upload_file/_list_photos
兩支改寫為呼叫 Graph API 即可，前端不用改。

用法：
  python photo_server.py [port]
"""
import io
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PHOTO_ROOT = os.path.join(BASE, "站台照片")
DEFAULT_PORT = 8000

# 可直接使用的靜態檔（讓本機瀏覽也能完全運作）
STATIC_FILES = {
    "index.html",
    "data.js",
    "data5g.js",
    "manifest.json",
    "sw.js",
    "icon-192.png",
    "icon-512.png",
    ".nojekyll",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/manifest+json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".css": "text/css; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
MAX_UPLOAD = 50 * 1024 * 1024  # 單檔上限 50MB


def sanitize_station(name):
    """站台名轉成安全資料夾名稱：去除路徑與非法字元。"""
    name = (name or "").strip()
    # 去除可能的路徑穿越與作業系統非法字元
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    if not cleaned:
        raise ValueError("站台名稱為空或無效")
    return cleaned


def station_dir(station):
    return os.path.join(PHOTO_ROOT, sanitize_station(station))


def list_photos(station):
    """回傳 [{name, url}]，依檔名排序。"""
    folder = station_dir(station)
    if not os.path.isdir(folder):
        return []
    files = []
    for fn in sorted(os.listdir(folder)):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in ALLOWED_EXT:
            continue
        st = station
        url = "/photos/{0}/{1}".format(
            urllib.parse.quote(st), urllib.parse.quote(fn)
        )
        files.append({"name": fn, "url": url})
    return files


def unique_path(folder, filename):
    """避免覆寫同名檔，若已存在則自動加 (n) 後綴。"""
    base, ext = os.path.splitext(filename)
    target = os.path.join(folder, filename)
    n = 1
    while os.path.exists(target):
        target = os.path.join(folder, "{0} ({1}){2}".format(base, n, ext))
        n += 1
    return target


def _upload_file(station, filename, fileobj):
    """核心寫入：把檔案存到 OneDrive 的「站台照片/<站台名>/」。"""
    folder = station_dir(station)
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(filename) or "photo.jpg"
    target = unique_path(folder, name)
    with open(target, "wb") as f:
        while True:
            chunk = fileobj.read(65536)
            if not chunk:
                break
            f.write(chunk)
    return os.path.basename(target)


def parse_multipart(content_type, body):
    """手動剖析 multipart/form-data（僅 python 標準庫）。"""
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip('"')
            break
    if not boundary:
        raise ValueError("缺少 boundary")
    delim = b"--" + boundary.encode("utf-8", "surrogateescape")
    body = body.split(delim)
    fields = {}
    files = []
    for chunk in body[1:-1]:
        chunk = chunk.lstrip(b"\r\n")
        header_blob, _, data = chunk.partition(b"\r\n\r\n")
        if not data:
            continue
        header_txt = header_blob.decode("utf-8", "replace")
        disposition = ""
        for line in header_txt.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        m_name = re.search(r'name="([^"]*)"', disposition)
        m_file = re.search(r'filename="([^"]*)"', disposition)
        data = data.rstrip(b"\r\n")
        if not m_name:
            continue
        field = m_name.group(1)
        if m_file:
            files.append({"field": field, "filename": m_file.group(1), "data": data})
        else:
            fields[field] = data.decode("utf-8", "replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = "PhotoServer/1.0"

    def log_message(self, fmt, *args):  # 避免刷屏
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, status=200):
        blob = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _send_file(self, path):
        if not os.path.isfile(path):
            self._send_json({"ok": False, "error": "檔案不存在"}, 404)
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            self._send_json({"ok": False, "error": str(e)}, 500)
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/photos":
            station = qs.get("station", [""])[0]
            try:
                station = sanitize_station(station)
            except ValueError:
                self._send_json({"ok": False, "error": "站台名稱無效"}, 400)
                return
            self._send_json({"ok": True, "station": station, "photos": list_photos(station)})
            return

        if path.startswith("/photos/"):
            rel = path[len("/photos/"):]
            parts = rel.split("/", 1)
            if len(parts) != 2:
                self._send_json({"ok": False, "error": "路徑無效"}, 400)
                return
            station, filename = parts
            try:
                station = sanitize_station(station)
            except ValueError:
                self._send_json({"ok": False, "error": "站台名稱無效"}, 400)
                return
            target = os.path.join(station_dir(station), os.path.basename(filename))
            self._send_file(target)
            return

        # 靜態檔（本機瀏覽站台用）
        name = path.lstrip("/") or "index.html"
        if name in STATIC_FILES:
            self._send_file(os.path.join(BASE, name))
            return
        self._send_json({"ok": False, "error": "找不到"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if path != "/api/upload":
            self._send_json({"ok": False, "error": "找不到"}, 404)
            return
        station = qs.get("station", [""])[0]
        try:
            station = sanitize_station(station)
        except ValueError:
            self._send_json({"ok": False, "error": "站台名稱無效"}, 400)
            return

        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            self._send_json({"ok": False, "error": "沒有內容"}, 400)
            return
        body = self.rfile.read(min(length, MAX_UPLOAD * 4 + 65536))
        if not body:
            self._send_json({"ok": False, "error": "讀取內容失敗"}, 400)
            return
        try:
            fields, files = parse_multipart(ctype, body)
        except ValueError as e:
            self._send_json({"ok": False, "error": "解析失敗: {0}".format(e)}, 400)
            return

        saved = []
        for f in files:
            if len(f["data"]) > MAX_UPLOAD:
                return self._send_json(
                    {"ok": False, "error": "檔案 {0} 超過 {1}MB 限制".format(f["filename"], MAX_UPLOAD // (1024 * 1024))},
                    413,
                )
            io_ = io.BytesIO(f["data"])
            saved.append(_upload_file(station, f["filename"], io_))
        # 也接受非 multipart 的 raw body（可省略）
        if not files and ctype.startswith("image/"):
            saved.append(_upload_file(station, "photo-{0}.jpg".format(len(saved) + 1), io.BytesIO(body)))
        if not saved:
            self._send_json({"ok": False, "error": "沒有可儲存的檔案"}, 400)
            return
        self._send_json({"ok": True, "station": station, "saved": saved})


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    os.makedirs(PHOTO_ROOT, exist_ok=True)
    print("站台照片伺服器已啟動")
    print("  網址 : http://localhost:{0}".format(port))
    print("  照片目錄 : {0}".format(PHOTO_ROOT))
    print("  按 Ctrl+C 停止")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()