/**
 * 台電查詢代理 Worker（Cloudflare Workers）
 * ==========================================
 * 用途：GitHub Actions（美國機房）連不到 service.taipower.com.tw（連線逾時），
 *       由 Cloudflare 邊緣節點代為連線台電官網，再把結果回傳。
 *
 * 部署方式（不需要任何環境變數）：
 *   1. Cloudflare Dashboard → Workers & Pages → Create → Worker
 *   2. 名稱：taipower-proxy
 *   3. 編輯程式碼，貼上本檔全部內容 → Deploy
 *   4. 部署後網址：https://taipower-proxy.<你的 workers.dev 子網域>.workers.dev
 *
 * 驗證：瀏覽器開 https://taipower-proxy.<子網域>.workers.dev/ping
 *       看到 {"ok":true,...} 表示 Cloudflare 連得到台電。
 *
 * 只轉發 /nds/ 路徑，其他路徑一律 404。
 */

const UPSTREAM = 'https://service.taipower.com.tw';

const STRIP_REQ = [
  'host', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade',
  'accept-encoding', 'content-length',
  'cf-connecting-ip', 'cf-ipcountry', 'cf-ray', 'cf-visitor',
  'x-forwarded-for', 'x-real-ip', 'x-forwarded-proto', 'x-forwarded-host',
];

const STRIP_RES = [
  'content-encoding', 'content-length', 'transfer-encoding',
  'connection', 'keep-alive', 'set-cookie',
];

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

// 台電設定的 cookie 帶 Domain=service.taipower.com.tw，
// 直傳會因網域不符被 requests 丟棄，這裡改寫成 host-only cookie。
function rewriteCookie(c) {
  return String(c)
    .replace(/;\s*domain=[^;]*/ig, '')
    .replace(/;\s*secure/ig, '');
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === '/ping') {
      const t0 = Date.now();
      try {
        const r = await fetch(UPSTREAM + '/nds/ndsWeb/ndft112.aspx', {
          method: 'GET',
          headers: { 'User-Agent': 'Mozilla/5.0' },
          redirect: 'follow',
        });
        return json({ ok: r.ok, status: r.status, ms: Date.now() - t0 });
      } catch (e) {
        return json({ ok: false, error: String(e && e.message || e), ms: Date.now() - t0 }, 502);
      }
    }

    if (!url.pathname.startsWith('/nds/')) {
      return new Response('taipower proxy: only /nds/ paths are proxied', { status: 404 });
    }

    const headers = new Headers(request.headers);
    for (const h of STRIP_REQ) headers.delete(h);

    const init = { method: request.method, headers, redirect: 'follow' };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      init.body = await request.arrayBuffer();
    }

    const t0 = Date.now();
    let resp;
    try {
      resp = await fetch(UPSTREAM + url.pathname + url.search, init);
    } catch (e) {
      return json({ ok: false, error: 'upstream failed: ' + String(e && e.message || e), ms: Date.now() - t0 }, 502);
    }

    const out = new Headers();
    resp.headers.forEach((v, k) => {
      if (STRIP_RES.includes(k)) return;
      out.set(k, v);
    });

    const setCookies = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [];
    if (setCookies.length) {
      for (const c of setCookies) out.append('set-cookie', rewriteCookie(c));
    } else {
      const c = resp.headers.get('set-cookie');
      if (c) out.set('set-cookie', rewriteCookie(c));
    }

    return new Response(resp.body, { status: resp.status, headers: out });
  },
};
