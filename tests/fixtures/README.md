# 測資來源 / Fixture sources

## 繁體中文

測資保留官方回應或其中選取的原始資料列。URL、回應雜湊、大小及取得時間
見 `source-manifest.json`；目錄與規格回應另記於 `research/completion-fixtures.json`。

| 測資 | 來源與參數 |
| --- | --- |
| TWSE／TPEx 日行情 | 官方 JSON |
| 證券 MIS | `getStockInfo.jsp`，`ex_ch=tse_2330.tw`、`json=1`、`delay=0` |
| TAIFEX 歷史 | `futDataDown`／`optDataDown`，2026/10/05，商品 TX／TXO，cp950 CSV |
| 興櫃 | 2026/09/01 歷史資料、GETQ20 XML |
| MOPS 季財報 | `t164sb03`／`t164sb04`／`t164sb05`，2330、民國 115 年第 2 季、dataType=2 |
| MOPS 年財報 | `t164sb04`，2330、民國 114 年第 4 季、dataType=2 |
| MOPS 特別股股利 | `t05st09_2`，2881、民國 114–115 年、queryType=1、dataType=2 |
| TDCC | 原始表頭與 2330／000218 資料列 |
| 國發會 | 完整 PMI CSV 與景氣 ZIP |
| 央行 | 最後五筆原始資料列 |
| TAIFEX MIS | 官方 metadata／detail、選擇權列表資料列及 TXFJ6-F SockJS 快照 |

取得日期為 2026-10-06。測資中的契約、價格與日期代表當次回應。
解析與測試使用原始欄位值，來源編碼及換行保留。

## English

Fixtures contain official responses or selected original rows. source-manifest.json
records URLs, hashes, sizes and capture times; research/completion-fixtures.json
records catalog and specification captures. The table above lists source parameters.
Responses were captured on 2026-10-06; instruments, prices and dates reflect those
responses. Original field values, encodings and line endings are preserved.
