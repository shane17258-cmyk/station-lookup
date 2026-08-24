#!/usr/bin/env python3
import json, re, time, os, sys
import requests
from bs4 import BeautifulSoup
BASE="https://service.taipower.com.tw/nds/ndsWeb/ndft112.aspx"
DATA_JS=os.path.join(os.path.dirname(__file__),"..","data.js")
OUT_JSON=os.path.join(os.path.dirname(__file__),"..","outage.json")

def get_4g_meters():
    t=open(DATA_JS,encoding="utf-8").read()
    arr=json.loads(t[t.find("["):t.rfind("]")+1])
    # 每子站台有電號都查（ distinct 已涵蓋全部子站台，去重後仍為全部 distinct 電號）
    meters=set()
    cnt=0
    for it in arr:
        for ms in it.get("meters",{}).values():
            for m in ms:
                cnt+=1
                meters.add(re.sub(r"[^0-9]","",m))
    meters=sorted([m for m in meters if len(m)>=10])
    print(f"4G 子站台有電號 {cnt} 筆，去重 {len(meters)} 筆（全部查詢）")
    return meters

def solve_captcha(session, soup):
    import re, ddddocr
    ocr=ddddocr.DdddOcr(show_ad=False)
    img=soup.find("img", src=re.compile(r"captcha\.ashx"))
    if not img: return None, None
    src=img.get("src")
    url=src if src.startswith("http") else "https://service.taipower.com.tw/nds/ndsWeb/"+src.lstrip("./")
    r=session.get(url, timeout=30)
    txt=ocr.classification(r.content).strip()
    return re.sub(r"[^0-9A-Za-z]","",txt), r.content

