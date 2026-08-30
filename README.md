# Annotation App

**目前版本：v5.0.2**

多人協作的通用資料標注、AI 自動分類與人工複查平台。前端使用 React/Vite，後端使用 FastAPI，正式資料儲存在 PostgreSQL。

v5 系列不再綁定固定的分類欄位或特定標籤集合，而是改成以 **Input Mapping + Annotation Schema + Codebook + Shared Prompt** 描述每個專案的資料與分類規則。

## v5.0.2 更新重點

### Durable API Background Tasks

平台模型 API 任務改成以 PostgreSQL `task_items` 保存逐列 checkpoint，不再只依賴 FastAPI process 內的背景執行狀態。

因此 API 分類任務現在具備：

- 關閉自動分類視窗或直接關掉瀏覽器後，後端任務仍會繼續執行。
- FastAPI / App container restart 後，啟動流程會自動掃描 `pending` / `running` API tasks 並恢復尚未完成的項目。
- 每 30 秒 watchdog 重新掃描可恢復任務，避免 transient error 後任務永久卡住。
- 每個 row 在呼叫 LLM 前先取得 lease；process 中斷後，過期 lease 會重新回到 `pending`。
- 已完成的 `task_items` 不會再次送到 LLM，避免 restart 後重複消耗 token。
- Task cancellation 與進度以 PostgreSQL 狀態為主要依據，不再只依賴瀏覽器連線。

對於升級前已經卡住、尚未建立 `task_items` 的舊 API task，v5.0.2 第一次 recovery 時會建立 snapshot，並以 task 建立後已寫入的 `row_llm_results` 回填完成 checkpoint，盡量從原本進度附近繼續執行，而不是重新從第 1 筆開始。

目前 durable queue 直接使用既有 PostgreSQL，不需要額外部署 Redis / Celery。

### 真實 100 並發與 HTTP Connection Pool

進階分類設定原本已允許 `Concurrency=1–100`，但舊版 blocking HTTP 呼叫仍可能受到 Python 預設 executor thread 數限制，因此設定 100 不代表一定真的同時送出 100 個 request。

v5.0.2 將整條 LLM request path 對齊到 100 並發：

```text
Single task concurrency          <= 100
Dedicated LLM executor workers  = 100
Global LLM in-flight limit      = 100
HTTP max connections            = 128
HTTP keep-alive connections     = 100
```

- 使用專用 `ThreadPoolExecutor` 執行 blocking LLM HTTP requests，不再受 asyncio 預設 executor 約數十條 thread 的隱性限制。
- `httpx.Client` 在整個 process 共用 connection pool / keep-alive，不再每筆資料重新建立 TCP/TLS connection。
- 多個 API tasks 可以同時 active，但共用全站 LLM in-flight 上限，避免兩張 concurrency=100 的 task 突然同時灌出 200 個 requests。
- 對 HTTP `408`、`429`、`5xx`、connection error 與 timeout 提供 retry + exponential backoff。
- PostgreSQL connection 不會在等待 LLM response 時被長時間占用，因此 DB pool 可以與 HTTP concurrency 分開配置。

### v5.0.2 執行參數

以下參數可透過環境變數調整；`.env.example` 已提供預設值：

