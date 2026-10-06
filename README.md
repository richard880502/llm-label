# Annotation App

**目前版本：v5.4.0**

多人協作的通用資料標注、AI 自動分類與人工複查平台。前端使用 React/Vite，後端使用 FastAPI，正式資料儲存在 PostgreSQL。

v5 系列不再綁定固定的分類欄位或特定標籤集合，而是改成以 **Input Mapping + Annotation Schema + Codebook + Shared Prompt** 描述每個專案的資料與分類規則。

## v5.4.0 更新重點

- 新增「標注傾向」頁：直接用既有審查紀錄呈現審查者與 AI 的標注傾向，不需額外標注。
- 專案頁標題列改版：專案分頁與審查進度摘要、動作按鈕分主次，帳號功能收進頭像選單。
- 修正頭像選單開啟時整頁變白的問題；「新增專案」「新增使用者」移到帳號選單之前。

完整更新紀錄見 [CHANGELOG.md](CHANGELOG.md)。

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

### 標注傾向

專案頁的「標注傾向」分頁，只用現有的審查紀錄計算：

- **重點發現**：以白話列出需要注意的現象，例如核准率過高、結果由 AI 模型寫入的比例、AI 常漏標或多標的標籤。
- **誰審了哪些資料**：依列號分段，顯示每位審查者實際審過的比例與待審範圍。
- **審查者**：直接核准／修正／未確定比例（含 95% 信賴區間），並區分結果是人工編輯、AI 模型寫入，或沿用 AI 預測。
- **AI 與審查結果的差異**：各標籤的 AI 選用率與最終選用率，以及審查時被補上或移除的次數。

使用的統計方法：Wilson 信賴區間、卡方檢定與 φ 效果量（審查者兩兩比較）、McNemar 精確檢定（標籤補上／移除是否不對稱）、Holm 多重比較校正。頁面內有可展開的說明。

注意：各審查者處理不同區段的資料時，差異可能來自資料本身而不是審查習慣，頁面會標示共同審過的區段比例。要確認審查者之間是否一致，需要讓多人獨立標注同一批資料。

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
