# 文件維護準則

修改公開介面、資料語意或操作方式時，同步更新相應文件。先選擇頁面責任，再撰寫內容。

## 1. 分頁與導覽

文件入口是第一次查詢教學；其他頁面分為操作指南與參考。股票、興櫃、衍生商品、公司資料與總體資料依實際查詢入口索引。中英文使用相同路徑結構，繁體中文為 `.mdx`，英文為 `.en.mdx`；各資料夾的 `meta.json` 與 `meta.en.json` 維護排序。

## 2. 四類文件的責任

| 類型 | twmarket 的用途 | 內容界線 |
| --- | --- | --- |
| 教學 | 完成第一次股票查詢等學習流程 | 有明確起點及可觀察結果，不列完整參數 |
| 操作指南 | 完成批次報價、串流、代理或 DataFrame 轉換 | 直接解決任務，不插入架構討論 |
| 參考 | API 簽名、欄位、單位、日期範圍與例外 | 精確描述介面，不安排學習步驟 |
| 解釋 | 理解來源差異、交易日、契約映射與資料流 | 解釋機制，不混入安裝操作 |

## 3. 頁面結構

每頁提供 `title` 與 `description`。教學依序包含目標、前提、步驟及結果；操作指南包含任務、必要前提、完整程式及結果；解釋先提出需要理解的問題，再說明關係與取捨；參考以識別符分節，列出簽名與資料契約。不要建立只有連結的介紹頁或空白章節。

## 4. API 文件

模組摘要描述資料職責；類別描述用途、狀態與生命週期；方法描述操作、參數、回傳與實際可發生的例外。模型描述欄位語意及來源單位。必須分清清單、單筆模型、非同步迭代器及 `BatchResult`，也要說明空結果和逐筆失敗。

`reference/api` 從原始碼產生，請修改 docstring 而非手寫產物：

```sh
cd apps/docs
npm run docs:generate
```

## 5. Docstring

遵守 PEP 257：使用三個雙引號，以摘要句開頭；多行摘要與本文之間空一行。摘要描述操作，不重述函式簽名。建構參數寫在 `__init__`。需要參數段落時使用 Google 風格的 `Args:`、`Returns:`、`Raises:`，不要混用 NumPy 或 Sphinx 標記。型別以程式註記為準，文字補充限制與語意。

雙語公開 docstring 先寫中文，以空行分隔 `English:` 與英文內容；兩個摘要都以句點結束。來源單位、缺值、交易日、契約身分與串流狀態不能只記錄在英文段落。

## 6. 範例

每段可執行範例包含匯入與 client 生命週期；非同步範例包含 `asyncio.run`。串流示範需有結束條件並關閉迭代器。使用字串代號保留前導零，使用明確日期。外部資料的預期結果描述型別或欄位，不捏造固定行情或筆數。使用選用功能前連結安裝方式。

## 7. 用詞

中文使用繁體，英文另頁。識別符保留原名。區分上市、上櫃、興櫃、期貨與選擇權；日期標明是交易日、來源日期、取得時間或報導期間。`None` 表示缺值，不能稱為零；股、張、元、千元及百分數不可混用。直接說明操作與資料，省略宣傳、自我評價及修改歷史。

## 8. 格式與提示

Python、shell 與輸出分別使用 `python`、`sh`、`text` 程式碼區塊。檔名、參數及 API 名稱使用行內程式碼。Note 補充必要條件；Warning 只用於會造成錯誤解讀或損失的具體限制；Tip 用於可選便利操作。一般來源差異直接寫在正文。

## 9. 互聯

站內連結使用 `/docs/...` 或 `/en/docs/...`，不連結 `.mdx`。操作頁連到對應 API 與必要的語意說明；參考頁需要範例時連到操作或教學。移動頁面時更新連結與舊路徑重新導向，維持中英文對應。

## 10. 相容性與棄用

安裝頁以 `pyproject.toml` 的 Python 要求為準。只有實際發布的改動才標示版本或遷移資訊。棄用內容需提供替代介面及已確定的移除版本；沒有確定計畫時不要捏造時程。

## 11. 驗證

產生 API 頁面，執行文件型別檢查與正式建置，確認入口、語言切換、搜尋和站內連結。Python 範例先檢查語法與簽名；涉及網路的範例另確認來源回應，不能將離線驗證說成查詢成功。必要測試針對缺值、單位、契約映射或資料轉換等可觀察契約，不為每段文字新增測試。

```sh
npm run types:check
npm run build
```

## 12. 維護

