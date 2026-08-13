/**
 * 站台照片 Worker (Cloudflare Workers)
 * =====================================
 * 本機伺服器 photo_server.py 的雲端版：
 *   - 持有 Google OAuth secrets + refresh token（存於 Worker 環境變數）
 *   - 負責 列出 / 下載 / 上傳 照片到 Google Drive「苗栗市站台照片/<站台>/」
 *   - 僅允許「苗栗市」鄉鎮的站台（資料來源：GitHub 上的 data.js / data5g.js）
 *
 * 環境變數（Worker secrets）：
 *   GOOGLE_CLIENT_ID      — OAuth 用戶端 ID
 *   GOOGLE_CLIENT_SECRET  — OAuth 用戶端 Secret
 *   GOOGLE_REFRESH_TOKEN  — 授權後取得的 refresh token
 *   ALLOWED_ORIGIN        — 允許的前端來源（如 https://shane17258-cmyk.github.io）
 *
 * 部署：
 *   wrangler deploy worker.js --name station-photo
 *   或 Cloudflare Dashboard 新 Worker → 貼上程式碼 → 設定 Variables/Secrets
 */

const DRIVE_FOLDER_NAME = '苗栗市站台照片';
const ALLOWED_TOWN = '苗栗市';
const DRIVE_API = 'https://www.googleapis.com/drive/v3';
const DRIVE_UPLOAD_API = 'https://www.googleapis.com/upload/drive/v3/files';
const TOKEN_URL = 'https://oauth2.googleapis.com/token';
const MAX_UPLOAD = 50 * 1024 * 1024;
const DATA_URLS = [
  'https://raw.githubusercontent.com/shane17258-cmyk/station-lookup/master/data.js',
  'https://raw.githubusercontent.com/shane17258-cmyk/station-lookup/master/data5g.js',
];
const CONTENT_TYPES = {
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
  '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
  '.heic': 'image/heic', '.heif': 'image/heif',
};
const ALLOWED_EXT = Object.keys(CONTENT_TYPES);

// ── 記憶體快取（isolate 內有效）─────────────────────────────
let tokenCache = null;          // { token, expiresAt }
let stationCache = null;        // { at, set }
let folderCache = {};           // station -> folder_id

// ── 工具 ───────────────────────────────────────────────────

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...headers },
  });
}

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function sanitizeStation(name) {
  let s = String(name || '').trim();
  s = s.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_');
  s = s.replace(/_+/g, '_').replace(/^[ ._]+|[ ._]+$/g, '');
  return s;
}

// ── Token ──────────────────────────────────────────────────

async function getAccessToken(env) {
  if (tokenCache && tokenCache.expiresAt > Date.now()) return tokenCache.token;
  if (!env.GOOGLE_REFRESH_TOKEN) throw new Error('缺少 GOOGLE_REFRESH_TOKEN');
  const body = new URLSearchParams();
  body.set('client_id', env.GOOGLE_CLIENT_ID);
  body.set('client_secret', env.GOOGLE_CLIENT_SECRET);
  body.set('refresh_token', env.GOOGLE_REFRESH_TOKEN);
  body.set('grant_type', 'refresh_token');
  const resp = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  const data = await resp.json();
  if (!resp.ok || !data.access_token) {
    throw new Error('Google refuse token: ' + (data.error_description || data.error || resp.status));
  }
  tokenCache = {
    token: data.access_token,
    expiresAt: Date.now() + ((data.expires_in || 3600) - 60) * 1000,
  };
  return tokenCache.token;
}

async function driveFetch(token, url, opts = {}) {
  const resp = await fetch(url, {
    ...opts,
    headers: { Authorization: 'Bearer ' + token, ...(opts.headers || {}) },
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error('Drive API ' + resp.status + ': ' + txt.slice(0, 300));
  }
  return resp;
}

// ── 允許站台清單（苗栗市）──────────────────────────────────

async function loadAllowedStations() {
  if (stationCache && (Date.now() - stationCache.at) < 60 * 60 * 1000) {
    return stationCache.set;
  }
  const allowed = new Set();
  for (const url of DATA_URLS) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) continue;
      const text = await resp.text();
      const start = text.indexOf('[');
      const end = text.lastIndexOf(']');
      if (start < 0 || end <= start) continue;
      const arr = JSON.parse(text.slice(start, end + 1));
      for (const item of arr) {
        const stations = item.stations || [];
        const towns = item.towns || [];
        stations.forEach((st, i) => {
          const town = towns[i] || item.town || '';
          if (town.trim() === ALLOWED_TOWN) {
            allowed.add(sanitizeStation(st));
          }
        });
      }
    } catch (e) {
      // 單一來源失敗時跳過
    }
  }
  stationCache = { at: Date.now(), set: allowed };
  return allowed;
}

