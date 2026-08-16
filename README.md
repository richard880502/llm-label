# Annotation App

**目前版本：v3.1.0**

多人協作的資料標注與複查平台。前端使用 React/Vite，後端使用 FastAPI，
正式資料儲存在獨立 PostgreSQL 服務。

## v3.1.0 更新重點

- 新增「專案 Codebook」：每個專案可在 LLM 設定中維護自己的分類規則（上限 12,000 字），
  未自訂時會顯示、並實際套用平台內建的完整預設規則，不再是空白或看不到目前生效內容。
  規則會同時套用到內建 LLM 任務、MCP Agent 批次分類，以及人工複查的手動修正。
- Emotional Resonance 與其情緒子類型的階層規則，現在在 LLM 產出、MCP 批次送出與人工修正
  三個路徑都會一致驗證：沒有 Emotional Resonance 就不能有子類型。
- 情感子類型新增「未確定」選項，供複查者標記「確定有情緒反應、但無法判斷具體子類型」；
  另補上先前已上線但未寫入文件的「Grateful and Heartfelt」子類型。
- 修正情感子類型標籤只顯示第一個英文字（如 `Satisfied`）的問題，處理頁與 LLM 比對結果
  現在都會顯示完整子類型名稱。
- 修正 PostgreSQL connection pool 洩漏：所有路由改用 context manager 存取資料庫連線，
  例外發生時保證連線會歸還 pool；新增 pool/session 逾時設定與逾時時的 503 錯誤處理，
  避免連線耗盡導致 `/api/projects` 等 API 整個失敗。
- MCP server 依賴改為 `mcp>=1.2.0,<2.0.0`，避免升級到會移除 `FastMCP` 匯入路徑的 2.x 版本。

## v3.0.0 更新重點

- 新增「未確定」審查狀態，可在處理頁標記、總表篩選及專案統計中查看。
- 新增 `U` 快捷鍵；標記未確定後會前往下一筆，並提供 5 秒撤銷操作。
- 未確定資料不會被選為已確認的 LLM few-shot 範例。
- 前端導入 TanStack Query，集中管理專案、列表、任務及標注資料的查詢快取。
- API 請求停用瀏覽器 HTTP cache，資料異動後會使相關列表與統計失效。
- PostgreSQL 改用 connection pool，並補強狀態、搜尋、排序及關聯查詢索引。
- 優化相鄰筆數導覽、批次更新與 LLM 任務查詢，降低大型專案的記憶體與資料庫負擔。
- 保留 optimistic locking，多人同時編輯同一筆資料時會提示版本衝突。

## 主要功能

- CSV／XLSX 專案匯入與 XLSX 結果匯出。
- 待審、已核准、已修正、未確定四種審查狀態。
- 依狀態、相關性、LLM 歧異及關鍵字篩選。
- 多組 LLM 結果比對、批次分類與 MCP Agent 執行模式。
- 專案層級 Codebook：自訂並檢視目前生效的分類規則，套用到所有分類路徑。
- 多人在線狀態、審查歷史、版本衝突偵測與使用者權限管理。
- PostgreSQL 持久化、Adminer 管理介面及 Docker Compose 部署。

## 處理頁快捷鍵

| 快捷鍵 | 功能 |
| --- | --- |
| `←`／`[` | 上一筆 |
| `→`／`]` | 下一筆 |
| `A` | 核准 |
| `S` | 儲存修正 |
| `U` | 標記為未確定 |

## 本地架構

- App：`http://localhost:8080`
- PostgreSQL：`localhost:5433`
- Adminer：`http://localhost:8081`
- MCP：App 映像在 `/mcp` 提供遠端 MCP；完整 Compose stack 也可使用獨立 MCP 服務
- Caddy：只在需要本地 HTTPS／反向代理時啟動

PostgreSQL 資料保存在 Docker named volume `annotation-app_annotation_db`，
不會因 App 容器重建而消失。

## 初次設定

```bash
cp .env.example .env
docker compose up -d db
docker compose build app
```

請先修改 `.env` 的 `POSTGRES_PASSWORD`、`SECRET_KEY` 與管理員密碼。
`.env` 已被 Git 忽略，不應提交任何正式金鑰。

## 從舊 SQLite 搬移

遷移前先停止舊 App，確認 `data/annotation.db`、`annotation.db-wal` 與
`annotation.db-shm` 都位於 `data/`。

```bash
docker compose run --rm --no-deps app \
  python scripts/migrate_sqlite_to_postgres.py
```

遷移工具會：

1. 將 SQLite 主檔及 WAL 輔助檔複製到容器暫存區。
2. 建立 PostgreSQL schema。
3. 依外鍵順序匯入所有資料表。
4. 重設 identity sequence。
5. 比較 SQLite 與 PostgreSQL 的逐表筆數。

來源 SQLite 不會被修改。PostgreSQL 已有資料時，工具預設會停止，避免意外合併。

## 啟動

只啟動日常開發所需服務：

```bash
docker compose up -d app adminer
```

啟動完整服務：

```bash
docker compose up -d
```

查看狀態與紀錄：

```bash
docker compose ps
docker compose logs -f app
```

## 備份與還原

備份 PostgreSQL：

```bash
docker compose exec -T db \
  pg_dump -U annotation -d annotation -Fc > annotation.backup
```

還原前請確認目標資料庫可被覆蓋：

```bash
docker compose exec -T db \
  pg_restore -U annotation -d annotation --clean --if-exists < annotation.backup
```

## 部署注意事項

- App 與 PostgreSQL 應部署成兩個獨立服務。
- App 只透過私有 `DATABASE_URL` 連接 PostgreSQL。
- Zeabur 的 App 映像會在同一個公開網域提供網站與 `/mcp`，資料庫仍維持獨立服務。
- PostgreSQL 必須掛載持久化磁碟並設定定期備份。
- 不要將 PostgreSQL port 直接開放到公網。
- `SECRET_KEY`、管理員密碼與 API 金鑰必須使用平台的非公開環境變數。
- SQLite 檔只保留作為舊資料備份，不再作為執行中的正式資料庫。

## 版本歷程

- `v3.1.0`：新增專案 Codebook、情感子類型「未確定」、完整子類型顯示，並修復 DB connection pool 洩漏。
- `v3.0.0`：新增未確定狀態、前端查詢管理與 PostgreSQL 效能優化。
- `v2.0.0-postgresql`：正式資料庫由 SQLite 遷移至 PostgreSQL。
- `v1.0.0-sqlite`：最後一個使用 SQLite 的版本。