| 變數 | 預設 | 說明 |
| --- | ---: | --- |
| `API_TASK_WORKERS` | `2` | 同一個 App process 最多同時執行幾張 API task |
| `API_TASK_WATCHDOG_SECONDS` | `30` | 掃描可恢復 API task 的間隔 |
| `LLM_EXECUTOR_WORKERS` | `100` | blocking LLM HTTP executor thread 數 |
| `LLM_MAX_CONCURRENT_REQUESTS` | `100` | 全站最大 LLM in-flight requests |
| `LLM_HTTP_MAX_CONNECTIONS` | `128` | HTTP pool 最大連線數 |
| `LLM_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `100` | HTTP keep-alive 連線數 |
| `LLM_HTTP_KEEPALIVE_EXPIRY_SECONDS` | `30` | keep-alive connection expiry |
| `LLM_MAX_RETRIES` | `3` | transient LLM HTTP error 最大重試次數 |

如果上游 vLLM / Triton / OpenAI-compatible endpoint 已確認可以承受更高流量，可以再提高全站 LLM request / executor / HTTP pool 上限；單一 task 的前台設定目前仍限制在 100。

## v5.0.1 更新重點

### Shared Prompt 與 Codebook 穩定化

- Prompt 改為 **project-scoped Shared Prompt**，同一專案的所有 LLM slots 與 MCP Agent 共用同一份 Prompt。
- Codebook 維持專案層級的分類規則來源，不需要替不同模型維護不同版本。
- 舊版 slot-level `prompt_template` 保留相容欄位，但會同步為目前生效的 Shared Prompt。
- 舊專案既有自訂 Prompt 會在 migration 時轉入新的 project-level Shared Prompt。

推薦的責任分工：

```text
Shared Prompt       怎麼執行標注任務
Codebook            怎麼判斷分類規則
Annotation Schema   哪些輸出值合法、階層與 constraints
Few-shot            人工複查後的正確範例
Output Contract      模型必須回傳的結構
```

實際分類時，平台會組合：

```text
Shared Prompt
  + Codebook
  + Annotation Schema
  + Few-shot examples
  + current row text
  + output contract
        ↓
Platform LLM API / MCP Agent
```

### Task-level Prompt Fingerprint

為避免長任務執行到一半分類規則被修改，task 建立時會記錄 SHA-256 prompt fingerprint。

Fingerprint 會涵蓋：

- Shared Prompt
- Codebook
- Annotation Schema
- Few-shot examples
- Output contract

實際 row text 不納入 fingerprint，因此它只代表「規則狀態」，不是 prediction history。

若 task 建立後上述規則發生變更：

- Platform API task 會停止並要求建立新任務。
- MCP batch 會回傳 `PROMPT_RULES_CHANGED`，避免 Agent 使用新舊規則混跑同一個 task。

Prediction 儲存邏輯仍維持原本的 overwrite semantics；v5.0.1 **沒有新增 prediction history**。

### 分類並發設定

- 進階分類設定中的 `Concurrency` 可設定 **1–100**。
- 此數值代表單一分類 task 的應用層並發上限。
- v5.0.1 仍可能受到 Python executor、HTTP client 與模型服務本身排程限制；此限制在 v5.0.2 已進一步修正。

### API / MCP 規則一致性

Platform LLM API 與 MCP Agent 現在共用相同的：

- Shared Prompt
- Codebook
- Annotation Schema
- Prompt fingerprint policy

因此切換執行方式時，不需要再手動複製 Prompt 或分類規則。

## v5.0.0 更新重點

### 通用資料匯入與欄位 Mapping

- 支援 CSV、XLSX、XLS、JSON、JSONL。
- 匯入時先預覽資料，再指定欄位用途，不要求來源檔案使用固定欄名。
- 每個專案指定一個主要 `Text` 欄位，另外可選：
  - `ID`：保留來源資料的唯一識別值。
  - `Source Label`：保留來源原始標籤。
  - `Context`：提供給 AI 分類時一起參考的額外欄位。
  - `Metadata`：只保存於平台，預設不送給模型。
- 每一列完整來源資料會原樣保存在 `original_data`，匯入流程不會破壞來源欄位。

### 動態 Annotation Schema

- 支援 `single_label` 與 `multi_label` 分類。
- Label 可以自訂名稱、ID、描述與 parent-child 關係。
- 支援最大標籤數、父子標籤約束與 relevance 規則。
- AI prediction、MCP Agent 結果與人工最終修正都走同一套 schema validation。
- Generic canonical result 使用 JSON 結構儲存，不再依賴固定的 legacy label 欄位。

### 自動分類工作流重新設計

自動分類主畫面只保留高頻操作：

1. 確認／修改 Codebook。
2. 選擇執行方式：平台模型 API 或 MCP Agent。
3. 選擇模型／Agent 與資料範圍。
4. 開始分類。

低頻設定集中到「進階分類設定」，包括：

- LLM API URL / API Key / Model。
- Concurrency。
- Prompt template。
- Few-shot 策略與每個 Label 的範例數。
- Provider 額外 request body。
- Prompt Preview。
- Codex / ChatGPT / Claude Code MCP 連線與 access token。
- 完整任務紀錄。

### Codebook 專用編輯體驗

- 自動分類主畫面只顯示 Codebook 摘要，減少資訊密度。
- 點擊 Codebook 卡片會開啟大型專用編輯器。
- 平台 API 與 MCP Agent 共用同一份 Codebook，不需要分開維護。
- 若 Codebook 有尚未儲存的修改，開始分類前會先自動儲存最新版。

### 常駐任務中心

- Project 頁右下角提供浮動任務中心。
- 即使關閉自動分類視窗，背景任務仍可持續查看。
- 折疊狀態會顯示執行中數量或單一任務進度。
- 執行中／等待中的任務可「停止」。
- 完成、失敗或已停止的任務可「刪除」。
- 進階設定另外保留最近 50 筆完整任務紀錄。

### LLM 回傳解析穩定性

- 對 LLM 常見的 `{{...}}` 額外外層大括號提供相容解析。
- 修正 Markdown 造成 JSON key 出現 `\_` 的無效 escape 問題。
- Legacy `emotional_subtypes` 仍可相容轉換至 generic labels，方便既有資料與模型逐步升級。

## v4.0.0 更新重點

- Remote MCP 支援標準 OAuth 2.1：Codex／ChatGPT GUI App 可從 `/mcp` 自動發現授權伺服器、以 PKCE 登入平台帳號，無須建立 `apt_` token 或設定環境變數。
- OAuth access token 與網站登入 JWT、既有 PAT 分離；`offline_access` 可輪替 refresh token，使用者可以撤銷 GUI 連線。
- 新增分級 scope：專案／資料列／任務讀取與執行、資料列修改、單筆核准、批次核准。
- GUI 連線可限制至特定 project IDs。
- PAT 與 Codex／Claude CLI 指令保留作為 CLI／Developer fallback。完整流程見 [Custom MCP App 文件](docs/codex-custom-mcp-app.md)。

## 主要功能

### Project / Dataset

- CSV／XLSX／XLS／JSON／JSONL 匯入。
- 自動資料預覽與欄位 Mapping。
- 保留完整 `original_data`。
- Text / ID / Source Label / Context / Metadata 分工。
- XLSX 結果匯出。

### Annotation

- 動態 Label Schema。
- Single-label / Multi-label。
- Parent-child hierarchy。
- Relevance 規則。
- 待審、已核准、已修正、未確定四種人工審查狀態。
- 依狀態、相關性、模型歧異及關鍵字篩選。
- 多人在線狀態、審查歷史與 optimistic locking。

### AI 自動分類

平台支援兩種分類執行方式：

```text
自動分類
├─ 平台模型 API
│  └─ 由後端 durable background runtime 呼叫已設定的 OpenAI-compatible API
│
└─ MCP Agent
   ├─ Codex / ChatGPT
   └─ Claude Code
