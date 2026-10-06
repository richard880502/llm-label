# 更新紀錄

## v5.4.0 更新重點

- 新增「標注傾向」頁：直接用既有審查紀錄呈現審查者與 AI 的標注傾向，不需額外標注。
- 專案頁標題列改版：專案分頁與審查進度摘要、動作按鈕分主次，帳號功能收進頭像選單。
- 修正頭像選單開啟時整頁變白的問題；「新增專案」「新增使用者」移到帳號選單之前。

### 標注傾向（PR #77）

- 新增 `GET /api/projects/{id}/tendency`，後端計算並回傳審查者統計、列號覆蓋率與各標籤的 AI／最終選用率。
- 審查者核准率附 Wilson 95% 信賴區間；審查者兩兩比較使用卡方檢定與 φ 效果量。
- 各標籤以 McNemar 精確檢定判斷「補上」與「移除」是否不對稱，並以 Holm 法校正多重比較。
- 依實際審過的列分段計算覆蓋率，共同覆蓋的區段不足時標示差異可能來自資料而非審查者。
- 辨識 `corrected_result.metadata` 中的 AI 模型來源，區分人工編輯與 AI 模型寫入。
- 頁面最上方以白話列出重點發現，並提供可展開的統計方法說明與限制。

### 標題列與帳號選單（PR #78）

- 新增共用 `ProjectNav`：資料列表／標注傾向分頁、已審進度（滑過顯示核准、修正、未確定、待審）。
- 「自動分類」為主要按鈕、「一鍵套用」為次要按鈕，「匯出」收進 `⋯` 選單。
- 頭像改為下拉選單，包含使用者管理與登出；選單標題需包在 `DropdownMenuGroup` 內。
- 第二個篩選下拉由「所有狀態」改名為「不限歧異」。

### 升級說明

不需資料庫遷移，沿用既有 PostgreSQL；新功能只讀取既有資料。

## v5.3.0 更新重點

- 桌面 Review 改為共用外框的雙欄工作台：左側閱讀原文與分類標注，右側集中 AI 理由、模型比對、備註及審查歷史。
- 標籤橫向排列並自動換行；審查操作保持可見，小螢幕維持上下排列。
- Review 的任務助手與任務紀錄收進上方工具列；統一浮動視窗大小與入口尺寸，助手採用低飽和玻璃樣式。
- 分頁檢查點依狀態範圍失效：僅修改標籤或備註不再清除檢查點，狀態切換只影響相關狀態的分頁。

### 分頁檢查點與多人審查（PR #67）

- 使用獨立狀態 generation，避免一位審查者的修改讓整個專案的檢查點一起失效。
- 狀態由 pending 切到 approved 時，只更新這兩種狀態的 generation；未篩選狀態的列表與其他狀態仍可重用檢查點。
- 儲存新檢查點時只清理相同篩選條件的舊 generation，保留其他篩選的有效檢查點。
- 批次審查及採用模型結果也使用相同的失效邏輯；新增 PostgreSQL 欄位由啟動遷移自動建立。

### Review 工作台與專案工具（PR #68）

- 兩欄共用外框與底部對齊，中間使用分隔線；桌面兩側可獨立捲動，右側底部保留核准、儲存修正及未確定操作。
- 保留原本漸層配色，移除內部重複圓角，閱讀區以縮排淡分隔線區分；上下文及主要文字標題更清楚，減少頂部留白。
- 子標籤保留群組層次；模型比對支援較窄欄位的換行。
- 修正登入後直接載入 Review 時，助手無法掛載到上方工具列的問題。
- 內容字體維持原始尺寸，登入頁樣式未變更。

## v5.2.1 更新重點

- 相鄰資料頁預取與 keyset pagination，減少連續翻頁等待。
- 每 20 頁保存稀疏檢查點，改善深頁跳轉；人工審查變更會在同一交易更新 generation，避免沿用過期檢查點。
- 不適用 cursor 的篩選維持 OFFSET 相容路徑；PostgreSQL 仍為資料來源，未加入 Redis。
- 改善深色模式的藍灰漸層、玻璃卡片與文字對比。

## v5.2.0 更新重點

### OpenClaw 專案任務助手

每個專案現在都有可保留對話紀錄的浮動任務助手。它讀取網站提供的專案進度、最近任務、目前資料列與可用 LLM slots，協助使用者規劃及推進分類工作。

- 回覆支援 Markdown、清單、表格、程式碼與連結；同一時間可傳送多則訊息，不必等待前一則回覆。
- 對話以 `project_id + username` 隔離；不同帳號或不同專案不會共用 OpenClaw response chain，也可由使用者清除自己的專案對話重新開始。
- 助手只能提出受驗證的 `create_task` 與 `cancel_task` 操作。有效操作會由 llm-label 後端自動執行，並把執行結果或錯誤寫回對話紀錄。
- 建立分類任務時，真正執行的是網站已設定的 Platform LLM API、Shared Prompt、Codebook、Annotation Schema 與 few-shot；OpenClaw 不會直接使用 GPU、檔案系統或 MCP 工具替平台分類。
- OpenClaw 必須使用專用的 `llm-label-assistant` agent。平台會拒絕指向通用 `main` agent 的設定，並在每次請求注入工具邊界，避免 agent 把自身容器或 workspace 誤認為平台資源。

