# -*- coding: utf-8 -*-
"""
站台架構資料產生器
參考 Nokia NetAct 的 SMOD/BBMOD → RMOD → RET → Cell 檢視，輸出 topo.js。

輸出結構（topo.js）：
{
  "updated": "20261103",
  "meta": {"4g": {"cell": "20261021", "sfp": "20260821"}, "5g": {...}},
  "4g": {
    "411480": {
      "smods": [{"id": "1", "name": "ASIB", "alarms": [{"t": "Door", "s": "major"}]}],
      "bbs":   [{"id": "1", "name": "ABIA", "smod": "1"}],
      "rmods": [{
        "id": "1", "name": "FXDB", "desc": "FXDB_RFM_3T6R_L900 - 3x80W",
        "smod": "1", "ants": "1, 2",
        "links": [                                     # RF/OPT 埠連線
          {"t": "bb", "bb": "1", "p": "RF3", "o": "1",
           "bw": "1534", "bm": "AOZNG", "w": "1531", "m": "AOYCO"}, # SFP 波長／型號
          {"t": "rmod", "up": "13", "p": "OPT2", "o": "1"}   # 上游 RMOD-13 OPT2 → RMOD OPT1
        ],
        "alarms": [{"t": "AC Power", "s": "major"}],   # RMOD 層級
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
  4G: LTE_CoCell（RMOD/BBMOD/SMOD/RET/細胞） + LTE_RMOD_SFP（RF/OPT 埠）
      + LTE_RMOD_EAC / LTE_SMOD_EAC（告警）
  5G: nrCell（RMOD/SMOD/RET/細胞/Baseband） + NR_RMOD_SFP（RF/OPT 埠）
      + NR_RMOD_EAC / NR_SMOD_EAC（告警）
"""
import json
import re

# 已知的模組名稱（用來從 rmod_name_cell 之類的長字串取前綴時做校正）
KNOWN_SMOD = ("FSMF", "ASIA", "ASIB", "ASIK", "ASIL", "ABIO", "ABIL")

# SFP 波長 → 型號對照表（未列出的波長只顯示波長、型號空白）
# 一般 waveLength（CWDM）
SFP_WAVE_MODEL = {
    "1271": "AOYCA", "1291": "AOYCB", "1311": "AOYCC", "1331": "AOYCD",
    "1351": "AOYCE", "1371": "AOYCF", "1511": "AOYCN", "1531": "AOYCO",
    "1551": "AOYCP", "1571": "AOYCQ", "1591": "AOYCR", "1611": "AOYCS",
}
# rMod_waveLength（射頻設備／OPT 側）
SFP_RMOD_WAVE_MODEL = {
    "1533": "AOZNF", "1535": "AOZNH", "1536": "AOZNK", "1538": "AOZNM",
    "1539": "AOZNO", "1541": "AOZNQ", "1542": "AOZNS", "1544": "AOZNU",
    "1546": "AOZNW", "1547": "AOZLZ", "1549": "AOZMB", "1550": "AOZMD",
    "1552": "AOZOE", "1554": "AOZOG", "1555": "AOZOI", "1557": "AOZOL",
    "1558": "AOZON", "1560": "AOZOP",
}
# bbMod_waveLength（容量卡板／RF 側）
SFP_BBMOD_WAVE_MODEL = {
    "1534": "AOZNG", "1535": "AOZNI", "1537": "AOZNL", "1538": "AOZNN",
    "1540": "AOZNP", "1542": "AOZNR", "1543": "AOZNT", "1545": "AOZNV",
    "1546": "AOZNX", "1548": "AOZMA", "1550": "AOZMC", "1551": "AOZME",
    "1553": "AOZOF", "1554": "AOZOH", "1556": "AOZOK", "1558": "AOZOM",
    "1559": "AOZOO", "1561": "AOZOQ",
}


_RE_RMOD = re.compile(r"RMOD[-_ ]?(\d+)")
_RE_BB = re.compile(r"bbMod[-_ ]?(\d+)", re.I)
# EAC Description：Cell_013_Door / " Cell_013_AC Power" / AC Power
_RE_CELL_ALARM = re.compile(r"^[Cc]ell[_ ]*(\d+)[_ ]+(.+)$")
_RE_BASEBAND = re.compile(r"(\d+)\s*\*\s*([A-Za-z0-9]+)")
_RE_TAIL_NUM = re.compile(r"(\d+)\s*$")


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


def _tail_no(raw):
    """'OPT_IF2' / '2' / 'OPT_IF1' → '2' / '2' / '1'"""
    s = _s(raw)
    m = _RE_TAIL_NUM.search(s)
    return m.group(1) if m else s


def _ants(raw, rid):
    """rMod_antPortId → 該 RMOD 使用的天線埠（'1, 2' / 複合值取本 RMOD 段）"""
    s = _s(raw)
    if not s:
        return ""
    if "RMOD" not in s.upper():
        return s
    out = []
    for m in re.finditer(r"RMOD[-_ ]?(\d+)/[^_]*\[([^\]]*)\]", s):
        if m.group(1) == rid:
            out.append(m.group(2).strip())
    return ", ".join(v for v in out if v)


