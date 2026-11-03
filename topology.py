# -*- coding: utf-8 -*-
"""
站台架構資料產生器
參考 Nokia NetAct 的 SMOD/BBMOD → RMOD → RET → Cell 檢視，輸出 topo.js。

輸出結構（topo.js）：
{
  "updated": "20261103",
  "4g": {
    "411480": {
      "smods": [{"id": "1", "name": "ASIB", "alarms": [{"t": "Door", "s": "major"}]}],
      "bbs":   [{"id": "1", "name": "ABIA", "smod": "1"}],
      "rmods": [{
        "id": "1", "name": "FXDB", "desc": "FXDB_RFM_3T6R_L900 - 3x80W",
        "bb": "1", "port": "3", "smod": "1",
        "alarms": [{"t": "AC Power", "s": "major"}],       # RMOD 層級
        "cells": [{
          "cel": "11", "n": "苗栗中央L17苗栗三角公園",
          "pci": 319, "band": "L09-10", "bw": 10, "freq": 3650,
          "az": 90, "mt": 0, "et": 10,
          "ant": "RVVPX303.6F12R2", "cov": "Outdoor",
          "ret": {"sn": "C6K0216878-R1", "tilt": 10, "min": 2, "max": 16},
          "alarms": [{"t": "Fire", "s": "critical"}]      # 細胞層級
        }]
      }],
      "alarms": [{"t": "..."}]                            # 無法歸屬到細胞/RMOD 的告警
    }
  },
  "5g": { ... }
}

資料來源：
  4G: LTE_CoCell（RMOD/BBMOD/SMOD/RET/細胞） + LTE_RMOD_EAC / LTE_SMOD_EAC（告警）
  5G: nrCell（RMOD/SMOD/RET/細胞/Baseband） + NR_RMOD_EAC / NR_SMOD_EAC（告警）
"""
import json
import re

# 已知的模組名稱（用來從 rmod_name_cell 之類的長字串取前綴時做校正）
KNOWN_SMOD = ("FSMF", "ASIA", "ASIB", "ASIK", "ASIL", "ABIO", "ABIL")

_RE_RMOD = re.compile(r"RMOD[-_ ]?(\d+)")
_RE_BB = re.compile(r"bbMod[-_ ]?(\d+)", re.I)
# EAC Description：Cell_013_Door / " Cell_013_AC Power" / AC Power
_RE_CELL_ALARM = re.compile(r"^[Cc]ell[_ ]*(\d+)[_ ]+(.+)$")
_RE_BASEBAND = re.compile(r"(\d+)\s*\*\s*([A-Za-z0-9]+)")


def _s(v):
    return "" if v is None else str(v).strip()


def _num(v):
    """轉數字（整數化），失敗回傳 None"""
    s = _s(v)
    if not s:
        return None
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return None


def _rmod_no(raw):
    m = _RE_RMOD.search(_s(raw))
    return m.group(1) if m else ""


def _bb_no(raw):
    m = _RE_BB.search(_s(raw))
    return m.group(1) if m else ""


def _port(raw):
    """bbMod_PortId：'3' / '1_Cell-43_RMOD-13/RMOD_R-2' → '3' / '1'"""
    s = _s(raw)
    m = re.match(r"^\d+", s)
    return m.group(0) if m else s


def _clean_alarm_text(desc):
    """Description → 去掉 Cell_013_ 之類前綴，只留告警文字"""
    d = _s(desc)
    m = _RE_CELL_ALARM.match(d)
    if m:
        return m.group(2).strip(), (m.group(1).lstrip("0") or "0")
    return d, ""


def _sev(v):
    s = _s(v).lower()
    for k in ("critical", "major", "minor", "warning"):
        if s.startswith(k):
            return k
    # Critical [3] / Major [2] ...
    return "major"


def _add_alarm(bucket, text, sev):
    if not text:
        return
    for a in bucket:
        if a["t"] == text and a["s"] == sev:
            return
    bucket.append({"t": text, "s": sev})


