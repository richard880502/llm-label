# Annotation App

**目前版本：v4.0.0**

多人協作的資料標注與複查平台。前端使用 React/Vite，後端使用 FastAPI，
正式資料儲存在獨立 PostgreSQL 服務。

## v4.0.0 更新重點

- Remote MCP 現在支援標準 OAuth 2.1：Codex／ChatGPT GUI App 可從 `/mcp`
  自動發現授權伺服器、以 PKCE 登入平台帳號，無須建立 `apt_` token 或設定環境變數。
- OAuth access token 與網站登入 JWT、既有 PAT 完全分離；access token 一小時後過期，
  `offline_access` 可安全輪替 refresh token，使用者可在 LLM 設定中直接撤銷 GUI 連線。
- 新增分級 scope：專案／資料列／任務讀取與執行、資料列修改、單筆核准、批次核准。
  預設連線只有讀取與分類任務權限；兩種核准權限均須在同意頁明確勾選。
- GUI 連線可選擇限制至特定 project IDs；未授權 project 的工具呼叫會被拒絕。
- LLM 設定將 GUI App 設為主要 MCP onboarding；`apt_` token 與 Codex／Claude CLI 指令保留於
  **CLI／Developer** fallback。完整管理者流程見 [Custom MCP App 文件](docs/codex-custom-mcp-app.md)。

## v3.0.2 更新重點

- 新增「專案 Codebook」：每個專案可在 LLM 設定中維護自己的分類規則（上限 12,000 字），
  未自訂時會顯示、並實際套用平台內建的完整預設規則，不再是空白或看不到目前生效內容。
  規則會同時套用到內建 LLM 任務、MCP Agent 批次分類，以及人工複查的手動修正。
- Emotional Resonance 與其情緒子類型的階層規則，現在在 LLM 產出、MCP 批次送出與人工修正
  三個路徑都會一致驗證：沒有 Emotional Resonance 就不能有子類型。
- 情感子類型新增「未確定」選項：確定為 Emotional Resonance、但無法判斷屬於哪一個具體子類型時使用。
  已寫入預設 LLM prompt／專案 Codebook 規則，AI 分類與人工複查都可以選用；
  另補上先前已上線但未寫入文件的「Grateful and Heartfelt」子類型。
- 修正情感子類型標籤只顯示第一個英文字（如 `Satisfied`）的問題，處理頁與 LLM 比對結果
  現在都會顯示完整子類型名稱。
- 修正 PostgreSQL connection pool 洩漏與背景 LLM 任務長時間佔用連線：所有路由改用 context
  manager，LLM 等待期間會釋放連線；預設 pool 提升為 4–40 條，並可用
  `DB_POOL_MIN_SIZE`、`DB_POOL_MAX_SIZE`、`DB_POOL_TIMEOUT_SECONDS` 調整，避免多人網頁、MCP
  與背景分類同時使用時導致 `/api/projects` 等 API 變慢或耗盡。
- MCP server 固定在 `mcp>=1.2.0,<2.0.0`，並限制相容的 `sse-starlette`，避免升級到會移除
  `FastMCP` 匯入路徑的 2.x 版本或在映像建置時發生 Starlette 相依衝突。

## v3.0.1 更新重點

- 總表分頁與相鄰筆數導覽改為依篩選條件快取總筆數，切換分頁或前後筆時不重複執行
  完整的 `COUNT(*)` 查詢，降低大型專案的資料庫負擔。

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
- MCP：App 映像在 `/mcp` 提供遠端 MCP。公網部署時，此 endpoint 以 OAuth 2.1 保護；
  GUI App 會自動發現授權設定，CLI 可繼續使用 PAT。
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
- 正式網域必須使用公開 HTTPS；OAuth metadata 位於
  `/.well-known/oauth-protected-resource/mcp` 與 `/.well-known/oauth-authorization-server`。
- PostgreSQL 必須掛載持久化磁碟並設定定期備份。
- 不要將 PostgreSQL port 直接開放到公網。
- `SECRET_KEY`、管理員密碼與 API 金鑰必須使用平台的非公開環境變數。
- SQLite 檔只保留作為舊資料備份，不再作為執行中的正式資料庫。

## 版本歷程

- `v4.0.0`：Remote MCP 改用 OAuth 2.1 GUI onboarding，提供可撤銷、有期限的連線 token、
  scope／project 限制與 ChatGPT Custom MCP App 管理文件；PAT／CLI 模式改為進階 fallback。
- `v3.0.2`：新增專案 Codebook、情感子類型「未確定」、完整子類型顯示，並修復 DB connection pool 洩漏。
- `v3.0.1`：優化總表分頁與相鄰筆數導覽的計數查詢。
- `v3.0.0`：新增未確定狀態、前端查詢管理與 PostgreSQL 效能優化。
- `v2.0.0-postgresql`：正式資料庫由 SQLite 遷移至 PostgreSQL。
- `v1.0.0-sqlite`：最後一個使用 SQLite 的版本。
