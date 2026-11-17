# 台股 ETF 法人進出表

外資、投信、自營商（自行買賣／避險分開）在台股 ETF 的買賣超與融資增減，1／5／22 日合計，附流向圖（全市場產業別／自編主題族群）。
資料來自臺灣證券交易所與證券櫃檯買賣中心的公開資料。網頁內容以密碼加密（StaticCrypt 3.5.4）；這個 repo 只放程式和加密後的 `index.html`。

只描述法人實際的買賣，不是投資建議。

## 怎麼運作
- 每個平日晚上，Claude 的排程任務在你的 Mac 上執行 `~/tw-etf-flow/build.sh`：從交易所下載當天檔案到 `~/tw-market-data/raw/`，跑 `build_data.py` → `render_page.py` → 加密，輸出 `out/index.html`。
- 接著由 Claude 把加密後的 `index.html` 推到這個 repo 的 `main`（Mac 本身不需要登入 GitHub）。資料沒變就不推。
- 密碼存在 `~/tw-market-data/.secrets/tw-etf-flow.pw`，不在 repo 裡，程式只用它來加密，不會印出。
- `.staticrypt.json` 是固定的 salt（不是秘密），讓朋友勾的「記住我」在每天更新後仍有效。

## 常用
- 換密碼：改寫 `~/tw-market-data/.secrets/tw-etf-flow.pw`，下次更新就用新密碼；舊密碼和舊的「記住我」都會失效。
- ETF 類型分錯：改 `build_data.py` 裡的 `OVERRIDE`。
- 自編主題族群：改 `themes.json`（主題名稱 → 股票代號清單）。
- 產業分類來自 `~/tw-market-data/raw/companies_current.csv`；新上市股票會先顯示「未分類」。

## 數字怎麼算
- 金額 ≈ 買賣超股數 × 當天均價（成交金額 ÷ 成交股數）。
- 「法人合計」＝外資＋投信＋自營（自行），不含自營（避險）。
- 融資＝融資餘額增減 × 當天均價，和法人買賣超分開。
- 受益權單位變化：只有上櫃 ETF 有每日公開數字。
