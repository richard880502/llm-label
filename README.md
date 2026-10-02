# Annotation App

**目前版本：v5.3.0**

多人協作的通用資料標注、AI 自動分類與人工複查平台。前端使用 React/Vite，後端使用 FastAPI，正式資料儲存在 PostgreSQL。

v5 系列不再綁定固定的分類欄位或特定標籤集合，而是改成以 **Input Mapping + Annotation Schema + Codebook + Shared Prompt** 描述每個專案的資料與分類規則。

## v5.3.0 更新重點

- 桌面 Review 改為共用外框的雙欄工作台：左側閱讀原文與分類標注，右側集中 AI 理由、模型比對、備註及審查歷史。
- 標籤橫向排列並自動換行；審查操作保持可見，小螢幕維持上下排列。
- Review 的任務助手與任務紀錄收進上方工具列；統一浮動視窗大小與入口尺寸，助手採用低飽和玻璃樣式。
- 分頁檢查點依狀態範圍失效：僅修改標籤或備註不再清除檢查點，狀態切換只影響相關狀態的分頁。

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