def _wave(raw):
    """'1534' / '1534nm' / '1534 nm' → '1534'"""
    s = _s(raw).upper().replace("NM", "").strip()
    m = re.match(r"^(\d{3,4})", s)
    return m.group(1) if m else ""


def _sfp_info(raw, table):
    """波長 → (波長, 型號)。型號依指定表查，查不到再查一般 CWDM 表。"""
    wl = _wave(raw)
    if not wl:
        return "", ""
    return wl, (table.get(wl) or SFP_WAVE_MODEL.get(wl, ""))


def _set_sfp(link, rmod_wl, peer_wl, peer_table=SFP_RMOD_WAVE_MODEL):
    """把本機 OPT 側與對端埠的 SFP 波長／型號寫進 link"""
    w, m = _sfp_info(rmod_wl, SFP_RMOD_WAVE_MODEL)
    if w:
        link["w"] = w
        if m:
            link["m"] = m
    bw, bm = _sfp_info(peer_wl, peer_table)
    if bw:
        link["bw"] = bw
        if bm:
            link["bm"] = bm


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
             "smod": "", "ants": "", "bbn": "", "links": [],
             "alarms": [], "cells": {}}
        site["rmods"][rid] = r
    return r


def _cell(rmod, cel):
    c = rmod["cells"].get(cel)
    if c is None:
        c = {"cel": cel, "alarms": []}
        rmod["cells"][cel] = c
    return c


def _add_link(rmod, link):
    """同一 RMOD 相同連線只留一筆（SFP 檔每個細胞會重複列）"""
    for l in rmod["links"]:
        if (l.get("t"), l.get("bb"), l.get("up"), l.get("p"), l.get("o")) == \
           (link.get("t"), link.get("bb"), link.get("up"), link.get("p"), link.get("o")):
            return
    rmod["links"].append(link)


def _bb(site, bbid, name, smod):
    key = bbid or (name and ("n:" + name)) or ""
    if not key:
        return ""
    b = site["bbs"].get(key)
    if b is None:
        b = {"id": bbid or name, "name": name, "smod": smod}
        site["bbs"][key] = b
    elif name and not b["name"]:
        b["name"] = name
    if not b.get("smod") and smod:
        b["smod"] = smod
    return key


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


