# -*- coding: utf-8 -*-
"""
站台照片伺服器 (Photo Server) — Google Drive 版
================================================
透過 Google Drive API 存取雲端照片，所有同事隨時可看、不用開你的電腦。

使用前：
  1. 在 Google Cloud Console 建立 OAuth 2.0 用戶端（桌面應用程式）
  2. 用戶端 ID / Secret 填入下方 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
  3. 首次執行時會自動開啟瀏覽器授權（只需做一次，之後 token 自動存檔）
  4. 照片存在你的 Google Drive「苗栗市站台照片/<站台名>/」資料夾

用法：
  python photo_server.py [port]
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests

# 確保 stdout 能正確輸出中文（避免 cp950 編碼錯誤）
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load_dotenv(path=None):
    """若照片伺服器同層有 .env 檔，自動載入環境變數（純 Python，不依賴批次檔）。"""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8000

# ── Google Drive API 設定（從環境變數讀取，避免 secret 外洩）──
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_FOLDER_NAME = "苗栗市站台照片"
TOKEN_FILE = os.path.join(BASE, ".gdrive_tokens.json")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3"
# ────────────────────────────────────────────────────────────────

STATIC_FILES = {
    "index.html", "data.js", "data5g.js", "manifest.json",
    "sw.js", "icon-192.png", "icon-512.png", ".nojekyll",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/manifest+json; charset=utf-8",
    ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".gif": "image/gif", ".jpeg": "image/jpeg", ".jpg": "image/jpeg",
    ".bmp": "image/bmp", ".heic": "image/heic", ".heif": "image/heif",
    ".css": "text/css; charset=utf-8", ".txt": "text/plain; charset=utf-8",
}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
MAX_UPLOAD = 50 * 1024 * 1024

# ── Token / OAuth ──────────────────────────────────────────────

def load_tokens():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_tokens(tokens):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)


def refresh_access_token(tokens):
    """用 refresh_token 取新的 access_token。"""
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError("Refresh token 失敗: {0}".format(resp.text))
    data = resp.json()
    tokens["access_token"] = data["access_token"]
    tokens["expires_at"] = time.time() + data.get("expires_in", 3600) - 300
    save_tokens(tokens)
    return tokens


def get_valid_token():
    """取得有效的 access_token（必要時自動 refresh）。"""
    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        return None
    if tokens.get("expires_at", 0) < time.time():
        tokens = refresh_access_token(tokens)
    return tokens["access_token"]


def exchange_code(code):
    """用授權 code 換 access_token + refresh_token。"""
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": "http://localhost:{0}/callback".format(DEFAULT_PORT),
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError("換 token 失敗: {0}".format(resp.text))
    data = resp.json()
    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": time.time() + data.get("expires_in", 3600) - 300,
    }
    save_tokens(tokens)
    return tokens


# ── Google Drive API 操作 ──────────────────────────────────────

def drive_headers():
    token = get_valid_token()
    if not token:
        return None
    return {"Authorization": "Bearer " + token}


def drive_find_folder(name, parent_id="root"):
    """找已存在的資料夾，回傳 id 或 None。"""
    hdrs = drive_headers()
    if not hdrs:
        return None
    q = "mimeType='application/vnd.google-apps.folder' and name='{0}' and '{1}' in parents and trashed=false".format(
        name.replace("'", "\\'"), parent_id
    )
    resp = requests.get(
        GOOGLE_DRIVE_API + "/files",
        headers=hdrs,
        params={"q": q, "fields": "files(id,name)", "pageSize": "1"},
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def drive_create_folder(name, parent_id="root"):
    """建立資料夾，回傳 id。"""
    hdrs = drive_headers()
    if not hdrs:
        raise RuntimeError("未授權")
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    resp = requests.post(
        GOOGLE_DRIVE_API + "/files",
        headers=hdrs,
        json=body,
        params={"fields": "id"},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError("建立資料夾失敗: {0}".format(resp.text))
    return resp.json()["id"]


def drive_get_or_create_folder(name, parent_id="root"):
    """找或建資料夾，回傳 id。"""
    fid = drive_find_folder(name, parent_id)
    if fid:
        return fid
    return drive_create_folder(name, parent_id)


def drive_list_files(folder_id):
    """列出資料夾內的圖片，回傳 [{id, name}]。"""
    hdrs = drive_headers()
    if not hdrs:
        return []
    q = "'{0}' in parents and trashed=false and (mimeType contains 'image/')".format(folder_id)
    files = []
    page_token = None
    while True:
        params = {
            "q": q,
            "fields": "nextPageToken,files(id,name,mimeType)",
            "pageSize": "100",
            "orderBy": "name",
        }
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(
            GOOGLE_DRIVE_API + "/files",
            headers=hdrs, params=params, timeout=30,
        )
        if resp.status_code != 200:
            break
        data = resp.json()
        files.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return files


def drive_upload_file(folder_id, filename, data):
    """上傳檔案到指定資料夾，回傳檔名。"""
    hdrs = drive_headers()
    if not hdrs:
        raise RuntimeError("未授權")
    # 避免覆寫：若已存在同名檔先改名
    existing = {f["name"] for f in drive_list_files(folder_id)}
    name = os.path.basename(filename) or "photo.jpg"
    base, ext = os.path.splitext(name)
    final = name
    n = 1
    while final in existing:
        final = "{0} ({1}){2}".format(base, n, ext)
        n += 1
    # Resumable upload（適合大檔）
    metadata = {"name": final, "parents": [folder_id]}
    resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        headers=hdrs,
        params={"uploadType": "resumable", "fields": "id,name"},
        json=metadata,
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError("上傳 init 失敗: {0}".format(resp.text))
    upload_url = resp.headers.get("Location")
    resp2 = requests.put(
        upload_url,
        headers={"Content-Type": "application/octet-stream"},
        data=data,
        timeout=120,
    )
    if resp2.status_code not in (200, 201):
        raise RuntimeError("上傳失敗: {0}".format(resp2.text))
    return final


def drive_download_file(file_id):
    """下載檔案內容，回傳 bytes。"""
    hdrs = drive_headers()
    if not hdrs:
        raise RuntimeError("未授權")
    resp = requests.get(
        GOOGLE_DRIVE_API + "/files/" + file_id,
        headers=hdrs,
        params={"alt": "media"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError("下載失敗: {0}".format(resp.text))
    return resp.content


def drive_file_thumbnail(file_id):
    """取得縮圖（small），回傳 bytes 或 None。"""
    hdrs = drive_headers()
    if not hdrs:
        return None
    resp = requests.get(
        GOOGLE_DRIVE_API + "/files/" + file_id,
        headers=hdrs,
        params={"alt": "media"},
        timeout=30,
    )
    return resp.content if resp.status_code == 200 else None


# ── 站台照片邏輯 ──────────────────────────────────────────────

def sanitize_station(name):
    name = (name or "").strip()
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    if not cleaned:
        raise ValueError("站台名稱為空或無效")
    return cleaned


# 快取：station_name -> folder_id
_folder_cache = {}


def get_station_folder_id(station):
    """取得站台在 Drive 上的資料夾 id（快取）。"""
    if station in _folder_cache:
        return _folder_cache[station]
    root_id = drive_get_or_create_folder(DRIVE_FOLDER_NAME)
    folder_id = drive_get_or_create_folder(sanitize_station(station), root_id)
    _folder_cache[station] = folder_id
    return folder_id


def list_photos(station):
    """回傳 [{name, url, id}]，依檔名排序。"""
    try:
        folder_id = get_station_folder_id(station)
    except Exception:
        return []
    files = drive_list_files(folder_id)
    result = []
    for f in files:
        ext = os.path.splitext(f["name"])[1].lower()
        if ext not in ALLOWED_EXT:
            continue
        st = sanitize_station(station)
        url = "/photos/{0}/{1}".format(urllib.parse.quote(st), urllib.parse.quote(f["name"]))
        result.append({"name": f["name"], "url": url, "id": f["id"]})
    result.sort(key=lambda x: x["name"])
    return result


def upload_photo(station, filename, data):
    """上傳照片到 Drive，回傳檔名。"""
    folder_id = get_station_folder_id(station)
    return drive_upload_file(folder_id, filename, data)


def download_photo(station, filename):
    """從 Drive 下載照片 bytes，回傳 bytes 或 None。"""
    try:
        folder_id = get_station_folder_id(station)
    except Exception:
        return None
    for f in drive_list_files(folder_id):
        if f["name"] == filename:
            return drive_download_file(f["id"])
    return None


# ── HTTP Handler ───────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "PhotoServer/2.0"

    def log_message(self, fmt, *args):
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

    def _send_bytes(self, data, ctype="application/octet-stream"):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path):
        if not os.path.isfile(path):
            self._send_json({"ok": False, "error": "檔案不存在"}, 404)
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            data = f.read()
        self._send_bytes(data, ctype)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)

        # OAuth callback
        if path == "/callback":
            code = qs.get("code", [""])[0]
            if code:
                try:
                    exchange_code(code)
                    body = "<html><body><h2>授權成功！</h2><p>可以關閉此頁面，回到照片伺服器。</p></body></html>".encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    print("  [OK] Google Drive 授權成功！")
                except Exception as e:
                    body = ("<html><body><h2>授權失敗</h2><p>" + str(e) + "</p></body></html>").encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            else:
                error = qs.get("error", ["unknown"])[0]
                body = ("<html><body><h2>授權失敗</h2><p>" + error + "</p></body></html>").encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        # API：列出照片
        if path == "/api/photos":
            station = qs.get("station", [""])[0]
            try:
                station = sanitize_station(station)
            except ValueError:
                self._send_json({"ok": False, "error": "站台名稱無效"}, 400)
                return
            token = get_valid_token()
            if not token:
                self._send_json({"ok": False, "error": "未授權"}, 401)
                return
            try:
                photos = list_photos(station)
                self._send_json({"ok": True, "station": station, "photos": photos})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API：下載照片
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
            try:
                data = download_photo(station, filename)
                if data is None:
                    self._send_json({"ok": False, "error": "照片不存在"}, 404)
                    return
                ext = os.path.splitext(filename)[1].lower()
                ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
                self._send_bytes(data, ctype)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # 靜態檔
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
        token = get_valid_token()
        if not token:
            self._send_json({"ok": False, "error": "未授權，請先執行授權流程"}, 401)
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
            try:
                name = upload_photo(station, f["filename"], f["data"])
                saved.append(name)
            except Exception as e:
                return self._send_json({"ok": False, "error": "上傳失敗: {0}".format(e)}, 500)
        if not saved:
            self._send_json({"ok": False, "error": "沒有可儲存的檔案"}, 400)
            return
        self._send_json({"ok": True, "station": station, "saved": saved})


def parse_multipart(content_type, body):
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


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    # 檢查是否已授權
    token = get_valid_token()
    if not token:
        print("尚未授權 Google Drive，正在開啟瀏覽器...")
        auth_url = (
            "{0}?client_id={1}&redirect_uri={2}&response_type=code&scope={3}&access_type=offline&prompt=consent"
        ).format(
            GOOGLE_AUTH_URL,
            GOOGLE_CLIENT_ID,
            urllib.parse.quote("http://localhost:{0}/callback".format(port)),
            urllib.parse.quote(" ".join(GOOGLE_SCOPES)),
        )
        print("  請在瀏覽器中完成授權。")
        print("  授權網址：{0}".format(auth_url))
        # 開啟瀏覽器
        import webbrowser
        webbrowser.open(auth_url)
        print("  等待授權完成（在瀏覽器中按「允許」）...")
    else:
        print("  [OK] Google Drive 已授權")

    print("")
    print("站台照片伺服器已啟動 (Google Drive 模式)")
    print("  網址 : http://localhost:{0}".format(port))
    print("  照片目錄 : Google Drive > {0}".format(DRIVE_FOLDER_NAME))
    print("  按 Ctrl+C 停止")
    print("")

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()