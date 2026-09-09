#!/usr/bin/env python3
import json, re, time, os, sys, threading
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE="https://service.taipower.com.tw/nds/ndsWeb/ndft112.aspx"
DATA_JS=os.path.join(os.path.dirname(__file__),"..","data.js")
OUT_JSON=os.path.join(os.path.dirname(__file__),"..","outage.json")

def get_4g_meters():
    t=open(DATA_JS,encoding="utf-8").read()
    arr=json.loads(t[t.find("["):t.rfind("]")+1])
    meters=set()
    for it in arr:
        for ms in it.get("meters",{}).values():
            for m in ms:
                meters.add(re.sub(r"[^0-9]","",m))
    return sorted([m for m in meters if len(m)>=10])

# Thread-local OCR
thread_local = threading.local()
def get_ocr():
    if not hasattr(thread_local, "ocr"):
        import ddddocr
        thread_local.ocr = ddddocr.DdddOcr(show_ad=False)
    return thread_local.ocr

def ocr_captcha(ocr, content):
    try:
        t = ocr.classification(content).strip()
        t = re.sub(r"[^0-9]", "", t)
        return t
    except Exception:
        return ""

def query_single(meter):
    ocr=get_ocr()
    # 台電流程:驗證碼欄預設灰底 disabled,必須先填電號再按「重產驗證碼」,
    # 取得第二次驗證碼後才能查詢。第一次驗證碼固定失效。
    for attempt in range(5):
        s=requests.Session()
        s.headers.update({"User-Agent":"Mozilla/5.0","Referer":BASE})
        try:
            r=s.get(BASE, timeout=30); r.encoding="utf-8"
            soup=BeautifulSoup(r.text,"html.parser")
            vs_elm=soup.find("input",{"name":"__VIEWSTATE"})
            ev_elm=soup.find("input",{"name":"__EVENTVALIDATION"})
            if not vs_elm or not ev_elm:
                print(f"[{meter}] no VIEWSTATE attempt {attempt+1}", file=sys.stderr)
                time.sleep(1)
                continue
            vs=vs_elm["value"]
            vsg_elm=soup.find("input",{"name":"__VIEWSTATEGENERATOR"})
            vsg=vsg_elm["value"] if vsg_elm else ""
            ev=ev_elm["value"]
            # 步驟1:已填電號狀態下按「重產驗證碼」(Button_Captcha),啟用驗證碼欄
            data1={"__VIEWSTATE":vs,"__VIEWSTATEGENERATOR":vsg,"__EVENTVALIDATION":ev,
                   "ctl00$ContentMain$HiddenField_ReportType":"1",
                   "ctl00$ContentMain$TextBox_CustNo":meter,
                   "__EVENTTARGET":"ctl00$ContentMain$Button_Captcha","__EVENTARGUMENT":""}
            r1=s.post(BASE, data=data1, timeout=30); r1.encoding="utf-8"
            soup1=BeautifulSoup(r1.text,"html.parser")
            vs1=soup1.find("input",{"name":"__VIEWSTATE"})
            ev1=soup1.find("input",{"name":"__EVENTVALIDATION"})
            if not vs1 or not ev1:
                print(f"[{meter}] no VIEWSTATE after refresh attempt {attempt+1}", file=sys.stderr)
                time.sleep(1)
                continue
            vs=vs1["value"]; ev=ev1["value"]
            vsg1=soup1.find("input",{"name":"__VIEWSTATEGENERATOR"})
            if vsg1: vsg=vsg1["value"]
            # 步驟2:對刷新後的第二次驗證碼加強重試,必須為4位數字
            # 注意:不可重打GET首頁,否則VIEWSTATE失效;同session重抓同captcha圖即可
            img1=soup1.find("img", src=re.compile(r"captcha\.ashx"))
            if not img1:
                print(f"[{meter}] no captcha after refresh attempt {attempt+1}", file=sys.stderr)
                time.sleep(1)
                continue
            src1=img1.get("src"); url1=src1 if src1.startswith("http") else "https://service.taipower.com.tw/nds/ndsWeb/"+src1.lstrip("./")
            captcha1=""
            for ocr_try in range(5):
                try:
                    cap1=s.get(url1, timeout=30)
                    if cap1.status_code!=200 or len(cap1.content)<100:
                        time.sleep(0.5)
                        continue
                    captcha1=ocr_captcha(ocr, cap1.content)
                except Exception:
                    time.sleep(0.5)
                    continue
                if re.fullmatch(r"[0-9]{4}", captcha1 or ""):
                    break
                print(f"[{meter}] OCR invalid '{captcha1}' retry {ocr_try+1}", file=sys.stderr)
                time.sleep(0.5)
            if not re.fullmatch(r"[0-9]{4}", captcha1 or ""):
                # 5次皆非4碼則整輪重試(換新session+重產驗證碼)
                continue
            data={"__VIEWSTATE":vs,"__VIEWSTATEGENERATOR":vsg,"__EVENTVALIDATION":ev,
                  "ctl00$ContentMain$HiddenField_ReportType":"1",
                  "ctl00$ContentMain$TextBox_CustNo":meter,
                  "ctl00$ContentMain$TextBox_Captcha":captcha1,
                  "__EVENTTARGET":"ctl00$ContentMain$Button_Inquiry","__EVENTARGUMENT":""}
            r2=s.post(BASE, data=data, timeout=30); r2.encoding="utf-8"
            text=BeautifulSoup(r2.text,"html.parser").get_text()
            if "暫停供電" in text:
                m=re.search(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})[^\d]+(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", text)
                reason="停電"
                for line in text.splitlines():
                    if "暫停供電" in line: reason=line.strip()[:120]; break
                if m:
                    return {"found":True,"start":m.group(1).replace("/","-").replace(" ","T")+":00","end":m.group(2).replace("/","-").replace(" ","T")+":00","reason":reason}
                return {"found":True,"reason":reason}
            if "尚未接獲通報停電或已完成復電" in text or "查無" in text or "無停電" in text:
                return {"found":False}
            if "驗證碼" in text:
                print(f"[{meter}] captcha '{captcha1}' rejected, retry {attempt+1}", file=sys.stderr)
                time.sleep(0.8)
                continue
            return {"found":False}
        except Exception as e:
            print(f"[{meter}] err {e}", file=sys.stderr)
            time.sleep(1)
            continue
    print(f"[{meter}] all retries exhausted", file=sys.stderr)
    return {"found":False}

def main():
    meters=get_4g_meters()
    print(f"4G distinct {len(meters)}")
    # Load old for merge
    old={}
    if os.path.exists(OUT_JSON):
        try:
            old=json.load(open(OUT_JSON,encoding="utf-8"))
        except: pass
    result=dict(old)
    # Clean expired
    now=time.time()
    for k in list(result.keys()):
        try:
            end=result[k].get("end","")
            if end and time.mktime(time.strptime(end, "%Y-%m-%dT%H:%M:%S")) < now:
                del result[k]
        except: pass
    # Concurrent
    max_workers=5
    print(f"Concurrent {max_workers} workers")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures={ex.submit(query_single, m): m for m in meters}
        for idx, fut in enumerate(as_completed(futures), 1):
            m=futures[fut]
            try:
                info=fut.result()
            except Exception as e:
                info={"found":False, "error":str(e)}
            if info.get("found"):
                result[m]=info
                print(f"[{idx}/{len(meters)}] {m} -> {info.get('start')}~{info.get('end')}")
            elif m in result:
                del result[m]
                print(f"[{idx}/{len(meters)}] {m} -> cleared")
            else:
                print(f"[{idx}/{len(meters)}] {m} -> normal")
            if idx%50==0:
                with open(OUT_JSON,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    with open(OUT_JSON,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"Done {len(result)} outages")

if __name__=="__main__":
    main()