```

平台 API 與 MCP Agent 會使用同一份：

- Shared Prompt
- Annotation Schema
- Codebook
- Context fields
- Few-shot examples（依模型設定）

每個模型／Agent 的結果會分開保存，人工審查後再寫入最終 corrected result。

### MCP / OAuth

- Remote MCP endpoint：`/mcp`
- OAuth 2.1 + PKCE GUI onboarding。
- 可撤銷 OAuth connections。
- Project scope / permission scope。
- CLI / Developer PAT fallback。
- MCP Agent 可 claim classification task、取得批次資料並持續提交結果。

## 資料流程

```text
Import
  ↓
Project + Input Mapping + Annotation Schema
  ↓
Rows
├─ original_data      完整來源資料
├─ text               主要分類文字
├─ metadata           非模型預設輸入資訊
├─ prediction         AI canonical result
└─ corrected_result   人工最終結果

          ┌─ Platform LLM API
Rows ─────┤
          └─ MCP Agent
                ↓
         row_llm_results
                ↓
          Human Review
                ↓
         corrected_result
                ↓
              Export
```

## Codebook 與 Few-shot

Codebook 用來描述此專案的分類判斷方式，例如：

- 每個 Label 什麼情況應該選。
- 容易混淆的 Label 如何區分。
- 多個條件同時出現時的優先順序。
- 邊界案例與例外情況。

Few-shot 則來自人工已審查資料，可依模型設定選擇：

- 只使用人工修正案例。
- 使用全部已審查案例。

Codebook 與 Few-shot 都屬於分類品質設定，但只有 Codebook 是日常高頻修改項目，因此 v5.0.0 將兩者分開呈現。

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
- MCP：公開 endpoint 為 `/mcp`，GUI App 使用 OAuth 2.1，CLI 可使用 PAT。
- Caddy：本地 HTTPS／反向代理需要時啟動。

PostgreSQL 資料保存在 Docker named volume `annotation-app_annotation_db`，不會因 App 容器重建而消失。API task checkpoint 同樣保存在 PostgreSQL，因此 App restart 後可以恢復尚未完成的分類工作。

## 初次設定

```bash
cp .env.example .env
docker compose up -d db
docker compose build app
```

請先修改 `.env` 的 `POSTGRES_PASSWORD`、`SECRET_KEY` 與管理員密碼。
`.env` 已被 Git 忽略，不應提交正式金鑰。

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

## 從舊 SQLite 搬移

遷移前先停止舊 App，確認 `data/annotation.db`、`annotation.db-wal` 與 `annotation.db-shm` 都位於 `data/`。

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

## 備份與還原

備份 PostgreSQL：

```bash
docker compose exec -T db \
  pg_dump -U annotation -d annotation -Fc > annotation.backup
