import json, re, urllib.request, urllib.parse, sys, webbrowser, http.server, threading, time

env = open(r'C:\Users\shane\OneDrive - Chunghwa Telecom Co., Ltd\苗栗市站台\.env', encoding='utf-8').read()
def g(k):
    m = re.search(r'^' + k + r'=(.+)$', env, re.M)
    return m.group(1).strip() if m else ''

cid = g('GOOGLE_CLIENT_ID')
cs = g('GOOGLE_CLIENT_SECRET')
redirect_uri = 'http://localhost:18932'
scopes = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive',
]
auth_url = (
    'https://accounts.google.com/o/oauth2/v2/auth?'
    + urllib.parse.urlencode({
        'client_id': cid,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(scopes),
        'access_type': 'offline',
        'prompt': 'consent',
    })
)

code_result = {'code': None}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        if 'code' in params:
            code_result['code'] = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('✅ 授權成功！請回到命令列繼續。'.encode('utf-8'))
        else:
            self.send_response(400)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('❌ 授權失敗：' + str(params).encode('utf-8'))
    def log_message(self, format, *args):
        pass

server = http.server.HTTPServer(('localhost', 18932), Handler)
thread = threading.Thread(target=server.handle_request, daemon=True)
thread.start()

print("即將開啟瀏覽器，請登入 Google 帳號並授權。")
print("授權後會自動跳轉，命令列將繼續執行。\n")
print("若瀏覽器未自動開啟，請手動開啟以下網址：")
print(auth_url)
print()
webbrowser.open(auth_url)

print("等待授權中...", end='', flush=True)
for _ in range(120):
    if code_result['code']:
        break
    time.sleep(1)
    print('.', end='', flush=True)

if not code_result['code']:
    print("\n❌ 超時未取得授權碼，請重新執行。")
    sys.exit(1)

code = code_result['code']
print("\n取得授權碼，正在換取 token...")

token_data = urllib.parse.urlencode({
    'code': code,
    'client_id': cid,
    'client_secret': cs,
    'redirect_uri': redirect_uri,
    'grant_type': 'authorization_code',
}).encode()

req = urllib.request.Request(
    'https://oauth2.googleapis.com/token',
    data=token_data,
    headers={'Content-Type': 'application/x-www-form-urlencoded'},
)
resp = json.loads(urllib.request.urlopen(req, timeout=30).read())

if 'refresh_token' not in resp:
    print("失敗:", resp)
    sys.exit(1)

tokens = {
    'refresh_token': resp['refresh_token'],
    'access_token': resp.get('access_token', ''),
    'token_type': resp.get('token_type', ''),
    'scope': resp.get('scope', ''),
}
out = r'C:\Users\shane\OneDrive - Chunghwa Telecom Co., Ltd\苗栗市站台\.gdrive_tokens.json'
json.dump(tokens, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print("✅ token 已更新:", out)
print("refresh_token:", resp['refresh_token'][:20] + "...")
print("\n請執行 python deploy_worker.py 將新 token 部署到 Cloudflare Worker")