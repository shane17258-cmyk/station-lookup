#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接把 outage.json 上傳到 GitHub（使用 GitHub Contents API，不需要安裝 Git）

Token 來源（依序尋找）：
  1. 環境變數 GITHUB_TOKEN
  2. 使用者家目錄的 .github_token（建議放這裡，不會同步到 OneDrive）
  3. 同資料夾的 github_token.txt
  4. 這台電腦 Git 已登入的憑證（開啟終端機跑過一次 git push 就會有）
  5. .git/config 內 origin 的 remote URL（舊版寫法）
"""
import os, sys, re, json, base64, time, shutil, subprocess
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "outage.json")
GIT_CONFIG = os.path.join(BASE_DIR, ".git", "config")
TOKEN_FILE = os.path.join(BASE_DIR, "github_token.txt")
USER_TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".github_token")
DEFAULT_REPO = "shane17258-cmyk/station-lookup"
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


def find_git():
    """找出這台電腦的 git（Windows 不一定在 PATH）"""
    p = shutil.which("git")
    if p:
        return p
    for c in (r"C:\Program Files\Git\cmd\git.exe",
              r"C:\Program Files (x86)\Git\cmd\git.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")):
        if os.path.exists(c):
            return c
    return ""


def token_from_git_credential():
    """向 Git 憑證管理員（GCM）要 GitHub 憑證，取回 OAuth token"""
    git = find_git()
    if not git:
        return ""
    try:
        env = dict(os.environ, GCM_INTERACTIVE="Never")
        r = subprocess.run([git, "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20, env=env)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    for line in r.stdout.splitlines():
        if line.startswith("password="):
            tok = line[9:].strip()
            if re.match(r"^(gho_|ghp_|ghu_|ghs_|github_pat_)", tok):
                return tok
    return ""


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except OSError:
        return ""


def find_credentials():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    if not tok:
        tok = read_text(USER_TOKEN_FILE)
    if not tok:
        tok = read_text(TOKEN_FILE)
    url = ""
    if os.path.exists(GIT_CONFIG):
        m = re.search(r"url\s*=\s*(\S+)", read_text(GIT_CONFIG))
        if m:
            url = m.group(1)
    t2, r2 = parse_remote(url)
    if not tok:
        tok = t2
    if not tok:
        tok = token_from_git_credential()
    if not repo:
        repo = r2 or DEFAULT_REPO
    return tok, repo


def main():
    if not os.path.exists(OUT):
        print("[錯誤] 找不到 outage.json", file=sys.stderr)
        return 1
    tok, repo = find_credentials()
    if not tok or not repo:
        print("[錯誤] 找不到 GitHub 登入資訊。", file=sys.stderr)
        print("請任選一種方式（只需做一次）：", file=sys.stderr)
        print("  1) 這台電腦用 Git 登入一次：開「命令提示字元」執行", file=sys.stderr)
        print("     在本資料夾執行 git push → 會跳出登入視窗，登入後即可", file=sys.stderr)
        print("  2) 建立 %USERPROFILE%\\.github_token，內容放 GitHub token", file=sys.stderr)
        print("     （Fine-grained token，只給 station-lookup 的 Contents: Read and write）", file=sys.stderr)
        print("  3) 在本資料夾建立 github_token.txt，內容放同一個 token", file=sys.stderr)
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
        elif r.status_code in (401, 403):
            print(f"[錯誤] GitHub 拒絕登入（{r.status_code}），憑證可能過期或權限不足。", file=sys.stderr)
            print("       請重新執行 git push 登入一次，或更新 token（需 Contents: Read and write）。", file=sys.stderr)
            return 1
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
        if p.status_code in (401, 403):
            print(f"[錯誤] 上傳被拒絕（{p.status_code}）：{p.text[:200]}", file=sys.stderr)
            print("       憑證權限不足或已過期，請重新登入 git 或更新 token。", file=sys.stderr)
            return 1
        print(f"[{attempt}/5] 上傳失敗 {p.status_code}：{p.text[:200]}", file=sys.stderr)
        time.sleep(3)

    print("[錯誤] 嘗試多次仍無法上傳", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
