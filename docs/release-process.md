# GitHub Release 發布流程

本專案使用 [Publish GitHub Release](../.github/workflows/publish-release.yml) GitHub Actions 手動發布版本。不會因為 PR 合併、`main` push 或 Coolify 部署自動建立 Tag／Release。

## 發布新版本

1. 確認功能已驗收、PR 已合併至 `main`，且 CI、Docker、CodeQL 在 **最新 main commit** 都成功。
2. 確認 `frontend/package.json` 的 `version`，以及 `CHANGELOG.md` 有對應的 `## vX.Y.Z 更新重點` 區段。
3. 開啟 GitHub **Actions → Publish GitHub Release → Run workflow**。
4. Branch 選擇 `main`，version 輸入例如 `v5.5.0`，再點 **Run workflow**。
5. 工作流程會檢查版本／CI 狀態、建立帶註解的 Git Tag，並以 CHANGELOG 當作 Release Notes 發布 GitHub Release。

## 安全保護

- 只允許 `main`，且必須是觸發時的最新 `main` commit；如果中途有新的合併，請重新執行。
- 輸入的版本必須和 `frontend/package.json` 完全一致（加上 `v` 前綴）。
- CI、Docker、CodeQL 的 main push workflow 都需要成功，否則停止發版。
- 已存在同名 Release 會拒絕重複發布。若 Tag 已建立但 Release 失敗，可在 Tag 指向同一 Commit 時安全地重試。
- Tag／Release 使用預設 `GITHUB_TOKEN`，不必新增個人存取權杖。若 Repository 規則禁止 GitHub Actions 建立 Tag，需由管理者調整權限或規則。
- 手動執行是第一道確認。若需要第二位審核者，可再配置 GitHub Environment required reviewers。

## 舊版 Tag 注意事項

目前程式碼版本為 `5.5.0`，但歷史 `v5.4.0` Tag 尚未補齊。**不要**直接拿最新版 `main` 的 Commit 建立 `v5.4.0` Tag；必須先查出當時真正的 v5.4.0 發布 Commit，並另行補上歷史 Tag／Release。此 workflow 刻意只處理目前 `main` 的版本，避免誤標歷史版本。