def build(cell_rows, center="", is_nr=False, rmod_eac=None, smod_eac=None,
          sfp_rows=None):
    """
    cell_rows : CoCell / nrCell 的資料列（dict）
    center    : 只取這個營運中心（空字串＝全部）
    rmod_eac  : {"rows", "id", "cel", "desc", "sev"}  細胞/RMOD 外部告警
    smod_eac  : {"rows", "id", "sid", "desc", "sev"}  SMOD 外部告警
    sfp_rows  : SFP 檔資料列（提供 BBMOD RF 埠 ↔ RMOD OPT 埠連線）
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
            ants_raw = ""
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
            ants_raw = _s(r.get("rMod_antPortId"))

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
        if not rmod["ants"]:
            rmod["ants"] = _ants(ants_raw, rid)
        if baseband and not rmod["bbn"]:
            rmod["bbn"] = baseband

        # ---- SMOD ----
        smod_name = _smod_name(smod_raw, rmod_name)
        if smod_name:
            skey = _smod_key(site, smod_name)
            rmod["smod"] = skey

        # ---- BBMOD / Baseband ----
        if is_nr:
            if baseband_mix and not site.get("mix"):
                site["mix"] = baseband_mix
            if link:
                rmod["link"] = link
        else:
            bb = _bb_no(_s(r.get("bbModId_bbModRId")))
            bname = _s(r.get("bbMod_R"))
            # 'SmallCell' / '接到_sMod-1_portId-1' 不是容量卡板型號（一體式或無 BB 資料）
            if bname.lower() == "smallcell" or bname.startswith("接到_"):
                if not rmod["bbn"]:
                    rmod["bbn"] = "SmallCell" if bname.lower() == "smallcell" else bname.replace("接到_", "")
                bname = ""
            if bb or bname:
                if not bb:
                    bb = "?"
                _bb(site, bb, bname, rmod.get("smod", ""))
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

    # ---- SFP：BBMOD RF 埠 ↔ RMOD OPT 埠 ----
    if sfp_rows:
        sid_col = "nrBtsId" if is_nr else "lnBtsId"
        for r in sfp_rows:
            if center and _s(r.get("營運中心")) != center:
                continue
            bid = _s(r.get(sid_col))
            rid = _s(r.get("rModId"))
            if not bid or not rid:
                continue
            site = sites.get(bid)
            if site is None:
                continue
            rmod = site["rmods"].get(rid)
            if rmod is None:
                # SFP 檔較舊，該 RMOD 已不在現行細胞檔 → 略過
                continue

            bbphy = _s(r.get("bbMod_physicalPort"))
            bbid = _s(r.get("bbModId"))
            bname = _s(r.get("bbModName"))
            up = _s(r.get("rModId2"))
            linked = _s(r.get("linked_Object")).upper()
            opt_no = _tail_no(r.get("rMod_portId"))
            opt = ("OPT" + opt_no) if opt_no else ""
            upper_phy = bbphy.upper()

            if (linked == "RMOD" or (not bbid and up and upper_phy.startswith("OPT"))) and up:
                # RMOD → RMOD 級聯：本站的 OPT 接到上游 RMOD 的 OPT
                link = {"t": "rmod", "up": up, "p": "OPT" + _tail_no(bbphy), "o": opt}
            elif upper_phy.startswith("RF") or upper_phy.startswith("S_RF"):
                key = _bb(site, bbid, bname, rmod.get("smod", "")) if (bbid or bname) else ""
                link = {"t": "bb", "p": bbphy, "o": opt}
                if key:
                    link["bb"] = site["bbs"][key]["id"]
                    if not rmod["bb"]:
                        rmod["bb"] = site["bbs"][key]["id"]
            elif bbid:
                key = _bb(site, bbid, bname, rmod.get("smod", ""))
                link = {"t": "bb", "bb": site["bbs"][key]["id"], "p": bbphy or "OPT", "o": opt}
                if not rmod["bb"]:
                    rmod["bb"] = site["bbs"][key]["id"]
            else:
                link = {"t": "?", "p": bbphy, "o": opt}
            _set_sfp(link, r.get("rMod_waveLength"), r.get("bbMod_waveLength"),
                     SFP_RMOD_WAVE_MODEL if upper_phy.startswith("OPT") else SFP_BBMOD_WAVE_MODEL)
            _add_link(rmod, link)

    # ---- 沒有 SFP 連線的 RMOD：用細胞檔的 BBMOD/RF 埠補 ----
    for site in sites.values():
        # 5G：若整站都沒有 SFP 的 BBMOD 資料，用細胞檔 Baseband_nrbts 建立容量卡板
        if not site["bbs"] and site.get("mix"):
            smod = next(iter(site["smods"].values()), {}).get("id", "")
            n = 0
            for cnt, name in _RE_BASEBAND.findall(site["mix"]):
                for _ in range(int(cnt)):
                    n += 1
                    _bb(site, str(n), name, smod)
        for rmod in site["rmods"].values():
            if rmod["links"]:
                continue
            if rmod["bb"] and rmod["bb"] != "?":
                port = ("RF" + rmod["port"]) if rmod["port"] else ""
                _add_link(rmod, {"t": "bb", "bb": rmod["bb"], "p": port, "o": "", "x": 1})

    # ---- 級聯方向正規化 ----
    # SFP 的 linked_Object=RMOD 只記錄「兩台 RMOD 相接」，rModId2 是對端。
    # 有接 BBMOD RF 埠的那一台視為上游，另一台掛在它下面。
    for site in sites.values():
        has_bb = {rid: any(l.get("t") == "bb" and l.get("bb") for l in rm["links"])
                  for rid, rm in site["rmods"].items()}
        moved = []
        seen_pairs = set()
        for rm in site["rmods"].values():
            keep = []
            for l in rm["links"]:
                if l.get("t") != "rmod":
                    keep.append(l)
                    continue
                peer = l.get("up") or ""
                if not peer or peer not in site["rmods"]:
                    keep.append(l)                     # 上游不在現行資料，保留提示
                    continue
                if not has_bb.get(rm["id"]) and has_bb.get(peer):
                    down, up = rm["id"], peer
                    up_port, down_port = l.get("p", ""), l.get("o", "")
                else:
                    down, up = peer, rm["id"]
                    up_port, down_port = l.get("o", ""), l.get("p", "")
                pair = (up, down)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                nl = {"t": "rmod", "up": up, "p": up_port, "o": down_port}
                if down == rm["id"]:
                    for k in ("w", "m", "bw", "bm"):
                        if k in l:
                            nl[k] = l[k]
                    keep.append(nl)
                else:
                    # 這筆在原 RMOD 是上游；移到下游後「本機／對端」互換
                    for src, dst in (("bw", "w"), ("bm", "m"), ("w", "bw"), ("m", "bm")):
                        if src in l:
                            nl[dst] = l[src]
                    moved.append((down, nl))
            rm["links"] = keep
        for rid, l in moved:
            _add_link(site["rmods"][rid], l)

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
            # 沒有被任何 RMOD 連到的 BBMOD（例如 5G 只有 Baseband 欄位）仍保留，
            # 讓前端可以提示「此容量卡板無連線資料」
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
            for k in ("name", "desc", "bb", "smod", "link", "bbn", "ants"):
                if rm.get(k):
                    d[k] = rm[k]
            if rm.get("links"):
                d["links"] = rm["links"]
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


def write_js(path, topo4, topo5, stamp="", meta=None):
    body = json.dumps({"updated": stamp, "meta": meta or {}, "4g": topo4, "5g": topo5},
                      ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("const TOPO = " + body + ";\n")
    return len(body)
