# Annotation App

多人協作的資料標注與複查平台。前端使用 React/Vite，後端使用 FastAPI，
正式資料儲存在獨立 PostgreSQL 服務。

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