改動公開 API 時更新 docstring，改動操作時更新相應指南，改動來源語意時更新參考或解釋。中文與英文在同一變更中同步，產生 API 頁面後一併提交。註解專注程式邏輯，不描述版本差異或編寫歷史。


## 開發環境與發布

安裝開發環境、執行檢查與建置：

```sh
git clone https://github.com/cmostw/twmarket.git
cd twmarket
uv sync --all-extras
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pyright
uv run --no-sync pytest -q
uv build
```

## 發布至 PyPI

發布流程使用 GitHub Actions OIDC（PyPI Trusted Publishing），不設定 API token。

PyPI 的 Trusted Publisher 設定：

| 欄位 | 值 |
| --- | --- |
| Owner | `cmostw` |
| Repository | `twmarket` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

首次發布且專案尚未建立時，使用 Pending Publisher，專案名稱填 `twmarket`。GitHub repository environment 名稱同樣使用 `pypi`。

更新 `pyproject.toml` 的版本與 `uv.lock` 後提交，建立對應的 `v<version>` tag 並發布 GitHub Release。`publish.yml` 會驗證 tag 與套件版本一致，通過檢查及測試後建置 wheel／sdist，使用 OIDC 發布。版本 `0.1.0` 對應 tag `v0.1.0`。同一 PyPI 版本不能重複上傳。


## 架構

套件採 modular monolith：單一套件及發行流程，內部按資料來源分組。

| 目錄 | 職責 |
| --- | --- |
| `client.py`、`async_client.py` | 來源入口與連線生命週期 |
| `providers/` | 各來源的請求、解析及查詢流程 |
| `models/` | 資料欄位、型別及來源資訊 |
| `transport/` | HTTP、限速、重試、快取及 SockJS |
| `parsing/` | 日期、數值、JSON 與表格解析 |
| `integrations/` | pandas／Polars 轉換 |

依賴方向為 `Client → providers → transport / parsing / models`，
`integrations → models`。模型使用不可變 dataclass；回傳集合為 `list`。

同步與非同步介面共用解析與請求規格，各自使用 httpx 連線池。
查詢才發出網路請求，建構 client 與匯入套件不連網。
所有請求有逾時；各 host 分別限速。重試限於可安全重送的查詢，並遵守 `Retry-After`。

來源、schema 與網路錯誤使用不同例外。多筆查詢無資料回傳空清單，
單筆查無資料拋出 `NoDataError`。批次查詢保留逐筆成功或錯誤。

各來源 provider 管理資料取得與解析，transport 管理請求及連線。
報價更新與快照的關係見 [報價、快照與串流](/docs/how-to/streaming)。
快取與資料轉換設定見 [API 功能](/docs/reference/data-contracts)。


## TAIFEX MIS 協議

| 端點 | 用途 |
| --- | --- |
| POST `https://mis.taifex.com.tw/futures/api/getQuoteList` | 契約報價列表 |
| POST `https://mis.taifex.com.tw/futures/api/getQuoteDetail` | 指定 SymbolID 的報價與五檔 |
| GET `https://mis.taifex.com.tw/futures/rt/info` | SockJS 連線資訊 |
| `/futures/rt` | SockJS 訂閱 |

列表的一般盤參數為 `MarketType="0"`，夜盤為 `"1"`；
`RowSize="全部"` 取得完整列表。詳情請求為 `{"SymbolID": ["TXFJ6-F"]}`，
範例代碼僅代表測資中的契約；查詢使用當前官方契約 ID。
回應先檢查 `RtCode`，資料位於 `RtData`，列表位於 `RtData.QuoteList`。

訂閱訊息：

```json
{"type": "subscribe", "symbols": ["TXFJ6-F"]}
```

SockJS envelope 解碼後，應用層訊息包含 `quote`、`changeDate`、`changeSource`。
`quote` 帶有 `mode`、`quote.symbol`、`quote.values`；數字欄位 ID 對應 QNameMap。
HTTP 詳情中的 `CDate`／`CTime` 使用台北時區，`CBidPrice1..5`／`CBidSize1..5`
及 `CAskPrice1..5`／`CAskSize1..5` 對應五檔。

完整快照建立狀態；部分更新中缺少的鍵保留原值，明示 `null` 清除欄位。
重連、換日或來源切換時標示舊快照 `stale` 並重新取得完整狀態。
取消或關閉 client 會關閉訂閱。串流提供報價狀態更新，並非逐筆成交紀錄。

來源封包與請求參數保存在 `research/taifex-mis/` 及 `tests/fixtures/`。
