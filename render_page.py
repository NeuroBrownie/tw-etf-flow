"""Build the page: data.json -> template.html (+ sankey_template.html in a tab) -> page.html.
The output is unencrypted; never commit it to the public repo (publish.sh encrypts it first).

  python3 render_page.py --data data.json --template template.html [--sankey sankey_template.html] --out page.html
"""
import argparse, html, json
ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--template", required=True)
ap.add_argument("--sankey"); ap.add_argument("--out", required=True)
a = ap.parse_args()
data = json.load(open(a.data, encoding="utf-8"))
blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
page = open(a.template, encoding="utf-8").read()
assert page.count("/*DATA*/null") == 1
page = page.replace("/*DATA*/null", blob)
if "<!--SANKEY-->" in page:
    if not a.sankey: raise SystemExit("template has a 流向圖 tab: pass --sankey")
    sk = open(a.sankey, encoding="utf-8").read()
    assert sk.count("/*DATA*/null") == 1
    sk = sk.replace("/*DATA*/null", "parent.__D")          # the tab reads the main page's data, no second copy
    page = page.replace("<!--SANKEY-->", html.escape(sk, quote=True))
open(a.out, "w", encoding="utf-8").write(page)
print(f"wrote {a.out} ({len(page.encode()):,} bytes), data as of {data['asof']}")