def query_single(meter):
    import ddddocr
    ocr=ddddocr.DdddOcr(show_ad=False)
    for attempt in range(4):
        s=requests.Session()
        s.headers.update({"User-Agent":"Mozilla/5.0","Referer":BASE})
        try:
            # 首次 GET
            r=s.get(BASE, timeout=30); r.encoding="utf-8"
            soup=BeautifulSoup(r.text,"html.parser")
            vs=soup.find("input",{"name":"__VIEWSTATE"})["value"]
            vsg=soup.find("input",{"name":"__VIEWSTATEGENERATOR"})["value"] if soup.find("input",{"name":"__VIEWSTATEGENERATOR"}) else ""
            ev=soup.find("input",{"name":"__EVENTVALIDATION"})["value"]
            # 首次驗證碼（依使用者回報此輪必失敗，仍需走一次以取得新 VIEWSTATE）
            img=soup.find("img", src=re.compile(r"captcha\.ashx"))
            src=img.get("src"); url=src if src.startswith("http") else "https://service.taipower.com.tw/nds/ndsWeb/"+src.lstrip("./")
            cap1=s.get(url, timeout=30)
            captcha1=ocr.classification(cap1.content).strip()
            captcha1=re.sub(r"[^0-9A-Za-z]","",captcha1)
            data1={"__VIEWSTATE":vs,"__VIEWSTATEGENERATOR":vsg,"__EVENTVALIDATION":ev,
                   "ctl00$ContentMain$HiddenField_ReportType":"1",
                   "ctl00$ContentMain$TextBox_CustNo":meter,
                   "ctl00$ContentMain$TextBox_Captcha":captcha1,
                   "__EVENTTARGET":"ctl00$ContentMain$Button_Inquiry","__EVENTARGUMENT":""}
            r1=s.post(BASE, data=data1, timeout=30); r1.encoding="utf-8"
            # 不論成功與否，取得第二次的 VIEWSTATE 與驗證碼
            soup1=BeautifulSoup(r1.text,"html.parser")
            # 若首次即有 暫停供電，代表意外通過，直接回傳
            if "暫停供電" in r1.text:
                m=re.search(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})[^\d]+(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", r1.text)
                reason="停電"
                for line in r1.text.splitlines():
                    if "暫停供電" in line: reason=line.strip()[:120]; break
                if m:
                    return {"found":True,"start":m.group(1).replace("/","-").replace(" ","T")+":00","end":m.group(2).replace("/","-").replace(" ","T")+":00","reason":reason}
                return {"found":True,"reason":reason}
            # 第二次驗證碼
            vs1=soup1.find("input",{"name":"__VIEWSTATE"})
            ev1=soup1.find("input",{"name":"__EVENTVALIDATION"})
            if vs1: vs=vs1["value"]
            if ev1: ev=ev1["value"]
            vsg1=soup1.find("input",{"name":"__VIEWSTATEGENERATOR"})
            if vsg1: vsg=vsg1["value"]
            img1=soup1.find("img", src=re.compile(r"captcha\.ashx"))
            if not img1:
                continue
            src1=img1.get("src"); url1=src1 if src1.startswith("http") else "https://service.taipower.com.tw/nds/ndsWeb/"+src1.lstrip("./")
            cap2=s.get(url1, timeout=30)
            captcha2=ocr.classification(cap2.content).strip()
            captcha2=re.sub(r"[^0-9A-Za-z]","",captcha2)
            data2={"__VIEWSTATE":vs,"__VIEWSTATEGENERATOR":vsg,"__EVENTVALIDATION":ev,
                   "ctl00$ContentMain$HiddenField_ReportType":"1",
                   "ctl00$ContentMain$TextBox_CustNo":meter,
                   "ctl00$ContentMain$TextBox_Captcha":captcha2,
                   "__EVENTTARGET":"ctl00$ContentMain$Button_Inquiry","__EVENTARGUMENT":""}
            r2=s.post(BASE, data=data2, timeout=30); r2.encoding="utf-8"
            text=BeautifulSoup(r2.text,"html.parser").get_text()
            if "暫停供電" in text:
                m=re.search(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})[^\d]+(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", text)
                reason="停電"
                for line in text.splitlines():
                    if "暫停供電" in line: reason=line.strip()[:120]; break
                if m:
                    return {"found":True,"start":m.group(1).replace("/","-").replace(" ","T")+":00","end":m.group(2).replace("/","-").replace(" ","T")+":00","reason":reason}
                return {"found":True,"reason":reason}
            if "尚未接獲通報停電或已完成復電" in text or "查無" in text or "無停電" in text or "目前無" in text:
                return {"found":False, "normal":True}
            # 若仍驗證碼錯誤，重試
            if "驗證碼" in text:
                continue
            return {"found":False}
        except Exception as e:
            print(f"[{meter}] err {e} retry {attempt+1}", file=sys.stderr)
            time.sleep(1)
            continue
    return {"found":False, "error":"二次驗證碼皆失敗"}

def main():
    meters=get_4g_meters()
    # 當日複核：優先檢查今日有排程停電的電號
    try:
        if os.path.exists(OUT_JSON):
            with open(OUT_JSON, encoding="utf-8") as f:
                old = json.load(f)
            today = time.strftime("%Y-%m-%d")
            due = [m for m, info in old.items() if info.get("start","").startswith(today)]
            if due:
                print(f"當日複核優先 {len(due)} 筆: {due[:5]}")
                # 將當日排程移至最前
                meters = due + [m for m in meters if m not in due]
    except Exception as e:
        print(f"當日複核載入失敗: {e}", file=sys.stderr)
    # 每日 300 筆輪詢（輪替覆蓋全部）
    limit = int(os.environ.get("OUTAGE_LIMIT", "0"))
    if limit and limit < len(meters):
        import datetime
        day_of_year = datetime.datetime.utcnow().timetuple().tm_yday
        offset = (day_of_year * limit) % len(meters)
        # 保留當日複核優先，再輪替其餘
        meters = meters[:limit] if len(meters) <= limit else (meters[offset:] + meters[:offset])[:limit]
        print(f"輪詢限制 {limit} 筆（offset {offset}）")
    print(f"本次查詢 {len(meters)} 筆")
    # 載入舊檔以合併（保留未輪詢到的未來排程）
    old_result = {}
    try:
        if os.path.exists(OUT_JSON):
            with open(OUT_JSON, encoding="utf-8") as f:
                old_result = json.load(f)
    except: pass
    result = dict(old_result)
    # 移除已過期的排程（end < now）
    now = time.time()
    for k in list(result.keys()):
        try:
            end = result[k].get("end","")
            if end and time.mktime(time.strptime(end, "%Y-%m-%dT%H:%M:%S")) < now:
                del result[k]
        except: pass
    for idx,m in enumerate(meters,1):
        print(f"[{idx}/{len(meters)}] {m} ...")
        try:
            info=query_single(m)
        except Exception as e:
            info={"found":False,"error":str(e)}
        if info.get("found"):
            result[m]=info
            print(f"  -> {info.get('start')}~{info.get('end')}")
        elif m in result:
            del result[m]
            print(f"  -> cleared")
        time.sleep(0.8)
        if idx%50==0:
            with open(OUT_JSON,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    with open(OUT_JSON,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"Done {len(result)} outages")

if __name__=="__main__":
    main()
