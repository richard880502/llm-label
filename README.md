# Annotation App

**目前版本：v5.0.1**

多人協作的通用資料標注、AI 自動分類與人工複查平台。前端使用 React/Vite，後端使用 FastAPI，正式資料儲存在 PostgreSQL。

v5 系列不再綁定固定的分類欄位或特定標籤集合，而是改成以 **Input Mapping + Annotation Schema + Codebook + Shared Prompt** 描述每個專案的資料與分類規則。

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
- 目前平台以 `asyncio.Semaphore` 控制 task 內同時處理的 rows；實際 HTTP 並發仍可能受到 Python executor、HTTP client 與模型服務本身排程限制。

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
│  └─ 由後端背景 worker 呼叫已設定的 OpenAI-compatible API
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

PostgreSQL 資料保存在 Docker named volume `annotation-app_annotation_db`，不會因 App 容器重建而消失。

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
- PostgreSQL 必須掛載持久化磁碟並設定定期備份。
- 不要將 PostgreSQL port 直接開放到公網。
- `SECRET_KEY`、管理員密碼、LLM API Key 與其他 token 必須使用非公開環境變數。
- SQLite 只保留作為歷史備份，不再是正式資料庫。

## 版本歷程

- `v5.0.1`：Shared Prompt / Codebook 規則穩定化、API / MCP 共用 prompt policy、task-level prompt fingerprint，以及分類 Concurrency 上限提高至 100。
- `v5.0.0`：通用資料匯入與 Mapping、動態 Annotation Schema、generic canonical result、重新設計的自動分類 UI、專用 Codebook 編輯器、API / MCP 雙執行路徑、常駐任務中心與進階分類設定整理。
- `v4.0.0`：Remote MCP 改用 OAuth 2.1 GUI onboarding，提供可撤銷、有期限的連線 token、scope／project 限制與 ChatGPT Custom MCP App 管理文件；PAT／CLI 模式改為進階 fallback。
- `v3.0.2`：新增專案 Codebook、情感子類型「未確定」、完整子類型顯示，並修復 DB connection pool 洩漏。
- `v3.0.1`：優化總表分頁與相鄰筆數導覽的計數查詢。
- `v3.0.0`：新增未確定狀態、前端查詢管理與 PostgreSQL 效能優化。
- `v2.0.0-postgresql`：正式資料庫由 SQLite 遷移至 PostgreSQL。
- `v1.0.0-sqlite`：最後一個使用 SQLite 的版本。