async function isAllowedStation(station) {
  const allowed = await loadAllowedStations();
  return allowed.has(sanitizeStation(station));
}

// ── Drive 資料夾 ───────────────────────────────────────────

async function driveFindFolder(token, name, parentId = 'root', mime = 'application/vnd.google-apps.folder') {
  const q = "name='" + name.replace(/'/g, "\\'") + "' and mimeType='" + mime +
    "' and trashed=false and '" + parentId + "' in parents";
  const url = DRIVE_API + '/files?q=' + encodeURIComponent(q) +
    '&pageSize=1&fields=files(id,name)';
  const resp = await driveFetch(token, url);
  const data = await resp.json();
  return data.files && data.files.length ? data.files[0].id : null;
}

async function driveCreateFolder(token, name, parentId) {
  const resp = await driveFetch(token, DRIVE_API + '/files?fields=id', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      mimeType: 'application/vnd.google-apps.folder',
      parents: [parentId],
    }),
  });
  const data = await resp.json();
  return data.id;
}

async function driveGetOrCreateFolder(token, name, parentId) {
  let id = await driveFindFolder(token, name, parentId);
  if (!id) id = await driveCreateFolder(token, name, parentId);
  return id;
}

async function getStationFolderId(env, token, station) {
  const key = station + '|' + token.slice(0, 8);
  if (folderCache[key]) return folderCache[key];
  const root = await driveGetOrCreateFolder(token, DRIVE_FOLDER_NAME, 'root');
  const folder = await driveGetOrCreateFolder(token, sanitizeStation(station), root);
  folderCache[key] = folder;
  return folder;
}

// ── 列出 / 下載 / 上傳 ─────────────────────────────────────

async function driveListPhotos(token, folderId) {
  const url = DRIVE_API + '/files?q=' + encodeURIComponent(
    "'" + folderId + "' in parents and trashed=false and mimeType contains 'image/'"
  ) + '&pageSize=1000&orderBy=name&fields=files(id,name)';
  const resp = await driveFetch(token, url);
  const data = await resp.json();
  return data.files || [];
}

async function listPhotos(env, station) {
  if (!(await isAllowedStation(station))) return [];
  const token = await getAccessToken(env);
  const folderId = await getStationFolderId(env, token, station);
  const files = await driveListPhotos(token, folderId);
  const st = sanitizeStation(station);
  const result = [];
  for (const f of files) {
    const ext = '.' + String(f.name).split('.').pop().toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) continue;
    result.push({
      name: f.name,
      url: '/photos/' + encodeURIComponent(st) + '/' + encodeURIComponent(f.name),
      id: f.id,
    });
  }
  result.sort((a, b) => a.name.localeCompare(b.name));
  return result;
}

async function downloadPhoto(env, station, filename) {
  if (!(await isAllowedStation(station))) return null;
  const token = await getAccessToken(env);
  const folderId = await getStationFolderId(env, token, station);
  const files = await driveListPhotos(token, folderId);
  const hit = files.find(f => f.name === filename);
  if (!hit) return null;
  const resp = await driveFetch(token, DRIVE_API + '/files/' + hit.id + '?alt=media');
  const buf = await resp.arrayBuffer();
  return { data: buf, size: buf.byteLength };
}

