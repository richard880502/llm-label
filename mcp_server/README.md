# 標注審查平台 — MCP Server

讓 Claude Code、Codex 等支援 MCP 的 agent 工具，能直接操作標注審查平台：
瀏覽專案、查看資料、比對 LLM 歧異、修正與批次核准。

透過 HTTP 呼叫平台既有的 REST API，**後端無需任何改動**。認證使用帳密自動
登入取得 JWT，快取於記憶體，過期自動重登。

## 提供的工具

| 工具 | 說明 |
|------|------|
| `list_projects` | 列出所有專案與審查進度 |
| `get_project` | 取得單一專案的進度統計 |
| `list_rows` | 列出審查資料，支援 status / relevance / 關鍵字 / 歧異篩選與分頁 |
| `get_row` | 取得單筆完整內容，含各 LLM 槽的分析比對 |
| `update_row` | 修正或核准單筆（樂觀鎖保護，需帶 version） |
| `batch_approve` | 批次核准（指定 ID，或全選符合篩選條件的資料） |
| `list_labeling_tasks` | 列出網頁建立的分類任務 |
| `claim_labeling_task` | 領取等待中的 MCP 分類任務 |
| `get_labeling_batch` | 領取下一批資料與完整分類 Prompt（5 分鐘租約） |
| `submit_labeling_batch` | 提交結構化標籤並更新網頁任務進度 |

## 雲端部署（推薦給平台使用者）

`docker compose` 會同時啟動平台、遠端 MCP Server 與 Caddy。Caddy 將
`https://你的網域/mcp` 轉送至 Streamable HTTP MCP Server，其餘路徑仍由平台處理。

使用者可在網頁的「自動分類 → 我的 Codex／Claude Code」建立個人存取權杖。
權杖只顯示一次，平台只保存 SHA-256 雜湊，使用者可隨時撤銷。

Codex CLI 連線範例：

```bash
export ANNOTATION_MCP_TOKEN="網頁建立的 apt_ 權杖"
codex mcp add annotation-platform \
  --url https://你的網域/mcp \
  --bearer-token-env-var ANNOTATION_MCP_TOKEN
```

網頁建立 MCP 分類任務後，將顯示可直接複製給 Codex／Claude Code 的任務指令。
Agent 會依序呼叫 `claim_labeling_task` → `get_labeling_batch` →
`submit_labeling_batch`，直到任務完成。中斷超過五分鐘的批次會自動釋放，可重新領取續跑。

## 安裝

