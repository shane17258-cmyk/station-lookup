# -*- coding: utf-8 -*-
"""
一鍵更新腳本
從本資料夾內的四個 xlsx 檔重新產生 data.js (4G) 與 data5g.js (5G)。
過濾條件：縣市=苗栗縣 且 鄉鎮=苗栗市
檔名會自動以 *LTE_CoBTS_CHT.xlsx / *LTE_CoCell_CHT.xlsx / *nrBts_DB_CHT.xlsx / *nrCell_DB_CHT.xlsx 匹配，
未來新 dump 直接放進來即可（支援不同日期前綴）。
"""
import openpyxl, json, os, glob, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
COUNTY = "苗栗縣"
TOWN = "苗栗市"

def find_file(pattern):
    files = glob.glob(os.path.join(BASE, pattern))
    if not files:
        raise FileNotFoundError(f"找不到 {pattern}，請確認檔案已放在本資料夾")
    return sorted(files)[-1]

def load_rows(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        raise KeyError(f"{os.path.basename(path)} 內沒有 {sheet} 工作表")
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    hdr = [str(c).strip() if c is not None else "" for c in next(it)]
    rows = [dict(zip(hdr, r)) for r in it if any(c is not None for c in r)]
    wb.close()
    return hdr, rows

def get(r, hdr, name):
    for i, h in enumerate(hdr):
        if h == name:
            v = r[h]
            return str(v).strip() if v is not None else ""
    return ""

def latlon_pairs(hdr, lat_base, lon_base, count=9):
    lat_cols = [lat_base] + [f"{lat_base}_{i}" for i in range(2, count + 1)]
    lon_cols = [lon_base] + [f"{lon_base}_{i}" for i in range(2, count + 1)]
    return lat_cols, lon_cols

def build_coords(row, hdr, lat_cols, lon_cols, n_stations):
    coords = []
    for i in range(n_stations):
        lat = get(row, hdr, lat_cols[i]) if i < len(lat_cols) else ""
        lon = get(row, hdr, lon_cols[i]) if i < len(lon_cols) else ""
        try:
            if lat and lon:
                coords.append({"lat": round(float(lat), 6), "lon": round(float(lon), 6)})
            else:
                coords.append(None)
        except (ValueError, TypeError):
            coords.append(None)
    return coords

def group_cells(cells, key_fn, field_map):
    """key_fn(cell_row) -> sector number; field_map -> output field names"""
    out = []
    for sec in sorted({key_fn(c) for c in cells if key_fn(c) is not None}):
        sec_cells = [field_map(c) for c in cells if key_fn(c) == sec]
        out.append({"sec": sec, "cells": sec_cells})
    return out

def normalize(s):
    return s.replace(" ", "").replace("　", "").replace("-", "").replace("_", "")

def build_meter_map(meter_rows, id2x):
    """
    電號檔：欄位 電號▲/台號/台名（dict 形式，key 為欄位名）
    回傳 { lnBtsId: { 站台名: [電號, ...] } }
    比對順序：
      1. 台號去尾綴(L/U/S/l)後精確等於 lnBtsId → 命中該基地台
      2. 否則以台名對站台名做模糊(雙向包含)比對
    """
    ids4 = set(id2x.keys())
    meter_map = {}
    for r in meter_rows:
        def g(k):
            return str(r.get(k, "")).strip() if r.get(k) else ""
        meter_no = g("電號▲") or g("電號")
        th = g("台號")
        tn = g("台名")
        if not meter_no or not th:
            continue

        hit_id = None
        # 台號精確比對（去尾綴）
        if th in ids4:
            hit_id = th
        else:
            for suf in ["L", "U", "S", "l"]:
                base = th[:-1] if th.endswith(suf) else th
                if base in ids4:
                    hit_id = base
                    break

        station_hit = None
        if hit_id:
            x = id2x[hit_id]
            cands = x["stations"] or []
            # 台名精確匹配站台
            if tn:
                for st in cands:
                    if st == tn:
                        station_hit = st
                        break
                if station_hit is None:
                    for st in cands:
                        if normalize(st) == normalize(tn):
                            station_hit = st
                            break
                # 台名模糊匹配站台
                if station_hit is None:
                    for st in cands:
                        if tn and (normalize(tn) in normalize(st) or normalize(st) in normalize(tn)):
                            station_hit = st
                            break
            # 找不到具體站台 → 掛到第一個站台
            if station_hit is None:
                station_hit = cands[0] if cands else ""
        else:
            # 台名全域模糊比對
            for x in id2x.values():
                for st in x["stations"] or []:
                    if tn and (normalize(tn) in normalize(st) or normalize(st) in normalize(tn)):
                        hit_id = x["id"]
                        station_hit = st
                        break
                if hit_id:
                    break

        if hit_id and station_hit is not None:
            meter_map.setdefault(hit_id, {}).setdefault(station_hit, []).append(meter_no)
    return meter_map

# ============ 4G ============
print("== 4G ==")
co_bts = find_file("*LTE_CoBTS_CHT.xlsx")
co_cell = find_file("*LTE_CoCell_CHT.xlsx")
hdr_bts, bts_rows = load_rows(co_bts, "LTE_CoBTS_CHT")
hdr_cell, cell_rows = load_rows(co_cell, "LTE_CoCell_CHT")
print("  stations file:", os.path.basename(co_bts))
print("  cells file  :", os.path.basename(co_cell))

bts = [r for r in bts_rows if get(r, hdr_bts, "縣市") == COUNTY and get(r, hdr_bts, "鄉鎮") == TOWN]
print(f"  過濾後站台數: {len(bts)}")

cell_map = {}
for r in cell_rows:
    lnbts = get(r, hdr_cell, "lnBtsId")
    st = get(r, hdr_cell, "CellName_CHS")
    if not lnbts or not st:
        continue
    cell_map.setdefault(lnbts, {}).setdefault(st, []).append(r)

# 電號檔（可選，找不到就跳過）
meter_rows = []
meter_files = glob.glob(os.path.join(BASE, "*電號*.xlsx"))
if meter_files:
    mf = sorted(meter_files)[-1]
    _, meter_rows = load_rows(mf, "工作表1")
    print(f"  電號檔: {os.path.basename(mf)} ({len(meter_rows)} 筆)")
else:
    print("  電號檔: 未找到，略過")

lat_cols, lon_cols = latlon_pairs(hdr_bts, "Lat", "Lon")
items4 = []
for r in bts:
    lnbts = get(r, hdr_bts, "lnBtsId")
    stations = get(r, hdr_bts, "lnBtsIdLL_NameChs").split("___") if get(r, hdr_bts, "lnBtsIdLL_NameChs") else []
    stations = [s.strip() for s in stations if s.strip()]
    secs = get(r, hdr_bts, "lnBtsIdLL_Sec").split("_") if get(r, hdr_bts, "lnBtsIdLL_Sec") else []
    coords = build_coords(r, hdr_bts, lat_cols, lon_cols, len(stations))
    cells_by_station = {}
    for s in stations:
        cell_rows_s = cell_map.get(lnbts, {}).get(s, [])
        def key_fn(c):
            try:
                return int(get(c, hdr_cell, "lnCelId")) // 10
            except (ValueError, TypeError):
                return None
        def field_map(c):
            obj = {
                "cel": get(c, hdr_cell, "lnCelId"),
                "cov": get(c, hdr_cell, "Coverage"),
                "rmod": get(c, hdr_cell, "rmod_cell"),
                "ant": get(c, hdr_cell, "AntType"),
                "az": get(c, hdr_cell, "Azimuth"),
                "mt": get(c, hdr_cell, "Mtilt"),
                "et": get(c, hdr_cell, "Etilt"),
            }
            try:
                lat, lon = float(get(c, hdr_cell, "Latitude")), float(get(c, hdr_cell, "Longitude"))
                obj["lat"] = round(lat, 6)
                obj["lon"] = round(lon, 6)
            except (ValueError, TypeError):
                pass
            return obj
        cells_by_station[s] = group_cells(cell_rows_s, key_fn, field_map)
    items4.append({
        "id": lnbts,
        "siteName": get(r, hdr_bts, "SiteName"),
        "siteNameCV": get(r, hdr_bts, "SiteNameCV"),
        "sec": get(r, hdr_bts, "lnBtsIdLL_Sec"),
        "secs": secs,
        "stations": stations,
        "coords": coords,
        "cells": cells_by_station,
        "nrBtsId": get(r, hdr_bts, "nrBtsId"),
        "ranType": get(r, hdr_bts, "RANtype"),
    })

# 電號比對（僅 4G）
if meter_rows:
    id2x = {x["id"]: x for x in items4}
    meter_map = build_meter_map(meter_rows, id2x)
    matched = 0
    for it in items4:
        m = meter_map.get(it["id"])
        if m:
            it["meters"] = m
            matched += 1
    print(f"  電號比對完成: {matched} 個站台有電號")

js4 = "const STATION_DATA = " + json.dumps(items4, ensure_ascii=False, indent=1) + ";\n"
with open(os.path.join(BASE, "data.js"), "w", encoding="utf-8") as f:
    f.write(js4)
print(f"  寫入 data.js: {len(items4)} 筆, {os.path.getsize(os.path.join(BASE,'data.js'))} bytes")

# ============ 5G ============
print("== 5G ==")
nr_bts = find_file("*nrBts_DB_CHT.xlsx")
nr_cell = find_file("*nrCell_DB_CHT.xlsx")
hdr5, bts5_rows = load_rows(nr_bts, "nrBts_DB_CHT")
hdr5c, cell5_rows = load_rows(nr_cell, "nrCell_DB_CHT")
print("  stations file:", os.path.basename(nr_bts))
print("  cells file  :", os.path.basename(nr_cell))

bts5 = [r for r in bts5_rows if get(r, hdr5, "縣市") == COUNTY and get(r, hdr5, "鄉鎮") == TOWN]
print(f"  過濾後站台數: {len(bts5)}")

cell5_map = {}
for r in cell5_rows:
    nrbts = get(r, hdr5c, "nrBtsId")
    st = get(r, hdr5c, "nrCellName_chs")
    if not nrbts or not st:
        continue
    cell5_map.setdefault(nrbts, {}).setdefault(st, []).append(r)

lat5_cols, lon5_cols = latlon_pairs(hdr5, "Lat", "Lon")
items5 = []
for r in bts5:
    nrbts = get(r, hdr5, "nrBtsId")
    stations = get(r, hdr5, "nrBtsIdNN_NameChs").split("___") if get(r, hdr5, "nrBtsIdNN_NameChs") else []
    stations = [s.strip() for s in stations if s.strip()]
    secs = get(r, hdr5, "nrBtsIdNN_Sec").split("_") if get(r, hdr5, "nrBtsIdNN_Sec") else []
    coords = build_coords(r, hdr5, lat5_cols, lon5_cols, len(stations))
    cells_by_station = {}
    for s in stations:
        cell_rows_s = cell5_map.get(nrbts, {}).get(s, [])
        def key_fn5(c):
            try:
                return int(get(c, hdr5c, "nrCellId")) // 100
            except (ValueError, TypeError):
                return None
        def field_map5(c):
            obj = {
                "cel": get(c, hdr5c, "nrCellId"),
                "rmod": get(c, hdr5c, "rMod"),
                "az": get(c, hdr5c, "Azimuth"),
                "mt": get(c, hdr5c, "M-tilt"),
                "et": get(c, hdr5c, "E-tilt"),
                "toff": get(c, hdr5c, "tiltOffset"),
                "cov": get(c, hdr5c, "Coverage"),
            }
            try:
                lat, lon = float(get(c, hdr5c, "Latitude")), float(get(c, hdr5c, "Longitude"))
                obj["lat"] = round(lat, 6)
                obj["lon"] = round(lon, 6)
            except (ValueError, TypeError):
                pass
            return obj
        cells_by_station[s] = group_cells(cell_rows_s, key_fn5, field_map5)
    items5.append({
        "id": nrbts,
        "siteName": get(r, hdr5, "SiteName"),
        "siteNameCV": get(r, hdr5, "SiteName"),
        "sec": get(r, hdr5, "nrBtsIdNN_Sec"),
        "secs": secs,
        "stations": stations,
        "coords": coords,
        "cells": cells_by_station,
        "ranType": get(r, hdr5, "RANtype"),
    })

js5 = "const STATION_DATA_5G = " + json.dumps(items5, ensure_ascii=False, indent=1) + ";\n"
with open(os.path.join(BASE, "data5g.js"), "w", encoding="utf-8") as f:
    f.write(js5)
print(f"  寫入 data5g.js: {len(items5)} 筆, {os.path.getsize(os.path.join(BASE,'data5g.js'))} bytes")

print("\n完成！")