啟用方式：在 llm-label 設定 `OPENCLAW_BASE_URL`、`OPENCLAW_API_TOKEN` 與 `OPENCLAW_AGENT_ID=llm-label-assistant`；並在 OpenClaw 建立同名專用 agent，禁止 `exec`、檔案系統、browser、web、memory、session 與 subagent 等宿主工具。完整環境變數見 [`.env.example`](.env.example)。

## v5.1.0 更新重點

### AI 分類試跑流程

自動分類改為「先試跑、檢查結果、再繼續」的漸進式流程，降低第一次執行大量資料前的風險與設定負擔。

- 主畫面精簡分類準則、執行方式、模型與資料範圍；低頻選項繼續放在進階設定。
- 第一次試跑會從選定範圍隨機抽取最多 20 筆。
- 調整 Codebook 後再次試跑會沿用同一批樣本，方便比較規則修改前後的結果。
- 結果頁提供「換一批」，需要時可重新隨機抽取 20 筆。
- 試跑完成後可逐筆查看原文、相關性、標籤與模型判斷理由。
- 「繼續分類剩餘資料」會排除該輪已成功完成的試跑樣本，避免重複呼叫模型。
- Platform API 與 MCP Agent 共用試跑流程。

### 分類輪次與結果快照

- `tasks` 新增 `run_kind`、`sample_size` 與 `continued_from_task_id`，區分試跑及完整分類。
- 新增 `task_result_snapshots`，每張任務保存當輪結果；後續分類不會覆蓋歷史試跑結果。
- 任務紀錄會標示「試跑／完整分類」，完成的試跑可以重新開啟查看。
- 接續完整分類前會驗證來源試跑、結果 slot 與 Prompt fingerprint，規則已改變時要求重新試跑。
- 所有新任務在建立時固定 `task_items` 範圍，保留既有 durable execution 與 restart recovery 行為。

## v5.0.3 更新重點

### 只重跑解析失敗

自動分類的「資料範圍」新增 **只重跑解析失敗**，用來快速重新處理模型已回傳內容、但 JSON / Annotation Schema 解析失敗的資料。

- 新增 task target：`parse_failed`。
- 只匹配所選結果 slot 中 `reason` 為 `⚠️ 解析失敗...` 的資料。
- 不會把 HTTP error、429、timeout 或其他 transport failure 混入解析錯誤重跑。
- Platform API 與 MCP Agent 都支援相同的解析失敗重跑範圍。
- 多模型比較時，每個 slot 各自判斷自己的解析失敗資料，不會互相混用。
- 任務建立時會把符合條件的 row snapshot 到 PostgreSQL `task_items`，因此同樣支援 v5.0.2 的 durable background execution、restart recovery、watchdog 與 lease recovery。
- 若重跑後模型仍產生無法解析的輸出，該次任務仍會正常完成並保留解析失敗結果，不會自動進入無限 retry loop；之後可再次使用「只重跑解析失敗」。

目前資料範圍共有：

```text
只分類待審資料
只重跑解析失敗
重新分類全部資料
```

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

## 版本歷程

- `v5.2.0`：新增 OpenClaw 專案任務助手、Markdown 對話、每位使用者／專案的獨立對話與清除功能；採用受限專用 agent，並由平台後端自動驗證及執行建立／停止分類任務。
- `v5.1.0`：新增隨機 20 筆試跑、固定樣本重試、換一批、結果檢查與接續剩餘資料；新增 task-level 結果快照並簡化自動分類介面。
- `v5.0.3`：新增「只重跑解析失敗」資料範圍，依結果 slot 精準重跑 JSON / Schema 解析錯誤；API / MCP 共用相同 target，並以 `task_items` snapshot 接續 v5.0.2 durable recovery 行為。
- `v5.0.2`：API 分類任務改為 PostgreSQL durable checkpoints，支援瀏覽器關閉後持續執行、App/container restart 自動恢復、watchdog/lease recovery；LLM HTTP path 改為真正可達 100 並發的專用 executor、共享 connection pool、全域 in-flight guard 與 transient error retry/backoff。
- `v5.0.1`：Shared Prompt / Codebook 規則穩定化、API / MCP 共用 prompt policy、task-level prompt fingerprint，以及分類 Concurrency 上限提高至 100。
- `v5.0.0`：通用資料匯入與 Mapping、動態 Annotation Schema、generic canonical result、重新設計的自動分類 UI、專用 Codebook 編輯器、API / MCP 雙執行路徑、常駐任務中心與進階分類設定整理。
- `v4.0.0`：Remote MCP 改用 OAuth 2.1 GUI onboarding，提供可撤銷、有期限的連線 token、scope／project 限制與 ChatGPT Custom MCP App 管理文件；PAT／CLI 模式改為進階 fallback。
- `v3.0.2`：新增專案 Codebook、情感子類型「未確定」、完整子類型顯示，並修復 DB connection pool 洩漏。
- `v3.0.1`：優化總表分頁與相鄰筆數導覽的計數查詢。
- `v3.0.0`：新增未確定狀態、前端查詢管理與 PostgreSQL 效能優化。
- `v2.0.0-postgresql`：正式資料庫由 SQLite 遷移至 PostgreSQL。
- `v1.0.0-sqlite`：最後一個使用 SQLite 的版本。