需要 Python 3.10+。推薦用 [uv](https://github.com/astral-sh/uv) 管理環境：

```bash
cd mcp_server
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

或用標準 venv（Python 需為 3.10 以上）：

```bash
cd mcp_server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 認證帳號

MCP Server 用一組平台帳號登入。建議：

- 建立一個**專用的自動化帳號**（例如 `agent-bot`），而非用個人帳號。
- 該帳號**不要啟用 TOTP 兩步驟驗證**（會導致無法自動登入）。
- 審查紀錄與 audit log 會以此帳號名義記錄，方便追蹤哪些是 agent 操作的。

## 掛載到 Claude Code

```bash
claude mcp add annotation-platform \
  --env ANNOTATION_API_URL=http://localhost:8080 \
  --env ANNOTATION_USERNAME=agent-bot \
  --env ANNOTATION_PASSWORD=你的密碼 \
  -- /Users/richard/Desktop/data/annotation-app/mcp_server/.venv/bin/python \
     /Users/richard/Desktop/data/annotation-app/mcp_server/server.py
```

掛載後在 Claude Code 裡就能直接說：

> 「列出 project 2 裡待審且沒有 LLM 歧異的資料，全部核准」

Claude 會依序呼叫 `list_rows`（篩 pending）→ `batch_approve`（select_all）完成。

## 掛載到 Codex CLI

Codex 的設定檔是 **TOML**（跟 Claude Code 的 JSON 不同），位置在 `~/.codex/config.toml`。
編輯這個檔案（沒有就新建），加入：

```toml
[mcp_servers.annotation-platform]
command = "/Users/richard/Desktop/data/annotation-app/mcp_server/.venv/bin/python"
args = ["/Users/richard/Desktop/data/annotation-app/mcp_server/server.py"]
env = { ANNOTATION_API_URL = "https://你的伺服器IP", ANNOTATION_USERNAME = "agent-bot", ANNOTATION_PASSWORD = "你的密碼", ANNOTATION_INSECURE = "1" }
```

存檔後重新啟動 `codex`，用 `/mcp` 指令（或啟動時的 MCP 狀態列表）確認
`annotation-platform` 有成功連上、6 個工具都列出來。之後就能直接對 Codex 說：

> 「列出 project 2 裡待審且沒有 LLM 歧異的資料，全部核准」

如果你的 Codex 版本有提供 `codex mcp add` 這類指令，也可以用指令產生同樣的設定，
但寫法可能隨版本調整，最穩妥的方式還是直接編輯 `config.toml`。

## 掛載到其他 MCP 客戶端（JSON 格式）

多數客戶端（例如各種 IDE 外掛）用 JSON 設定：

```json
{
  "mcpServers": {
    "annotation-platform": {
      "command": "/Users/richard/Desktop/data/annotation-app/mcp_server/.venv/bin/python",
      "args": ["/Users/richard/Desktop/data/annotation-app/mcp_server/server.py"],
      "env": {
        "ANNOTATION_API_URL": "https://你的伺服器IP",
        "ANNOTATION_USERNAME": "agent-bot",
        "ANNOTATION_PASSWORD": "你的密碼",
        "ANNOTATION_INSECURE": "1"
      }
    }
  }
}
```

## 環境變數

| 變數 | 必填 | 預設 | 說明 |
|------|------|------|------|
| `ANNOTATION_API_URL` | 否 | `http://localhost:8080` | 平台網址 |
| `ANNOTATION_USERNAME` | 是 | — | 登入帳號 |
| `ANNOTATION_PASSWORD` | 是 | — | 登入密碼 |
| `ANNOTATION_CA_CERT` | 否 | — | 自簽憑證的根 CA 檔路徑（用 Caddy `tls internal` 時建議設定） |
| `ANNOTATION_INSECURE` | 否 | — | 設為 `1` 跳過 TLS 憑證驗證（自簽最省事，但不防中間人） |

### 連到自簽憑證的 HTTPS（純 IP 部署）

若平台用 Caddy `tls internal` 自簽憑證（例如 `https://<伺服器IP>`），
httpx 預設會拒絕不受信任的憑證。兩種解法：

- **推薦**：取出 Caddy 根 CA 並指定給 MCP Server（可驗證、較安全）：
  ```bash
  # 從 caddy 容器取出根憑證
  docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
  ```
  然後設 `ANNOTATION_CA_CERT=/絕對路徑/caddy-root.crt`。

- **省事**：直接設 `ANNOTATION_INSECURE=1` 跳過驗證（連線仍加密，但不驗證對方身分）。

## 安全建議

- **不要自動核准有歧異的資料。** `select_all` 無法直接排除歧異資料
  （`disagreement_filter=only` 反而是「只選有歧異的」）。要安全地只核准
  無歧異者，請用指定 ID 的模式：先用 `list_rows` 逐頁挑出 `llm_disagreement=False`
  的 id，再把這些 id 傳入 `batch_approve` 的 `row_ids`。有歧異的交給人工判斷。
- 樂觀鎖：`update_row` 需帶 `version`，若與伺服器不符會回傳衝突，
  agent 應重新 `get_row` 取得最新版本再更新，避免覆蓋他人修改。
- 用專用帳號 + audit log，所有 agent 操作都可追溯。

## 手動測試

```bash
export ANNOTATION_API_URL=http://localhost:8080
export ANNOTATION_USERNAME=agent-bot
export ANNOTATION_PASSWORD=你的密碼

.venv/bin/python -c "import server; print(server.list_projects())"
```
