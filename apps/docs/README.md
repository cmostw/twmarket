# twmarket 文件站 / Documentation site

## 繁體中文

```sh
npm ci
npm run dev
npm run types:check
npm run build
```

開啟 http://localhost:3000/docs 。文件位於 `content/docs`，靜態輸出位於 `out`。

Cloudflare Pages 設定：

| 欄位 | 值 |
| --- | --- |
| 框架預設 | 無 / None |
| 根目錄 | `apps/docs` |
| 組建命令 | `npm run build` |
| 組建輸出目錄 | `out` |
| 環境變數 | `NODE_VERSION=24` |

## English

Run the commands above from this directory. Open http://localhost:3000/docs .
Content lives in `content/docs`; the static build is in `out`.

For Cloudflare Pages, select framework None, root `apps/docs`, build command
`npm run build`, output `out`, and environment variable `NODE_VERSION=24`.
