# Codex／ChatGPT Custom MCP App

本文件給 `llm-label` 管理者使用。一般使用者不需要建立 `apt_` token、設定環境變數，
只需要從已發布的 App 按 **Connect**，登入平台並同意所需權限。

## 前置條件

1. 將 v4.0.0 部署到公網 HTTPS 網域，例如 `https://llm-judge.zeabur.app`。
2. 確認同一個公開網域可以存取：

   ```text
   https://<domain>/mcp
   https://<domain>/.well-known/oauth-protected-resource/mcp
   https://<domain>/.well-known/oauth-authorization-server
   ```

3. 不要將 PostgreSQL 公開；`DATABASE_URL`、`SECRET_KEY`、管理員密碼與 Google Client ID
   均維持為 Zeabur 非公開環境變數。

## 建立並測試 Draft

1. 在 ChatGPT Workspace 中啟用 **Developer mode**（需依方案由 workspace admin／owner
   啟用）。前往 **Workspace Settings → Apps → Create**。
2. Endpoint 填入 `https://<domain>/mcp`，選擇 OAuth authentication。
3. 按 **Scan Tools**。系統會透過 MCP Protected Resource Metadata 發現 OAuth endpoint，
   並開啟 llm-label 登入頁。可使用原有帳密、Google Login，及帳號已啟用時的 TOTP。
4. 在同意頁選擇權限。預設建議只保留：

   ```text
   projects:read rows:read tasks:read tasks:run
   ```

   `rows:write`、`reviews:approve` 與尤其 `reviews:batch_approve` 都必須明確勾選。
   如只讓 App 處理少數專案，可填入逗號分隔的 project IDs。
5. 完成 Scan 後建立 Draft，在新對話中選取它，驗證：

   - 列出專案與資料列；
   - 建立並完成至少一個 labeling task；
   - 若 client 請求並同意 `offline_access`，OAuth token 過期後能透過 refresh token 重新連線；
   - 從 **LLM 設定 → Codex／ChatGPT GUI App** 撤銷連線後，舊 token 立即失效。

ChatGPT 對寫入操作仍會顯示確認；不要只依賴這個 UI 保護，scope 是服務端強制執行的。

## 發布到 Workspace

測試通過後，workspace admin／owner 前往 **Workspace Settings → Apps → Drafts**，選擇
**Publish**。發布前再次檢查 action control：新增或變更的 write actions 應維持停用，直到
完成安全檢查。一般使用者會在 Apps 設定中看到 custom App，按 **Connect** 即可完成自己的 OAuth
連線。

目前 ChatGPT 的 Custom MCP App 能力與可用方案可能調整；請以
[OpenAI 官方 Developer Mode 文件](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta)
為準。

## 疑難排解

- **Scan Tools 直接失敗**：確認 `/mcp` 回傳 `401` 時有 `WWW-Authenticate` 的
  `resource_metadata`，且兩個 `.well-known` JSON 的 issuer／resource 都是相同的公開 HTTPS origin。
- **登入後回不到 App**：OAuth client 的 redirect URI 由 client 動態註冊並嚴格比對；不要經由
  不同網域、HTTP 或會改寫 query string 的 proxy。
- **token 過期後重新要求登入**：若 client 有請求 `offline_access`，確認同意頁已選取它；系統會輪替 refresh token，
  不會延長 access token 的一小時有效期。
- **工具收到 403**：查看連線的 scopes 與 project 限制；核准工具需要額外的
  `reviews:approve` 或 `reviews:batch_approve`。

## CLI／Developer fallback

既有 Personal Access Token 和 Codex／Claude Code 設定方式仍可使用，適合不支援 OAuth 的
開發工具。請在 LLM 設定的 **CLI／Developer access token** 區塊建立、使用及撤銷 token；它不再是
一般使用者的建議 onboarding。
