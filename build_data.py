"""台股 ETF 法人進出表 — build the page data from the exchanges' raw daily files.

  python3 build_data.py --root ~/tw-market-data --out data.json [--days 60]

Reads (never writes) tw-market-data/raw/{twse_insti,tpex_insti,twse_quotes,tpex_quotes}/YYYY/YYYYMMDD.json.gz.
Keeps the dealer split the main database drops: dealer own-account (自行買賣) vs dealer hedging (避險).

Amounts are estimates (≈): net shares × that day's average price (成交金額 ÷ 成交股數).
A security with no row in an exchange's institutional report that day had no institutional trading -> 0.
A whole trading day missing from any of the four sources -> the build stops (no silent gaps).
"""
import argparse, glob, gzip, json, os, re, sys, datetime as dt

PERIODS = [1, 5, 22]

def num(s):
    if s is None: return None
    s = re.sub(r"<[^>]*>", "", str(s)).replace(",", "").strip()
    if s in ("", "--", "---", "----", "X"): return None
    try: return float(s)
    except ValueError: return None

def load(root, src, ymd):
    p = os.path.join(root, "raw", src, ymd[:4], ymd + ".json.gz")
    return json.load(gzip.open(p)) if os.path.exists(p) else None

def is_etf(code):
    # Taiwan ETF codes all start with "00" (0050 … 00xxxx); ordinary shares never do.
    return code.startswith("00")

# Automatic grouping from the code suffix and name. It is a reading aid, not an official classification;
# fix individual codes in OVERRIDE when one is wrong.
OVERRIDE = {"0055": "台股市值/主題", "006203": "台股市值/主題", "00771": "海外股票"}
OVERSEAS = ("美", "日本", "日經", "東證", "中國", "滬深", "上證", "上証", "深100", "深証", "中証", "A50", "A股", "恒生", "香港", "韓",
            "KOSPI", "印度", "越南", "歐洲", "全球", "世界", "亞太", "新興", "NASDAQ", "納斯達克", "那斯達克", "S&P", "標普", "費城",
            "道瓊", "FANG", "MAG7", "北美", "洲際", "未來車", "基因", "生技", "潔淨能源", "電池", "元宇宙", "數位支付", "太空",
            "網路資安", "REITs", "不動產", "稀土", "5G", "未來通訊", "航運", "品牌50", "菁英55", "AI機器人", "全球AI", "電動車")

def etf_type(code, name):
    c = code.upper()
    if c in OVERRIDE: return OVERRIDE[c]
    if "主動" in name or c.endswith("A") or c.endswith("D"): return "主動式"
    if "平衡" in name or c.endswith("T"): return "平衡/多資產"
    if c.endswith("L") or "正2" in name: return "槓桿"
    if c.endswith("R") or "反1" in name: return "反向"
    if c.endswith("B") or "債" in name: return "債券"
    if c.endswith("U") or any(k in name for k in ("黃金", "原油", "石油", "白銀", "黃豆", "銅", "美元指數")): return "商品期貨"
    taiwan = any(k in name for k in ("台灣", "臺灣", "台股", "台50")) and "台美" not in name and "台日韓" not in name
    if any(k in name for k in OVERSEAS) and not taiwan: return "海外股票"
    if any(k in name for k in ("高股息", "高息", "股息", "優息", "高填息", "收益", "存股")): return "台股高股息"
    return "台股市值/主題"

def trading_days(root, since="20250101"):
    """Trading days = days TWSE published prices. Every such day must also have institutional data;
    a price day without it means the institutional report was fetched too early -> stop, don't skip."""
    days = []
    for f in sorted(glob.glob(os.path.join(root, "raw", "twse_quotes", "*", "*.json.gz"))):
        ymd = os.path.basename(f)[:8]
        if ymd < since: continue
        if json.load(gzip.open(f)).get("stat") != "OK": continue
        ins = load(root, "twse_insti", ymd)
        if not ins or ins.get("stat") != "OK":
            sys.exit(f"{ymd}: TWSE prices exist but institutional data is missing or empty. "
                     f"Delete raw/twse_insti/{ymd[:4]}/{ymd}.json.gz and re-run after ~16:00 Taipei.")
        days.append(ymd)
    return days

