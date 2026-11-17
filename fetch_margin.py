"""Download daily margin (融資融券) files from TWSE / TPEx into tw-market-data/raw/, resumable.

  python3 fetch_margin.py SOURCE --root ~/tw-market-data --start YYYY-MM-DD --end YYYY-MM-DD [--pause 3]

SOURCE: twse_margin (MI_MARGN, all securities), tpex_margin (上櫃融資融券餘額),
        twse_bfi82u (上市 三大法人買賣金額統計表, official NT$ totals), tpex_insti_sum (上櫃 三大法人買賣金額彙總表).
Same conventions as tw-market-data/scripts/fetch.py: raw bytes gzipped to raw/SOURCE/YYYY/YYYYMMDD.json.gz,
one log line per request in raw/SOURCE/fetch_log.csv, days on disk skipped, stop at once if TWSE blocks.
Only stores a "no data" file for days that are already in the past by 2+ days, so a report fetched
before the exchange publishes it is retried on the next run instead of being remembered as empty.
"""
import argparse, csv, datetime as dt, gzip, hashlib, json, os, subprocess, sys, time

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"
URL = {
    "twse_margin": "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd}&selectType=ALL&response=json",
    "tpex_margin": "https://www.tpex.org.tw/www/zh-tw/margin/balance?date={slash}&response=json",
    "twse_bfi82u": "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={ymd}&response=json",
    "tpex_insti_sum": "https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&date={slash}&response=json",
}

def classify(source, body):
    if body.lstrip()[:1] == b"<": return "blocked"
    try: d = json.loads(body)
    except Exception: return "bad"
    if source == "twse_margin":
        if d.get("stat") == "OK" and len(d.get("tables") or []) > 1 and d["tables"][1].get("data"): return "ok"
        return "nodata" if "沒有符合條件" in str(d.get("stat")) or d.get("stat") == "OK" else "bad"
    if source == "twse_bfi82u":
        if d.get("stat") == "OK" and d.get("data"): return "ok"
        return "nodata" if "沒有符合條件" in str(d.get("stat")) or d.get("stat") == "OK" else "bad"
    t = (d.get("tables") or [{}])[0]
    return "ok" if t.get("data") else "nodata"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=URL); ap.add_argument("--root", required=True)
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--pause", type=float, default=3); ap.add_argument("--budget", type=float, default=600)
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    d0, d1 = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    days = [d0 + dt.timedelta(i) for i in range((d1 - d0).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    base = os.path.join(root, "raw", a.source); os.makedirs(base, exist_ok=True)
    path = lambda d: os.path.join(base, str(d.year), d.strftime("%Y%m%d") + ".json.gz")
    log = os.path.join(base, "fetch_log.csv"); new_log = not os.path.exists(log)
    todo = [d for d in days if not os.path.exists(path(d))]
    t0 = time.time(); n = {"ok": 0, "nodata": 0, "later": 0}; status = "done"
    with open(log, "a", newline="") as lf:
        w = csv.writer(lf)
        if new_log: w.writerow(["date", "fetched_utc", "status", "http", "bytes", "sha256", "url"])
        for d in todo:
            if time.time() - t0 > a.budget: status = "budget"; break
            url = URL[a.source].format(ymd=d.strftime("%Y%m%d"), slash=d.strftime("%Y/%m/%d"))
            for attempt in range(3):
                r = subprocess.run(["curl", "-sS", "--http1.1", "-m", "60", "-A", UA, "-w", "\n%{http_code}", url], capture_output=True)
                body, _, code = r.stdout.rpartition(b"\n"); code = code.decode() or "000"
                c = classify(a.source, body) if r.returncode == 0 else "bad"
                if c != "bad": break
                time.sleep(10 * (attempt + 1))
            w.writerow([d.isoformat(), dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), c, code, len(body), hashlib.sha256(body).hexdigest(), url]); lf.flush()
            if c == "blocked": status = "blocked"; break
            if c == "bad": status = "error"; print(f"{d}: unexpected response (HTTP {code}); stopping", file=sys.stderr); break
            if c == "nodata" and (dt.date.today() - d).days < 2: n["later"] += 1
            else:
                os.makedirs(os.path.dirname(path(d)), exist_ok=True)
                tmp = path(d) + ".tmp"
                with gzip.open(tmp, "wb") as f: f.write(body)
                os.replace(tmp, path(d)); n[c] += 1
            time.sleep(a.pause)
    left = sum(1 for d in days if not os.path.exists(path(d)))
    print(f"{a.source}: {n['ok']} ok, {n['nodata']} no-data, {n['later']} not yet published, {left} left, stop={status}, {time.time()-t0:.0f}s")
    sys.exit({"done": 0, "budget": 0, "blocked": 3, "error": 4}[status])

if __name__ == "__main__":
    main()
