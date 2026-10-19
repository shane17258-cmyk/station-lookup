#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接把 outage.json 上傳到 GitHub（使用 GitHub Contents API，不需要安裝 Git）

Token 來源（依序尋找）：
  1. 環境變數 GITHUB_TOKEN
  2. 同資料夾的 github_token.txt（內容放 token 即可）
  3. .git/config 內 origin 的 remote URL（本機/OneDrive 已同步 .git 時）
"""
import os, sys, re, json, base64, time
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "outage.json")
GIT_CONFIG = os.path.join(BASE_DIR, ".git", "config")
TOKEN_FILE = os.path.join(BASE_DIR, "github_token.txt")
BRANCH = "master"


def parse_remote(url):
    """從 remote URL 取出 (token, owner/repo)"""
    if not url:
        return "", ""
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", url)
    repo = m.group(1) if m else ""
    tok = ""
    m2 = re.match(r"https://([^@]+)@github\.com/", url)
    if m2:
        cred = m2.group(1)
        tok = cred.split(":")[-1] if ":" in cred else cred
    return tok, repo


def find_credentials():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    if os.path.exists(TOKEN_FILE):
        t = open(TOKEN_FILE, encoding="utf-8", errors="ignore").read().strip()
        if t and not tok:
            tok = t
    url = ""
    if os.path.exists(GIT_CONFIG):
        txt = open(GIT_CONFIG, encoding="utf-8", errors="ignore").read()
        m = re.search(r"url\s*=\s*(\S+)", txt)
        if m:
            url = m.group(1)
    t2, r2 = parse_remote(url)
    if not tok:
        tok = t2
    if not repo:
        repo = r2
    return tok, repo


def main():
    if not os.path.exists(OUT):
        print("[錯誤] 找不到 outage.json", file=sys.stderr)
        return 1
    tok, repo = find_credentials()
    if not tok or not repo:
        print("[錯誤] 找不到 GitHub token 或 repo。", file=sys.stderr)
        print("請在同資料夾建立 github_token.txt，內容放你的 GitHub token。", file=sys.stderr)
        return 1

    api = "https://api.github.com/repos/" + repo + "/contents/outage.json"
    headers = {
        "Authorization": "Bearer " + tok,
        "Accept": "application/vnd.github+json",
        "User-Agent": "outage-push",
    }
    local = open(OUT, "rb").read()

    for attempt in range(1, 6):
        sha = None
        remote = None
        try:
            r = requests.get(api, headers=headers, timeout=30)
        except Exception as e:
            print(f"[{attempt}/5] 讀取遠端失敗：{e}", file=sys.stderr)
            time.sleep(3)
            continue
        if r.status_code == 200:
            j = r.json()
            sha = j.get("sha")
            try:
                remote = base64.b64decode(j.get("content", ""))
            except Exception:
                remote = None
        elif r.status_code != 404:
            print(f"[{attempt}/5] GitHub 回應 {r.status_code}：{r.text[:200]}", file=sys.stderr)
            time.sleep(3)
            continue

        if remote == local:
            print("遠端已是最新，無需上傳")
            return 0

        body = {
            "message": "chore: 本機台電查詢結果",
            "content": base64.b64encode(local).decode("ascii"),
            "branch": BRANCH,
        }
        if sha:
            body["sha"] = sha
        try:
            p = requests.put(api, headers=headers, json=body, timeout=30)
        except Exception as e:
            print(f"[{attempt}/5] 上傳失敗：{e}", file=sys.stderr)
            time.sleep(3)
            continue
        if p.status_code in (200, 201):
            print("已上傳 outage.json 到 GitHub")
            return 0
        print(f"[{attempt}/5] 上傳失敗 {p.status_code}：{p.text[:200]}", file=sys.stderr)
        time.sleep(3)

    print("[錯誤] 嘗試多次仍無法上傳", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