async function uploadPhotos(env, station, files) {
  if (!(await isAllowedStation(station))) {
    return { error: '此站台不開放照片功能（僅苗栗市站台可用）', status: 403 };
  }
  const token = await getAccessToken(env);
  const folderId = await getStationFolderId(env, token, station);

  // 避免覆寫：取目前已存在檔名
  const existing = new Set((await driveListPhotos(token, folderId)).map(f => f.name));

  const saved = [];
  for (const entry of files) {
    const name = String(entry.name).split(/[\/\\]/).pop() || 'photo.jpg';
    if (name.length > 0 && !ALLOWED_EXT.includes('.' + name.split('.').pop().toLowerCase())) continue;
    const arr = new Uint8Array(await entry.arrayBuffer());
    if (arr.byteLength > MAX_UPLOAD) {
      return { error: '檔案 ' + name + ' 超過 50MB 限制', status: 413 };
    }
    let final = name;
    const base = name.replace(/\.[^.]*$/, '');
    const ext = /(\.[^.]*)$/.exec(name) ? /(\.[^.]*)$/.exec(name)[1] : '';
    let n = 1;
    while (existing.has(final)) {
      final = base + ' (' + n + ')' + ext;
      n += 1;
    }
    existing.add(final);
    const finalName = await uploadOne(token, folderId, final, arr);
    saved.push(finalName);
  }
  return { saved };
}

async function uploadOne(token, folderId, name, bytes) {
  const init = await driveFetch(token, DRIVE_UPLOAD_API +
    '?uploadType=resumable&fields=id,name', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, parents: [folderId] }),
  });
  const uploadUrl = init.headers.get('Location');
  if (!uploadUrl) throw new Error('上傳初始化失敗');
  const put = await fetch(uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: bytes,
  });
  if (!put.ok) throw new Error('上傳失敗: ' + put.status);
  const data = await put.json();
  return data.name || name;
}

// ── HTTP Handler ───────────────────────────────────────────

async function handleRequest(request, env) {
  const url = new URL(request.url);
  const path = decodeURIComponent(url.pathname);
  const origin = request.headers.get('Origin') || '';
  const allowedOrigin = env.ALLOWED_ORIGIN || '*';
  const cors = corsHeaders(allowedOrigin);

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: cors });
  }

  try {
    // 列出照片
    if (request.method === 'GET' && path === '/api/photos') {
      const station = url.searchParams.get('station') || '';
      if (!sanitizeStation(station)) return json({ ok: false, error: '站台名稱無效' }, 400, cors);
      const photos = await listPhotos(env, station);
      return json({ ok: true, station: sanitizeStation(station), photos }, 200, cors);
    }

    // 下載照片
    if (request.method === 'GET' && path.startsWith('/photos/')) {
      const rel = path.slice('/photos/'.length);
      const sep = rel.indexOf('/');
      if (sep < 0) return json({ ok: false, error: '路徑無效' }, 400, cors);
      const station = rel.slice(0, sep);
      const filename = rel.slice(sep + 1);
      if (!sanitizeStation(station)) return json({ ok: false, error: '站台名稱無效' }, 400, cors);
      const photo = await downloadPhoto(env, station, filename);
      if (!photo) return json({ ok: false, error: '照片不存在' }, 404, cors);
      const ext = '.' + filename.split('.').pop().toLowerCase();
      const ctype = CONTENT_TYPES[ext] || 'application/octet-stream';
      return new Response(photo.data, {
        status: 200,
        headers: {
          'Content-Type': ctype,
          'Content-Length': String(photo.size),
          'Cache-Control': 'public, max-age=3600',
          ...cors,
        },
      });
    }

    // 上傳照片
    if (request.method === 'POST' && path === '/api/upload') {
      const station = url.searchParams.get('station') || '';
      if (!sanitizeStation(station)) return json({ ok: false, error: '站台名稱無效' }, 400, cors);
      const contentType = request.headers.get('Content-Type') || '';
      if (!contentType.includes('multipart/form-data')) {
        return json({ ok: false, error: '格式錯誤：需要 multipart/form-data' }, 400, cors);
      }
      const fd = await request.formData();
      const files = fd.getAll('files').filter(f => f instanceof File && f.size > 0);
      if (!files.length) return json({ ok: false, error: '沒有可儲存的檔案' }, 400, cors);
      const res = await uploadPhotos(env, station, files);
      if (res.error) return json({ ok: false, error: res.error }, res.status, cors);
      return json({ ok: true, station: sanitizeStation(station), saved: res.saved }, 200, cors);
    }

    return json({ ok: false, error: '找不到' }, 404, cors);
  } catch (e) {
    return json({ ok: false, error: String(e && e.message || e) }, 500, cors);
  }
}

export default {
  async fetch(request, env, ctx) {
    return handleRequest(request, env);
  },
};