#!/bin/bash
# Fetch today's exchange files -> build data -> page -> encrypt.  Writes out/index.html (encrypted), out/asof, out/data_hash.
# Does NOT touch git: Claude's scheduled task pushes out/index.html to GitHub from the cloud.
# Paths (defaults work on the Mac and in Claude's view of the Mac):
#   code   = folder of this script (~/tw-etf-flow)
#   DB     = ../tw-market-data next to it
#   PWFILE = $DB/.secrets/tw-etf-flow.pw  (one line; never printed, never committed)
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
REPO="$(cd "$(dirname "$0")" && pwd)"
DB="${DB:-$(cd "$REPO/../tw-market-data" && pwd)}"
PWFILE="${PWFILE:-$DB/.secrets/tw-etf-flow.pw}"
cd "$REPO"
mkdir -p build out
echo "=== $(date '+%Y-%m-%d %H:%M:%S') start"
[ -s "$PWFILE" ] || { echo "ERROR: password file missing: $PWFILE"; exit 2; }

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

# 2) data + page (unencrypted copies stay in build/; never pushed)
python3 build_data.py --root "$DB" --themes themes.json --out build/data.json
python3 render_page.py --data build/data.json --template template.html --sankey sankey_template.html --out build/page.html
python3 -c "import json;print(json.load(open('build/data.json'))['asof'])" > out/asof
python3 -c "import json,hashlib;d=json.load(open('build/data.json'));d.pop('built_utc');print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest())" > out/data_hash

# 3) encrypt with the fixed salt in .staticrypt.json (keeps friends' "記住我" working across updates)
BEFORE=$(date +%s)
STATICRYPT_PASSWORD="$(cat "$PWFILE")" npx --yes staticrypt@3.5.4 build/page.html --short --remember 30 \
  --config .staticrypt.json -d build/enc \
  --template-title "台股 ETF 法人進出表" --template-instructions "請輸入密碼" --template-button "開啟" \
  --template-placeholder "密碼" --template-remember "記住我（30 天）" --template-error "密碼不對" \
  --template-toggle-show "顯示密碼" --template-toggle-hide "隱藏密碼" \
  --template-color-primary "#4c8dff" --template-color-secondary "#111418" >/dev/null
[ "$(stat -c %Y build/enc/page.html 2>/dev/null || stat -f %m build/enc/page.html)" -ge "$BEFORE" ] || { echo "ERROR: encrypted page not refreshed"; exit 3; }
if grep -q -e "元大台灣50" -e "半導體業" build/enc/page.html; then echo "ERROR: plain text found in encrypted page"; exit 3; fi
cp build/enc/page.html out/index.html
echo "OK out/index.html ($(wc -c < out/index.html) bytes), data as of $(cat out/asof)"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') done"