```

還原：

```bash
docker compose exec -T db \
  pg_restore -U annotation -d annotation --clean --if-exists < annotation.backup
```

## 部署注意事項

- App 與 PostgreSQL 應使用獨立服務／持久化儲存。
- App 只透過私有 `DATABASE_URL` 連接 PostgreSQL。
- 正式網域必須使用 HTTPS。
- OAuth metadata 位於 `/.well-known/oauth-protected-resource/mcp` 與 `/.well-known/oauth-authorization-server`。
- PostgreSQL 必須掛載持久化磁碟並設定定期備份；API task checkpoint 也依賴這份資料庫持久性。
- `LLM_MAX_CONCURRENT_REQUESTS` 應依上游 LLM server / provider 能承受的吞吐量設定，避免單純提高前台 concurrency 導致 429 或排隊時間暴增。
- 不要將 PostgreSQL port 直接開放到公網。
- `SECRET_KEY`、管理員密碼、LLM API Key 與其他 token 必須使用非公開環境變數。
- SQLite 只保留作為歷史備份，不再是正式資料庫。

## 版本歷程

- `v5.0.2`：API 分類任務改為 PostgreSQL durable checkpoints，支援瀏覽器關閉後持續執行、App/container restart 自動恢復、watchdog/lease recovery；LLM HTTP path 改為真正可達 100 並發的專用 executor、共享 connection pool、全域 in-flight guard 與 transient error retry/backoff。
- `v5.0.1`：Shared Prompt / Codebook 規則穩定化、API / MCP 共用 prompt policy、task-level prompt fingerprint，以及分類 Concurrency 上限提高至 100。
- `v5.0.0`：通用資料匯入與 Mapping、動態 Annotation Schema、generic canonical result、重新設計的自動分類 UI、專用 Codebook 編輯器、API / MCP 雙執行路徑、常駐任務中心與進階分類設定整理。
- `v4.0.0`：Remote MCP 改用 OAuth 2.1 GUI onboarding，提供可撤銷、有期限的連線 token、scope／project 限制與 ChatGPT Custom MCP App 管理文件；PAT／CLI 模式改為進階 fallback。
- `v3.0.2`：新增專案 Codebook、情感子類型「未確定」、完整子類型顯示，並修復 DB connection pool 洩漏。
- `v3.0.1`：優化總表分頁與相鄰筆數導覽的計數查詢。
- `v3.0.0`：新增未確定狀態、前端查詢管理與 PostgreSQL 效能優化。
- `v2.0.0-postgresql`：正式資料庫由 SQLite 遷移至 PostgreSQL。
- `v1.0.0-sqlite`：最後一個使用 SQLite 的版本。