def _sort_key(k):
    return (0, int(k)) if str(k).isdigit() else (1, str(k))


def _site(sites, bid):
    if bid not in sites:
        sites[bid] = {"smods": {}, "bbs": {}, "rmods": {}, "alarms": []}
    return sites[bid]


def _rmod(site, rid):
    r = site["rmods"].get(rid)
    if r is None:
        r = {"id": rid, "name": "", "desc": "", "bb": "", "port": "",
             "smod": "", "alarms": [], "cells": {}}
        site["rmods"][rid] = r
    return r


def _cell(rmod, cel):
    c = rmod["cells"].get(cel)
    if c is None:
        c = {"cel": cel, "alarms": []}
        rmod["cells"][cel] = c
    return c


def _smod_name(raw, fallback_rmod=""):
    """Sys_Module / SMOD 欄位 → 乾淨的 SMOD 名稱"""
    n = _s(raw)
    if not n:
        # 從 RMOD 名稱前綴推測（FXDB_RFM_... → FXDB，不是 SMOD）
        return ""
    for k in KNOWN_SMOD:
        if n.upper().startswith(k):
            return k
    # "FW2EHB_L2600_L1800" 之類的異常值 → 取底線前的部分
    if "_" in n:
        head = n.split("_")[0]
        for k in KNOWN_SMOD:
            if head.upper().startswith(k):
                return k
        return head
    return n


def _smod_key(site, name):
    """同一站台依名稱取得（或建立）SMOD，id 採 1,2,3..."""
    for k, v in site["smods"].items():
        if v["name"] == name:
            return k
    key = str(len(site["smods"]) + 1)
    site["smods"][key] = {"id": key, "name": name, "alarms": []}
    return key