def margin_rows(root, ymd):
    """-> {code: change in 融資 balance, shares} for every security, or None if the day's file is missing."""
    tw, tp = load(root, "twse_margin", ymd), load(root, "tpex_margin", ymd)
    if tw is None or tp is None: return None
    out = {}
    if tw.get("stat") == "OK" and len(tw.get("tables") or []) > 1:
        for r in tw["tables"][1].get("data") or []:
            prev, now = num(r[5]), num(r[6])
            if prev is not None and now is not None: out[r[0].strip()] = (now - prev) * 1000
    for r in (tp.get("tables") or [{}])[0].get("data") or []:
        prev, now = num(r[2]), num(r[6])
        if prev is not None and now is not None: out[r[0].strip()] = (now - prev) * 1000
    return out

def official_totals(root, ymd):
    """Exchange-published NT$ net totals for one day, main board (BFI82U) + OTC (三大法人買賣金額彙總表).
    Includes warrants. -> dict(f, t, d) or None if either file is missing or empty."""
    tw, tp = load(root, "twse_bfi82u", ymd), load(root, "tpex_insti_sum", ymd)
    if not tw or tw.get("stat") != "OK" or not tw.get("data") or not tp: return None
    t = (tp.get("tables") or [{}])[0]
    if not t.get("data"): return None
    a = {r[0].strip(): num(r[3]) for r in tw["data"]}
    b = {r[0].strip(): num(r[3]) for r in t["data"]}
    try:
        return dict(f=a["外資及陸資(不含外資自營商)"] + a["外資自營商"] + b["外資及陸資合計"],
                    t=a["投信"] + b["投信"],
                    d=a["自營商(自行買賣)"] + a["自營商(避險)"] + b["自營商合計"])
    except (KeyError, TypeError):
        return None

def day_rows(root, ymd):
    """-> ({code: dict(market, name, f, t, do, dh, m, vol, val, close)} for every security, market totals) for one day."""
    out, allpx, mkt = {}, {}, dict(val=0.0, f=0.0, t=0.0, d=0.0, m=0.0)
    tq, ti, oq, oi = (load(root, s, ymd) for s in ("twse_quotes", "twse_insti", "tpex_quotes", "tpex_insti"))
    for name, d in (("twse_quotes", tq), ("twse_insti", ti), ("tpex_quotes", oq), ("tpex_insti", oi)):
        if d is None: sys.exit(f"missing {name} for {ymd}: fetch it first")
    # prices
    if tq.get("stat") != "OK": sys.exit(f"twse_quotes {ymd} not OK")
    t = next(t for t in tq["tables"] if t.get("fields") and t["fields"][0] == "證券代號")
    f = {k: i for i, k in enumerate(t["fields"])}
    for r in t["data"]:
        c = r[0].strip(); v, q = num(r[f["成交金額"]]), num(r[f["成交股數"]])
        mkt["val"] += v or 0; allpx[c] = (v / q) if q else num(r[f["收盤價"]])
        out[c] = dict(market="上市", name=r[1].strip(), vol=num(r[f["成交股數"]]), val=num(r[f["成交金額"]]),
                      close=num(r[f["收盤價"]]), f=0.0, t=0.0, do=0.0, dh=0.0, units=None)
    for r in (oq.get("tables") or [{}])[0].get("data") or []:
        c = r[0].strip(); v, q = num(r[8]), num(r[7])
        mkt["val"] += v or 0; allpx[c] = (v / q) if q else num(r[2])
        out[c] = dict(market="上櫃", name=r[1].strip(), vol=num(r[7]), val=num(r[8]), close=num(r[2]),
                      f=0.0, t=0.0, do=0.0, dh=0.0, units=num(r[14]))
    # institutional, TWSE (T86)
    fi = {k: i for i, k in enumerate(ti["fields"])}
    g = lambda r, k: num(r[fi[k]]) or 0.0
    for r in ti["data"]:
        c = r[0].strip(); px = allpx.get(c)
        if px:
            mkt["f"] += (g(r, "外陸資買賣超股數(不含外資自營商)") + g(r, "外資自營商買賣超股數")) * px
            mkt["t"] += g(r, "投信買賣超股數") * px; mkt["d"] += g(r, "自營商買賣超股數") * px
        if c in out:
            o = out[c]
            o["f"] = g(r, "外陸資買賣超股數(不含外資自營商)") + g(r, "外資自營商買賣超股數")
            o["t"] = g(r, "投信買賣超股數")
            o["do"] = g(r, "自營商買賣超股數(自行買賣)")
            o["dh"] = g(r, "自營商買賣超股數(避險)")
            tot = g(r, "三大法人買賣超股數")
            assert abs(o["f"] + o["t"] + o["do"] + o["dh"] - tot) < 1, (ymd, c)
    if (oq.get("tables") or [{}])[0].get("data") and not (oi.get("tables") or [{}])[0].get("data"):
        sys.exit(f"{ymd}: TPEx prices exist but institutional data is empty. "
                 f"Delete raw/tpex_insti/{ymd[:4]}/{ymd}.json.gz and re-run later.")
    # institutional, TPEx: 10 foreign total net, 13 trust net, 16 dealer own net, 19 dealer hedge net, 23 total
    for r in (oi.get("tables") or [{}])[0].get("data") or []:
        c = r[0].strip(); px = allpx.get(c)
        if px:
            mkt["f"] += (num(r[10]) or 0) * px; mkt["t"] += (num(r[13]) or 0) * px; mkt["d"] += (num(r[22]) or 0) * px
        if c in out:
            o = out[c]
            o["f"], o["t"], o["do"], o["dh"] = (num(r[i]) or 0.0 for i in (10, 13, 16, 19))
            assert abs(o["f"] + o["t"] + o["do"] + o["dh"] - (num(r[23]) or 0)) < 1, (ymd, c)
    mg = margin_rows(root, ymd)
    for c, o in out.items(): o["m"] = None if mg is None else mg.get(c, 0.0)
    if mg is None: mkt["m"] = None
    else:
        for c, dm in mg.items():
            if allpx.get(c): mkt["m"] += dm * allpx[c]
    return out, mkt

