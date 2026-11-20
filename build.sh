#!/bin/bash
# Fetch today's exchange files -> build data -> page.  Writes out/index.html (public, no password since 2026-11-20), out/asof, out/data_hash.
# Does NOT touch git: Claude's scheduled task pushes out/index.html to GitHub from the cloud.
# Paths (defaults work on the Mac and in Claude's view of the Mac):
#   code   = folder of this script (~/tw-etf-flow)
#   DB     = ../tw-market-data next to it
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
REPO="$(cd "$(dirname "$0")" && pwd)"
DB="${DB:-$(cd "$REPO/../tw-market-data" && pwd)}"
cd "$REPO"
mkdir -p build out
echo "=== $(date '+%Y-%m-%d %H:%M:%S') start"

# 1) fetch the last two weeks (days already on disk are skipped; TWSE one source at a time, paced)
# END = today only after 21:00 Taipei (institutional ~15:00, margin ~21:00); earlier runs stop at yesterday,
# so a report that is not out yet is never saved as an empty "no data" day.
read START END < <(python3 -c "
import datetime as d, zoneinfo
now = d.datetime.now(zoneinfo.ZoneInfo('Asia/Taipei'))
end = now.date() if now.hour >= 21 else now.date() - d.timedelta(1)
print(end - d.timedelta(14), end)")
for s in twse_quotes twse_insti; do python3 "$DB/scripts/fetch.py" $s --root "$DB" --start "$START" --end "$END" --pause 3; done
for s in tpex_quotes tpex_insti; do python3 "$DB/scripts/fetch.py" $s --root "$DB" --start "$START" --end "$END" --pause 2; done
python3 fetch_margin.py twse_margin --root "$DB" --start "$START" --end "$END" --pause 3
python3 fetch_margin.py tpex_margin --root "$DB" --start "$START" --end "$END" --pause 2
python3 fetch_margin.py twse_bfi82u --root "$DB" --start "$START" --end "$END" --pause 3
python3 fetch_margin.py tpex_insti_sum --root "$DB" --start "$START" --end "$END" --pause 2

# 2) data + page
python3 build_data.py --root "$DB" --themes themes.json --out build/data.json
python3 render_page.py --data build/data.json --template template.html --sankey sankey_template.html --out build/page.html
python3 -c "import json;print(json.load(open('build/data.json'))['asof'])" > out/asof
python3 -c "import json,hashlib;d=json.load(open('build/data.json'));d.pop('built_utc');print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest())" > out/data_hash

# 3) publish copy (public page; owner removed the password on 2026-11-20)
BEFORE=$(date +%s)
cp build/page.html out/index.html
[ "$(stat -c %Y out/index.html 2>/dev/null || stat -f %m out/index.html)" -ge "$BEFORE" ] || { echo "ERROR: page not refreshed"; exit 3; }
grep -q "元大台灣50" out/index.html || { echo "ERROR: page has no ETF data"; exit 3; }
if grep -q -e "staticrypt" -e "validation.html" out/index.html; then echo "ERROR: password page or 驗證 link still in page"; exit 3; fi
echo "OK out/index.html ($(wc -c < out/index.html) bytes, public), data as of $(cat out/asof)"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') done"