def build(cell_rows, center="", is_nr=False, rmod_eac=None, smod_eac=None):
    """
    cell_rows : CoCell / nrCell 的資料列（dict）
    center    : 只取這個營運中心（空字串＝全部）
    rmod_eac  : {"rows", "id", "cel", "desc", "sev"}  細胞/RMOD 外部告警
    smod_eac  : {"rows", "id", "sid", "desc", "sev"}  SMOD 外部告警
    """
    sites = {}

    for r in cell_rows:
        if center and _s(r.get("營運中心")) != center:
            continue
        if is_nr:
            bid, cel = _s(r.get("nrBtsId")), _s(r.get("nrCellId"))
            rmod_raw = _s(r.get("rModId_rModRId"))
            rmod_name = _s(r.get("rMod"))
            rmod_desc = _s(r.get("rMod_name"))
            smod_raw = _s(r.get("SMOD"))
            cell_name = _s(r.get("nrCellName_chs")) or _s(r.get("nrCellName"))
            band = _s(r.get("freqBandIndicatorNR"))
            band = ("N" + band) if band else ""
            bw = _num(r.get("chBw_DL"))
            freq = _num(r.get("arfcnSsbPbch"))
            pci = _num(r.get("PCI"))
            az = _num(r.get("Azimuth"))
            mt = _num(r.get("M-tilt"))
            et = _num(r.get("E-tilt"))
            ant = _s(r.get("AntType"))
            cov = _s(r.get("Coverage"))
            ret_raw = r.get("RET")
            ret_sn = _s(r.get("antSerial"))
            ret_min = _num(r.get("RET_Min"))
            ret_max = _num(r.get("RET_Max"))
            baseband = _s(r.get("Baseband"))
            baseband_mix = _s(r.get("Baseband_nrbts"))
            link = _s(r.get("SFP_CPRI"))
        else:
            bid, cel = _s(r.get("lnBtsId")), _s(r.get("lnCelId"))
            rmod_raw = _s(r.get("rModId_rModRId"))
            rmod_name = _s(r.get("rmod_cell"))
            rmod_desc = _s(r.get("rmod_name_cell"))
            smod_raw = _s(r.get("Sys_Module"))
            cell_name = _s(r.get("CellName_CHS")) or _s(r.get("CellName"))
            band = _s(r.get("Band_dlChBw"))
            bw = _num(r.get("dlChBw"))
            freq = _num(r.get("earfcnDL"))
            pci = _num(r.get("PCI"))
            az = _num(r.get("Azimuth"))
            mt = _num(r.get("Mtilt"))
            et = _num(r.get("Etilt"))
            ant = _s(r.get("AntType"))
            cov = _s(r.get("Coverage"))
            ret_raw = r.get("RET")
            ret_sn = _s(r.get("ALD_serialNumber"))
            ret_min = _num(r.get("RET_Min"))
            ret_max = _num(r.get("RET_Max"))
            baseband = ""
            baseband_mix = ""
            link = ""

        if not bid or not cel:
            continue
        rid = _rmod_no(rmod_raw)
        if not rid:
            continue

        site = _site(sites, bid)
        rmod = _rmod(site, rid)
        if rmod_name and not rmod["name"]:
            rmod["name"] = rmod_name
        if rmod_desc and not rmod["desc"]:
            rmod["desc"] = rmod_desc

        # ---- SMOD ----
        smod_name = _smod_name(smod_raw, rmod_name)
        if smod_name:
            skey = _smod_key(site, smod_name)
            rmod["smod"] = skey

        # ---- BBMOD / Baseband ----
        if is_nr:
            if baseband_mix:
                for cnt, name in _RE_BASEBAND.findall(baseband_mix):
                    for b in site["bbs"].values():
                        if b["name"] == name:
                            break
                    else:
                        key = str(len(site["bbs"]) + 1)
                        site["bbs"][key] = {"id": key, "name": name, "smod": rmod.get("smod", "")}
            if baseband:
                bkey = ""
                for k, b in site["bbs"].items():
                    if b["name"] == baseband:
                        bkey = k
                        break
                if not bkey:
                    bkey = str(len(site["bbs"]) + 1)
                    site["bbs"][bkey] = {"id": bkey, "name": baseband, "smod": rmod.get("smod", "")}
                rmod["bb"] = bkey
            if link:
                rmod["link"] = link
        else:
            bb = _bb_no(_s(r.get("bbModId_bbModRId")))
            bname = _s(r.get("bbMod_R"))
            if bb or bname:
                if not bb:
                    bb = "?"
                b = site["bbs"].setdefault(bb, {"id": bb, "name": bname or "", "smod": rmod.get("smod", "")})
                if bname and not b["name"]:
                    b["name"] = bname
                if not rmod["bb"]:
                    rmod["bb"] = bb
                if not rmod["port"]:
                    rmod["port"] = _port(r.get("bbMod_PortId"))

        # ---- Cell ----
        cell = _cell(rmod, cel)
        if cell_name and not cell.get("n"):
            cell["n"] = cell_name
        for key, val in (("pci", pci), ("band", band), ("bw", bw), ("freq", freq),
                         ("az", az), ("mt", mt), ("et", et), ("ant", ant), ("cov", cov)):
            if val not in (None, "") and key not in cell:
                cell[key] = val
        ret_tilt = _num(ret_raw)
        if ret_tilt is not None or ret_sn:
            ret = {"tilt": ret_tilt, "min": ret_min, "max": ret_max, "sn": ret_sn}
            cell["ret"] = {k: v for k, v in ret.items() if v not in (None, "")}

    # ---- 外部告警 ----
    if rmod_eac:
        rows = rmod_eac.get("rows") or []
        id_col = rmod_eac.get("id", "mrbtsId")
        cel_col = rmod_eac.get("cel") or ("nrCellId" if is_nr else "lnCelId")
        desc_col = rmod_eac.get("desc", "Description")
        sev_col = rmod_eac.get("sev", "severity")
        for r in rows:
            if center and _s(r.get("營運中心")) and _s(r.get("營運中心")) != center:
                continue
            bid = _s(r.get(id_col))
            cel = _s(r.get(cel_col))
            txt, cel_from_desc = _clean_alarm_text(r.get(desc_col))
            sv = _sev(r.get(sev_col))
            if not bid or not txt:
                continue
            site = sites.get(bid)
            if site is None:
                continue
            target = None
            if cel:
                for rm in site["rmods"].values():
                    if cel in rm["cells"]:
                        target = rm["cells"][cel]
                        break
            if target is not None:
                _add_alarm(target["alarms"], txt, sv)
            elif cel_from_desc:
                for rm in site["rmods"].values():
                    if cel_from_desc in rm["cells"]:
                        _add_alarm(rm["cells"][cel_from_desc]["alarms"], txt, sv)
                        target = rm["cells"][cel_from_desc]
                        break
            if target is None:
                _add_alarm(site["alarms"], txt, sv)

    if smod_eac:
        rows = smod_eac.get("rows") or []
        id_col = smod_eac.get("id", "mrbtsId")
        sid_col = smod_eac.get("sid", "sModId")
        desc_col = smod_eac.get("desc", "Description")
        sev_col = smod_eac.get("sev", "severity")
        for r in rows:
            if center and _s(r.get("營運中心")) and _s(r.get("營運中心")) != center:
                continue
            bid = _s(r.get(id_col))
            txt, _ = _clean_alarm_text(r.get(desc_col))
            sv = _sev(r.get(sev_col))
            site = sites.get(bid)
            if site is None or not txt or not site["smods"]:
                continue
            sid = _s(r.get(sid_col))
            sm = site["smods"].get(sid)
            if sm is None:                      # sModId 對不上（或只有 1 個 SMOD）→ 掛到第一個
                sm = next(iter(site["smods"].values()))
            _add_alarm(sm["alarms"], txt, sv)

    return _clean(sites)