IND = {"01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維", "05": "電機機械", "06": "電器電纜",
       "08": "玻璃陶瓷", "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
       "15": "航運業", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學工業",
       "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業",
       "28": "電子零組件業", "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業", "33": "農業科技業",
       "34": "電子商務", "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證"}

def industries(root):
    """code -> industry name, from the exchanges' current company list (raw/companies_current.csv)."""
    import csv
    p = os.path.join(root, "raw", "companies_current.csv")
    if not os.path.exists(p): return {}
    return {r["code"].strip(): IND.get((r.get("industry") or "").strip().zfill(2), "其他") for r in csv.DictReader(open(p, encoding="utf-8"))}

def group_of(code, ind):
    if is_etf(code): return "ETF"
    if code in ind: return ind[code]
    if code.startswith("02") or code.startswith("01") or (len(code) > 4 and code[-1].isalpha()): return "ETN／REIT／特別股"
    return "未分類（新上市等）"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--themes", help="JSON {theme name: [codes]} for the 自編主題族群 view")
    ap.add_argument("--days", type=int, default=max(PERIODS) + 1)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    days = trading_days(root)[-a.days:]
    per_day, mkt_day = [], []
    for ymd in days:
        rows, mkt = day_rows(root, ymd); per_day.append((ymd, rows)); mkt_day.append(mkt)

    last_px = {}   # previous average price, used only if an ETF has net flow but no trade that day (rare)
    daily = []     # per day: {code: [f, t, do, dh] in NT$, val}
    for ymd, rows in per_day:
        dd = {}
        for c, o in rows.items():
            px = (o["val"] / o["vol"]) if o["vol"] else None
            if px is None: px = last_px.get(c) or o["close"]
            else: last_px[c] = px
            # zero net shares is NT$0 even on a day with no price; unknown only if shares are missing or nonzero without a price
            amt = [None if o[k] is None else 0.0 if o[k] == 0 else None if px is None else o[k] * px for k in ("f", "t", "do", "dh", "m")]
            dd[c] = dict(amt=amt, val=o["val"] or 0.0)
        daily.append(dd)

    latest = per_day[-1][1]
    meta = {c: dict(name=o["name"], market=o["market"], type=etf_type(c, o["name"]), close=o["close"]) for c, o in latest.items() if is_etf(c)}
    names = {c: o["name"] for c, o in latest.items()}
    # securities that traded earlier in the window but not on the last day (e.g. delisted) keep their last known name
    for ymd, rows in per_day:
        for c, o in rows.items():
            names.setdefault(c, o["name"])
            if is_etf(c): meta.setdefault(c, dict(name=o["name"], market=o["market"], type=etf_type(c, o["name"]), close=None))
    ind = industries(root)
    secs = {c: [n, group_of(c, ind)] for c, n in names.items()}

    periods = {}
    for n in PERIODS:
        if n > len(daily): continue
        win = daily[-n:]
        rows = []
        for c, m in meta.items():
            s = [0.0] * 5; val = 0.0; seen = False; unknown = [False] * 5
            for dd in win:
                if c not in dd: continue
                seen = True; val += dd[c]["val"]
                for k in range(5):
                    if dd[c]["amt"][k] is None: unknown[k] = True
                    else: s[k] += dd[c]["amt"][k]
            if not seen: continue
            s = [None if unknown[k] else round(s[k]) for k in range(5)]
            rows.append(dict(code=c, **m, f=s[0], t=s[1], do=s[2], dh=s[3], m=s[4], val=round(val)))
        # every security, compact: [code, f, t, d_own, d_hedge, margin, value] in 萬元 (null = missing)
        allrows = []
        for c in secs:
            s = [0.0] * 5; val = 0.0; seen = False; unknown = [False] * 5
            for dd in win:
                if c not in dd: continue
                seen = True; val += dd[c]["val"]
                for k in range(5):
                    if dd[c]["amt"][k] is None: unknown[k] = True
                    else: s[k] += dd[c]["amt"][k]
            if not seen: continue
            v = [None if unknown[k] else round(s[k] / 1e4) for k in range(5)]
            if not any(v) and val == 0: continue
            allrows.append([c] + v + [round(val / 1e4)])
        mk = mkt_day[-n:]
        # cards: our warrant-free average-price estimate (same universe as the flow chart);
        # off_*: the exchanges' official totals incl. warrants, shown only in the 「交易所官方統計（含權證）」 fold-out
        market = {"val": sum(x["val"] for x in mk)}
        # same per-security amounts as the flow chart, so the cards equal the chart's totals
        market["f"] = sum((r[1] or 0) for r in allrows) * 1e4
        market["t"] = sum((r[2] or 0) for r in allrows) * 1e4
        market["d"] = sum((r[3] or 0) + (r[4] or 0) for r in allrows) * 1e4
        offs = [official_totals(root, ymd) for ymd in days[-n:]]
        for k in ("f", "t", "d"): market["off_" + k] = None if any(o is None for o in offs) else sum(o[k] for o in offs)
        market["m"] = None if any(x["m"] is None for x in mk) else sum(x["m"] for x in mk)
        periods[str(n)] = dict(start=days[-n], end=days[-1], rows=rows, market=market, all=allrows)

    # units outstanding (TPEx publishes 發行股數 for its listings) — change over each window
    units = {}
    for n in PERIODS:
        if n > len(per_day): continue
        a0, a1 = per_day[-n - 1][1] if n < len(per_day) else None, per_day[-1][1]
        if a0 is None: continue
        for c, o in a1.items():
            if is_etf(c) and o["units"] and c in a0 and a0[c]["units"]:
                units.setdefault(c, {})[str(n)] = o["units"] - a0[c]["units"]

    out = dict(asof=days[-1], built_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               trading_days=days, periods=periods, units_change=units, securities=secs,
               themes={k: v for k, v in (json.load(open(a.themes, encoding="utf-8")) if a.themes else {}).items() if not k.startswith("_")},
               source="TWSE T86 / MI_INDEX / MI_MARGN, TPEx 三大法人日報 / 上櫃收盤行情 / 融資融券餘額")
    with open(a.out, "w", encoding="utf-8") as fh: json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    p1 = periods["1"]["rows"]
    tot = lambda k: sum(r[k] or 0 for r in p1) / 1e8
    print(f"as of {days[-1]}: {len(meta)} ETFs, {len(days)} days | 1-day 億: foreign {tot('f'):.1f}, trust {tot('t'):.1f}, "
          f"dealer own {tot('do'):.1f}, dealer hedge {tot('dh'):.1f}, margin {tot('m'):.1f}")

if __name__ == "__main__":
    main()
