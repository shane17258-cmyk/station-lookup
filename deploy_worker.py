# -*- coding: utf-8 -*-
"""
部署站台照片 Worker 到 Cloudflare Workers（直接用 Cloudflare API，不需要 Node/wrangler）。

前置準備：
  1. 在 Cloudflare Dashboard > My Profile > API Tokens 建立 Token，
     權限需含：Account > Workers Scripts > Edit；Account > Workers Scripts > KV Storage > Edit（若有）
  2. 將 Token 與 Account ID 填入下面的 CF_API_TOKEN / CF_ACCOUNT_ID

執行：
  python deploy_worker.py
"""
import io
import json
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_NAME = "station-photo"
WORKER_FILE = os.path.join(BASE, "worker.js")
ENV_FILE = os.path.join(BASE, ".env")

# ========== 填入你的 Cloudflare 憑證（或直接寫入 .cf_creds.json） ==========
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
# ===============================================================


def load_cf_creds():
    creds_file = os.path.join(BASE, ".cf_creds.json")
    if os.path.isfile(creds_file):
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_dotenv(path=ENV_FILE):
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def cf(method, url, token, body=None, content_type=None, raw_text=False):
    import urllib.request
    headers = {"Authorization": "Bearer " + token}
    if content_type:
        headers["Content-Type"] = content_type
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    global CF_API_TOKEN, CF_ACCOUNT_ID
    creds = load_cf_creds()
    CF_API_TOKEN = CF_API_TOKEN or creds.get("CF_API_TOKEN", "")
    CF_ACCOUNT_ID = CF_ACCOUNT_ID or creds.get("CF_ACCOUNT_ID", "")
    if not CF_API_TOKEN or not CF_ACCOUNT_ID:
        print("[ERR] 請先設定 CF_API_TOKEN 與 CF_ACCOUNT_ID")
        print("     方式一：編輯 deploy_worker.py 最上方變數")
        print("     方式二：執行前設定環境變數 (PowerShell)：")
        print('     $env:CF_API_TOKEN="..." ; $env:CF_ACCOUNT_ID="..."')
        sys.exit(1)

    env = load_dotenv()
    client_id = env.get("GOOGLE_CLIENT_ID", "")
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "")

    token_file = os.path.join(BASE, ".gdrive_tokens.json")
    refresh_token = ""
    if os.path.isfile(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                refresh_token = json.load(f).get("refresh_token", "")
        except Exception:
            refresh_token = ""

    if not client_id or not client_secret or not refresh_token:
        print("[ERR] 缺少 .env 的 GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET 或 .gdrive_tokens.json 的 refresh_token")
        sys.exit(1)

    base_url = "https://api.cloudflare.com/client/v4/accounts/{0}/workers".format(CF_ACCOUNT_ID)

    # 1. 上傳 Worker 程式碼（ES module 需用 multipart + metadata）
    print("[1/3] 上傳 Worker 程式碼 ...")
    with open(WORKER_FILE, "r", encoding="utf-8") as f:
        code = f.read()
    metadata = {"main_module": "worker.js", "compatibility_date": "2024-01-01"}
    import requests
    resp = requests.put(
        base_url + "/scripts/" + SCRIPT_NAME,
        headers={"Authorization": "Bearer " + CF_API_TOKEN},
        files=[
            ("metadata", ("metadata.json", json.dumps(metadata), "application/json")),
            ("worker.js", ("worker.js", code.encode("utf-8"), "application/javascript+module")),
        ],
        timeout=60,
    )
    print("     上傳結果 HTTP", resp.status_code)
    if resp.status_code not in (200, 201):
        print("     ", resp.text[:500])
        sys.exit(1)
    data = resp.json()
    print("      改動 ID:", data.get("result", {}).get("id", ""))

    # 2. 設定環境變數（secrets）
    print("[2/3] 設定環境變數 (secrets) ...")
    secrets = {
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
        "GOOGLE_REFRESH_TOKEN": refresh_token,
    }
    for name, val in secrets.items():
        resp = requests.put(
            base_url + "/scripts/" + SCRIPT_NAME + "/secrets",
            headers={"Authorization": "Bearer " + CF_API_TOKEN,
                     "Content-Type": "application/json"},
            json={"name": name, "text": val, "type": "secret_text"},
            timeout=60,
        )
        print("     {0}: HTTP {1}".format(name, resp.status_code))
        if resp.status_code not in (200, 201):
            print("      ", resp.text[:300])

    # 3. 取得 workers.dev 網址
    print("[3/3] 查詢 workers.dev 子網域 ...")
    sub = CF_ACCOUNT_ID
    try:
        resp = requests.get(
            "https://api.cloudflare.com/client/v4/accounts/" + CF_ACCOUNT_ID + "/workers/subdomain",
            headers={"Authorization": "Bearer " + CF_API_TOKEN},
            timeout=60,
        )
        if resp.ok:
            sub = resp.json().get("result", {}).get("subdomain") or sub
    except Exception:
        pass
    url = "https://{0}.{1}.workers.dev".format(SCRIPT_NAME, sub)
    print("[OK] 部署完成")
    print("     Worker 網址: {0}".format(url))


if __name__ == "__main__":
    main()