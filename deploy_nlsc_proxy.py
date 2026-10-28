# -*- coding: utf-8 -*-
"""
部署 NLSC 地址定位代理 Worker 到 Cloudflare Workers。

會讀取 .cf_creds.json（CF_API_TOKEN / CF_ACCOUNT_ID），不需要 Node 或 wrangler。

執行：
  python deploy_nlsc_proxy.py
"""
import json
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_NAME = "nlsc-proxy"
WORKER_FILE = os.path.join(BASE, "nlsc-proxy-worker.js")
API = "https://api.cloudflare.com/client/v4/accounts/{0}/workers"


def load_cf_creds():
    token = os.environ.get("CF_API_TOKEN", "")
    account = os.environ.get("CF_ACCOUNT_ID", "")
    path = os.path.join(BASE, ".cf_creds.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                creds = json.load(f)
            token = token or creds.get("CF_API_TOKEN", "")
            account = account or creds.get("CF_ACCOUNT_ID", "")
        except Exception:
            pass
    return token, account


def main():
    import requests

    token, account = load_cf_creds()
    if not token or not account:
        print("[ERR] 找不到 CF_API_TOKEN / CF_ACCOUNT_ID（.cf_creds.json 或環境變數）")
        sys.exit(1)

    with open(WORKER_FILE, "r", encoding="utf-8") as f:
        code = f.read()

    base = API.format(account)
    headers = {"Authorization": "Bearer " + token}

    print("[1/3] 上傳 Worker 程式碼 ...")
    metadata = {"main_module": "nlsc-proxy-worker.js", "compatibility_date": "2024-01-01"}
    resp = requests.put(
        base + "/scripts/" + SCRIPT_NAME,
        headers=headers,
        files=[
            ("metadata", ("metadata.json", json.dumps(metadata), "application/json")),
            ("nlsc-proxy-worker.js", ("nlsc-proxy-worker.js", code.encode("utf-8"), "application/javascript+module")),
        ],
        timeout=60,
    )
    print("      HTTP", resp.status_code)
    if resp.status_code not in (200, 201):
        print("     ", resp.text[:600])
        sys.exit(1)

    print("[2/3] 啟用 workers.dev 子網域路由 ...")
    resp = requests.post(
        base + "/scripts/" + SCRIPT_NAME + "/subdomain",
        headers={**headers, "Content-Type": "application/json"},
        json={"enabled": True},
        timeout=60,
    )
    print("      HTTP", resp.status_code)

    print("[3/3] 查詢 workers.dev 網址 ...")
    sub = account
    try:
        r = requests.get(
            "https://api.cloudflare.com/client/v4/accounts/" + account + "/workers/subdomain",
            headers=headers,
            timeout=60,
        )
        if r.ok:
            sub = r.json().get("result", {}).get("subdomain") or sub
    except Exception:
        pass

    url = "https://{0}.{1}.workers.dev".format(SCRIPT_NAME, sub)
    print("[OK] 部署完成")
    print("     Worker 網址: {0}".format(url))
    print("     驗證：{0}/ping".format(url))


if __name__ == "__main__":
    main()
