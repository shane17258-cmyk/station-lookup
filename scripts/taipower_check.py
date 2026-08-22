#!/usr/bin/env python3
# 4G-only daily outage check via https://service.taipower.com.tw/nds/ndsWeb/ndft112.aspx
# Uses ddddocr for captcha (4-digit numeric)
import json, re, time, os, sys
import requests
from bs4 import BeautifulSoup

BASE = "https://service.taipower.com.tw/nds/ndsWeb/ndft112.aspx"
DATA_JS = os.path.join(os.path.dirname(__file__), "..", "data.js")
OUT_JSON = os.path.join(os.path.dirname(__file__), "..", "outage.json")

def get_4g_meters():
    # Parse data.js: const STATION_DATA = [...] - 每一個有電號的 4G 子站台都要查（無電號不查）
    t = open(DATA_JS, encoding="utf-8").read()
    s = t.find("[")
    e = t.rfind("]") + 1
    arr = json.loads(t[s:e])
    # 每子站台統計
    sub_count = 0
    meters = set()
    for it in arr:
        for ms in it.get("meters", {}).values():
            for m in ms:
                sub_count += 1
                meters.add(re.sub(r"[^0-9]", "", m))
    meters = sorted([m for m in meters if len(m) >= 10])
    print(f"4G 子站台有電號數: {sub_count}, 去重後 distinct 電號: {len(meters)}（僅查 distinct，結果同步顯示至 4G/5G）")
    return meters

def query_single(meter, retries=3):
    # ddddocr setup (lazy import)
    try:
        import ddddocr
        ocr = ddddocr.DdddOcr(show_ad=False)
        use_ocr = True
    except Exception as e:
        print(f"ddddocr not available: {e}", file=sys.stderr)
        use_ocr = False
        ocr = None

    for attempt in range(retries):
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": BASE})
        # GET page
        r = s.get(BASE, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        vs = soup.find("input", {"name": "__VIEWSTATE"})
        vsg = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
        ev = soup.find("input", {"name": "__EVENTVALIDATION"})
        if not vs or not ev:
            print(f"[{meter}] failed to get VIEWSTATE attempt {attempt+1}", file=sys.stderr)
            time.sleep(1)
            continue
        vs = vs["value"]; vsg = vsg["value"] if vsg else ""; ev = ev["value"]
        # GET captcha
        img = soup.find("img", src=re.compile(r"captcha\.ashx"))
        if not img:
            print(f"[{meter}] no captcha img", file=sys.stderr)
            time.sleep(1)
            continue
        src = img.get("src")
        captcha_url = src if src.startswith("http") else "https://service.taipower.com.tw/nds/ndsWeb/" + src.lstrip("./")
        cap_r = s.get(captcha_url, timeout=15)
        if cap_r.status_code != 200 or len(cap_r.content) < 100:
            print(f"[{meter}] captcha download failed", file=sys.stderr)
            time.sleep(1)
            continue
        # OCR
        if use_ocr:
            try:
                captcha_text = ocr.classification(cap_r.content).strip()
                captcha_text = re.sub(r"[^0-9A-Za-z]", "", captcha_text)
            except Exception as e:
                print(f"[{meter}] OCR failed: {e}", file=sys.stderr)
                time.sleep(1)
                continue
        else:
            # fallback: manual (should not happen in Actions)
            captcha_text = ""
        if not captcha_text or len(captcha_text) < 3:
            print(f"[{meter}] OCR empty: '{captcha_text}'", file=sys.stderr)
            time.sleep(0.5)
            continue
        # POST
        data = {
            "__VIEWSTATE": vs,
            "__VIEWSTATEGENERATOR": vsg,
            "__EVENTVALIDATION": ev,
            "ctl00$ContentMain$HiddenField_ReportType": "1",
            "ctl00$ContentMain$TextBox_CustNo": meter,
            "ctl00$ContentMain$TextBox_Captcha": captcha_text,
            "__EVENTTARGET": "ctl00$ContentMain$Button_Inquiry",
            "__EVENTARGUMENT": ""
        }
        r2 = s.post(BASE, data=data, timeout=15)
        r2.encoding = "utf-8"
        text = BeautifulSoup(r2.text, "html.parser").get_text()
        if "驗證碼有誤" in text or "驗證碼錯誤" in text:
            print(f"[{meter}] captcha '{captcha_text}' incorrect, retry {attempt+1}", file=sys.stderr)
            time.sleep(0.8)
            continue
        if "請輸入驗證碼" in text and "暫停供電" not in text and "查無" not in text:
            print(f"[{meter}] need captcha, retry", file=sys.stderr)
            time.sleep(0.8)
            continue
        # Success: parse result
        if "暫停供電" in text:
            # Extract period: 2026/08/24 08:30 至 2026/08/24 15:00
            m = re.search(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})[^\d]+(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", text)
            reason = "停電"
            if "桿線遷移" in text:
                reason = "桿線遷移工程"
            elif "工程" in text:
                # generic
                pass
            # Find the sentence containing 暫停供電
            for line in text.splitlines():
                if "暫停供電" in line:
                    reason = line.strip()[:120]
                    break
            if m:
                start = m.group(1).replace("/", "-").replace(" ", "T") + ":00"
                end = m.group(2).replace("/", "-").replace(" ", "T") + ":00"
                return {"found": True, "start": start, "end": end, "reason": reason, "raw": text[text.find("暫停供電")-80:text.find("暫停供電")+120].strip()}
            else:
                return {"found": True, "reason": reason}
        if "查無" in text or "無停電" in text or "目前無" in text:
            return {"found": False}
        # Unknown but treat as no outage
        # Save snippet for debug
        # print(text[:1500])
        return {"found": False}
    # retries exhausted
    return {"found": False, "error": "captcha retries exhausted"}

def main():
    meters = get_4g_meters()
    print(f"4G distinct meters to check: {len(meters)}")
    # For Actions, limit to avoid long runtime/timeout (e.g., 380 meters * ~2s = 760s > 10min)
    # We process in batches, with delay
    result = {}
    # Optional: limit for testing via env
    limit = int(os.environ.get("OUTAGE_LIMIT", "0"))
    if limit and limit < len(meters):
        meters = meters[:limit]
        print(f"Limited to {limit} for testing")
    for idx, m in enumerate(meters, 1):
        print(f"[{idx}/{len(meters)}] querying {m}...")
        info = query_single(m)
        if info.get("found"):
            result[m] = info
            print(f"  -> OUTAGE {info.get('start')} to {info.get('end')}")
        else:
            # not storing normal to keep file small
            pass
        # Be nice to Taipower
        time.sleep(1.0)
        # Early exit for test
        if idx % 50 == 0:
            print(f"  ...{idx} done, saving interim")
            with open(OUT_JSON, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
    # Final write
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Done, outages found: {len(result)}, written to {OUT_JSON}")

if __name__ == "__main__":
    main()
