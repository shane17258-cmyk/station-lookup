/**
 * 國土測繪圖資服務雲（NLSC）地址定位代理 Worker
 * ==================================================
 * 用途：maps.nlsc.gov.tw 的地址搜尋 API（api.nlsc.gov.tw/idc/TextQueryMap）
 *       會檢查 Referer，只接受來自 maps.nlsc.gov.tw 的請求，
 *       瀏覽器無法偽造 Referer，因此由 Worker 代為加上 Referer 後轉發。
 *
 * 部署方式（不需要任何環境變數）：
 *   1. 執行 python deploy_nlsc_proxy.py（會讀 .cf_creds.json）
 *   2. 或 Cloudflare Dashboard → Workers & Pages → Create Worker
 *      名稱：nlsc-proxy，貼上本檔 → Deploy
 *
 * 端點：
 *   GET /q?addr=<地址>&cx=<TWD97 X>&cy=<TWD97 Y>
 *       → 回傳 NLSC 原始 XML（UTF-8，含 CORS）
 *   GET /ping → 檢查 Cloudflare 是否連得到 NLSC
 */

const UPSTREAM = 'https://api.nlsc.gov.tw/idc/TextQueryMap';
const REFERER = 'https://maps.nlsc.gov.tw/T09/mapshow.action';

// 苗栗縣附近（TWD97）；只影響 NLSC 的距離排序，不影響可搜尋範圍
const DEFAULT_CX = '241000';
const DEFAULT_CY = '2727000';

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,OPTIONS',
  'access-control-allow-headers': 'Content-Type',
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      ...CORS,
    },
  });
}

async function askNlsc(addr, cx, cy) {
  const url = `${UPSTREAM}/${encodeURIComponent(addr)}/10/${cx}/${cy}`;
  return fetch(url, {
    headers: {
      'Referer': REFERER,
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
      'Accept': 'application/xml,text/xml,*/*',
      'Accept-Language': 'zh-TW,zh;q=0.9',
    },
    cf: { cacheTtl: 3600, cacheEverything: true },
  });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (url.pathname === '/ping') {
      const t0 = Date.now();
      try {
        const r = await askNlsc('國華路600巷', DEFAULT_CX, DEFAULT_CY);
        const body = await r.text();
        return json({
          ok: r.ok && body.includes('<ITEM>'),
          status: r.status,
          items: (body.match(/<ITEM>/g) || []).length,
          ms: Date.now() - t0,
        });
      } catch (e) {
        return json({ ok: false, error: String((e && e.message) || e), ms: Date.now() - t0 }, 502);
      }
    }

    if (url.pathname !== '/q') {
      return json({ ok: false, error: 'nlsc proxy: use /q?addr=...' }, 404);
    }

    const addr = (url.searchParams.get('addr') || '').trim().slice(0, 60);
    if (!addr) return json({ ok: false, error: 'missing addr' }, 400);

    const cx = (url.searchParams.get('cx') || DEFAULT_CX).replace(/\D/g, '') || DEFAULT_CX;
    const cy = (url.searchParams.get('cy') || DEFAULT_CY).replace(/\D/g, '') || DEFAULT_CY;

    const t0 = Date.now();
    let resp;
    try {
      resp = await askNlsc(addr, cx, cy);
    } catch (e) {
      return json({ ok: false, error: 'upstream failed: ' + String((e && e.message) || e), ms: Date.now() - t0 }, 502);
    }

    const body = await resp.text();
    if (!resp.ok || body.includes('PERMISSION DENIED')) {
      return json({
        ok: false,
        status: resp.status,
        error: body.trim().slice(0, 80) || 'upstream error',
        ms: Date.now() - t0,
      }, 502);
    }

    return new Response(body, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml; charset=utf-8',
        'Cache-Control': 'public, max-age=3600',
        ...CORS,
      },
    });
  },
};