def _clean(sites):
    """dict → list、排序、移除空欄位（縮小檔案）"""
    out = {}
    for bid in sorted(sites, key=_sort_key):
        s = sites[bid]
        smods = []
        for sm in sorted(s["smods"].values(), key=lambda x: _sort_key(x["id"])):
            d = {"id": sm["id"], "name": sm["name"]}
            if sm["alarms"]:
                d["alarms"] = sm["alarms"]
            smods.append(d)
        bbs = []
        for b in sorted(s["bbs"].values(), key=lambda x: _sort_key(x["id"])):
            d = {"id": b["id"], "name": b["name"]}
            if b.get("smod"):
                d["smod"] = b["smod"]
            bbs.append(d)
        rmods = []
        for rm in sorted(s["rmods"].values(), key=lambda x: _sort_key(x["id"])):
            cells = []
            for c in sorted(rm["cells"].values(), key=lambda x: _sort_key(x["cel"])):
                d = {"cel": c["cel"]}
                for k in ("n", "pci", "band", "bw", "freq", "az", "mt", "et", "ant", "cov"):
                    if c.get(k) not in (None, ""):
                        d[k] = c[k]
                if c.get("ret"):
                    d["ret"] = c["ret"]
                if c.get("alarms"):
                    d["alarms"] = c["alarms"]
                cells.append(d)
            d = {"id": rm["id"], "cells": cells}
            for k in ("name", "desc", "bb", "port", "smod", "link"):
                if rm.get(k):
                    d[k] = rm[k]
            if rm.get("alarms"):
                d["alarms"] = rm["alarms"]
            rmods.append(d)
        s_out = {}
        if smods:
            s_out["smods"] = smods
        if bbs:
            s_out["bbs"] = bbs
        s_out["rmods"] = rmods
        if s.get("alarms"):
            s_out["alarms"] = s["alarms"]
        out[bid] = s_out
    return out


def write_js(path, topo4, topo5, stamp=""):
    body = json.dumps({"updated": stamp, "4g": topo4, "5g": topo5},
                      ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("const TOPO = " + body + ";\n")
    return len(body)
