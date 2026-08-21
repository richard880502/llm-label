import os
import re
import time
from collections.abc import Iterator, Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://annotation:annotation-local-password@localhost:5433/annotation",
)


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer setting without making a bad env var break startup."""

    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


# A web request, MCP auth request, and background classifier can all query
# PostgreSQL concurrently. Keep this independently configurable for a small
# local database or a larger production service.
DB_POOL_MIN_SIZE = _positive_int_env("DB_POOL_MIN_SIZE", 4)
DB_POOL_MAX_SIZE = max(DB_POOL_MIN_SIZE, _positive_int_env("DB_POOL_MAX_SIZE", 40))
DB_POOL_TIMEOUT_SECONDS = _positive_int_env("DB_POOL_TIMEOUT_SECONDS", 20)

_NOW_SQL = (
    "to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', "
    "'YYYY-MM-DD HH24:MI:SS')"
)
_PLUS_FIVE_MINUTES_SQL = (
    "to_char((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei') + interval '5 minutes', "
    "'YYYY-MM-DD HH24:MI:SS')"
)
_MINUS_THIRTY_SECONDS_SQL = (
    "to_char((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei') - interval '30 seconds', "
    "'YYYY-MM-DD HH24:MI:SS')"
)


class DatabaseRow(Mapping[str, Any]):
    """Mapping row that also preserves sqlite3.Row-style numeric indexing."""

    def __init__(self, values: dict[str, Any]):
        self._values = values
        self._ordered_values = tuple(values.values())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._ordered_values[key]
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class QueryResult:
    def __init__(self, cursor: psycopg.Cursor, lastrowid: int | None = None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self) -> DatabaseRow | None:
        row = self._cursor.fetchone()
        return DatabaseRow(row) if row is not None else None

    def fetchall(self) -> list[DatabaseRow]:
        return [DatabaseRow(row) for row in self._cursor.fetchall()]


def _translate_sql(sql: str) -> str:
    """Translate the small SQLite SQL subset still used by existing routers."""

    translated = re.sub(
        r"datetime\(\s*'now'\s*,\s*'localtime'\s*,\s*'\+5 minutes'\s*\)",
        _PLUS_FIVE_MINUTES_SQL,
        sql,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"datetime\(\s*'now'\s*,\s*'localtime'\s*,\s*'-30 seconds'\s*\)",
        _MINUS_THIRTY_SECONDS_SQL,
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"datetime\(\s*'now'\s*,\s*'localtime'\s*\)",
        _NOW_SQL,
        translated,
        flags=re.IGNORECASE,
    )
    return translated.replace("?", "%s")


def _escape_literal_percent(sql: str) -> str:
    """Escape SQL LIKE wildcards when psycopg also receives bind parameters."""

    return re.sub(r"%(?![sbt%])", "%%", sql)


class DatabaseConnection:
    def __init__(self, connection: psycopg.Connection, pool: ConnectionPool | None = None):
        self._connection = connection
        self._pool = pool

    def execute(self, sql: str, params: tuple | list | None = None) -> QueryResult:
        translated = _translate_sql(sql)
        if params:
            translated = _escape_literal_percent(translated)
        cursor = self._connection.cursor(row_factory=dict_row)
        lastrowid = None
        needs_id = re.match(
            r"^\s*INSERT\s+INTO\s+(projects|tasks|api_tokens|mcp_oauth_clients|mcp_oauth_connections|mcp_oauth_tokens)\b",
            translated,
            flags=re.IGNORECASE,
        )
        if needs_id and " RETURNING " not in translated.upper():
            translated = f"{translated.rstrip().rstrip(';')} RETURNING id"
            if params:
                cursor.execute(translated, params)
            else:
                cursor.execute(translated)
            returned = cursor.fetchone()
            lastrowid = int(returned["id"]) if returned else None
        else:
            if params:
                cursor.execute(translated, params)
            else:
                cursor.execute(translated)
        return QueryResult(cursor, lastrowid=lastrowid)

    def executemany(self, sql: str, params_seq: list[tuple]) -> QueryResult:
        cursor = self._connection.cursor(row_factory=dict_row)
        translated = _escape_literal_percent(_translate_sql(sql))
        cursor.executemany(translated, params_seq)
        return QueryResult(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.putconn(self._connection)
        else:
            self._connection.close()

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Guarantee the connection always goes back to the pool, even when the
        # caller raises mid-query (error, HTTPException, cancellation). Without
        # this, a leaked connection is never returned via pool.putconn() and the
        # pool permanently shrinks until it's exhausted (see incident: PoolTimeout
        # on /api/projects).
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            self.close()


_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=DB_POOL_MIN_SIZE,
            max_size=DB_POOL_MAX_SIZE,
            timeout=DB_POOL_TIMEOUT_SECONDS,
            max_idle=300,
            max_lifetime=1800,
            kwargs={
                "autocommit": False,
                # Defense in depth: if application code ever again fails to
                # rollback/close, Postgres itself will kill a connection stuck
                # in an open transaction or a runaway query instead of holding
                # it (and its pool slot) forever.
                "options": "-c idle_in_transaction_session_timeout=30000 -c statement_timeout=60000",
            },
        )
    return _pool


def get_db() -> DatabaseConnection:
    pool = _get_pool()
    return DatabaseConnection(pool.getconn(), pool=pool)


SCHEMA_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        username      TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'reviewer',
        created_at    TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        is_active     INTEGER DEFAULT 1,
        email         TEXT,
        google_sub    TEXT,
        totp_secret   TEXT,
        totp_enabled  INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    """
    CREATE TABLE IF NOT EXISTS projects (
        id          INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name        TEXT NOT NULL,
        filename    TEXT NOT NULL,
        created_at  TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        total_rows  INTEGER DEFAULT 0,
        llm_config  TEXT,
        annotation_instructions TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS rows (
        id                           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        project_id                   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        source_row_number            INTEGER,
        original_data                TEXT NOT NULL,
        content                      TEXT,
        comment_content              TEXT,
        ai_relevance                 TEXT,
        ai_labels                    TEXT,
        ai_emotional_subtypes        TEXT,
        ai_reason                    TEXT,
        corrected_relevance          TEXT,
        corrected_labels             TEXT,
        corrected_emotional_subtypes TEXT,
        reviewer_note                TEXT,
        status                       TEXT DEFAULT 'pending',
        reviewed_at                  TEXT,
        reviewer_id                  INTEGER REFERENCES users(id) ON DELETE SET NULL,
        llm_updated_at               TEXT,
        version                      INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rows_project ON rows(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_rows_status ON rows(project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_rows_reviewer ON rows(reviewer_id)",
    "CREATE INDEX IF NOT EXISTS idx_rows_project_source_num ON rows(project_id, source_row_number, id)",
    """
    CREATE INDEX IF NOT EXISTS idx_rows_project_corrected_reviewed
        ON rows(project_id, reviewed_at DESC) WHERE corrected_relevance IS NOT NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_rows_project_status_reviewed ON rows(project_id, status, reviewed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rows_content_trgm ON rows USING GIN (content gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_rows_comment_content_trgm ON rows USING GIN (comment_content gin_trgm_ops)",
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id               INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        slot             INTEGER,
        status           TEXT DEFAULT 'pending',
        total            INTEGER DEFAULT 0,
        processed        INTEGER DEFAULT 0,
        failed           INTEGER DEFAULT 0,
        created_at       TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        finished_at      TEXT,
        error            TEXT,
        execution_mode   TEXT DEFAULT 'api',
        executor_name    TEXT DEFAULT '',
        target           TEXT DEFAULT 'pending',
        created_by       TEXT DEFAULT '',
        claimed_by       TEXT DEFAULT '',
        last_activity_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
    """
    CREATE TABLE IF NOT EXISTS task_items (
        id               INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        task_id          INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        row_id           INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
        status           TEXT DEFAULT 'pending',
        lease_token      TEXT,
        lease_expires_at TEXT,
        error            TEXT,
        created_at       TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        completed_at     TEXT,
        UNIQUE(task_id, row_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_items_task_status ON task_items(task_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_task_items_row ON task_items(row_id)",
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
        id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        username     TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        name         TEXT NOT NULL DEFAULT 'Codex / Claude MCP',
        token_hash   TEXT NOT NULL UNIQUE,
        token_prefix TEXT NOT NULL,
        created_at   TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        last_used_at TEXT,
        revoked_at   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_api_tokens_username ON api_tokens(username)",
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
        id            INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        client_id     TEXT NOT NULL UNIQUE,
        client_name   TEXT NOT NULL DEFAULT 'MCP client',
        redirect_uris TEXT NOT NULL,
        created_at    TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_authorization_codes (
        id             INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        code_hash      TEXT NOT NULL UNIQUE,
        client_id      TEXT NOT NULL REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
        username       TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        redirect_uri   TEXT NOT NULL,
        scopes         TEXT NOT NULL,
        project_ids    TEXT NOT NULL DEFAULT '[]',
        code_challenge TEXT NOT NULL,
        expires_at     TEXT NOT NULL,
        consumed_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mcp_oauth_codes_client ON mcp_oauth_authorization_codes(client_id)",
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_connections (
        id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        username     TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        client_id    TEXT NOT NULL REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
        client_name  TEXT NOT NULL,
        scopes       TEXT NOT NULL,
        project_ids  TEXT NOT NULL DEFAULT '[]',
        created_at   TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        last_used_at TEXT,
        revoked_at   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mcp_oauth_connections_username ON mcp_oauth_connections(username)",
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
        id                 INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        connection_id      INTEGER NOT NULL REFERENCES mcp_oauth_connections(id) ON DELETE CASCADE,
        access_token_hash  TEXT NOT NULL UNIQUE,
        refresh_token_hash TEXT UNIQUE,
        expires_at         TEXT NOT NULL,
        created_at         TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        last_used_at       TEXT,
        revoked_at         TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mcp_oauth_tokens_connection ON mcp_oauth_tokens(connection_id)",
    """
    CREATE TABLE IF NOT EXISTS llm_configs (
        id                 INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        project_id         INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        slot               INTEGER NOT NULL,
        name               TEXT DEFAULT '',
        api_url            TEXT DEFAULT '',
        api_key            TEXT DEFAULT '',
        model              TEXT DEFAULT '',
        prompt_template    TEXT DEFAULT '',
        examples_mode      TEXT DEFAULT 'corrected_only',
        examples_per_label INTEGER DEFAULT 3,
        concurrency        INTEGER DEFAULT 1,
        extra_body         TEXT DEFAULT '',
        UNIQUE(project_id, slot)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_llm_configs_project ON llm_configs(project_id)",
    """
    CREATE TABLE IF NOT EXISTS row_llm_results (
        id          INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        row_id      INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
        slot        INTEGER NOT NULL,
        source_name TEXT DEFAULT '',
        relevance   TEXT,
        labels      TEXT DEFAULT '[]',
        subtypes    TEXT DEFAULT '[]',
        reason      TEXT DEFAULT '',
        updated_at  TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        UNIQUE(row_id, slot)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_row_llm_results_row ON row_llm_results(row_id)",
    "CREATE INDEX IF NOT EXISTS idx_row_llm_results_row_relevance ON row_llm_results(row_id, relevance)",
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        project_id INTEGER NOT NULL,
        row_id     INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
        username   TEXT NOT NULL,
        status     TEXT,
        relevance  TEXT,
        labels     TEXT,
        changed_at TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_row ON audit_log(row_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_row_changed ON audit_log(row_id, changed_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS presence (
        username  TEXT NOT NULL,
        row_id    INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
        project_id INTEGER NOT NULL,
        last_seen TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei', 'YYYY-MM-DD HH24:MI:SS'),
        PRIMARY KEY (username, row_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_presence_project ON presence(project_id)",
]


def init_db(*, seed_admin: bool = True) -> None:
    last_error: Exception | None = None
    for attempt in range(20):
        try:
            conn = get_db()
            break
        except Exception as error:
            last_error = error
            if attempt == 19:
                raise
            time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL 連線失敗") from last_error

    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        # CREATE TABLE IF NOT EXISTS 不會替既有資料庫補欄位；部署新版本時以
        # ADD COLUMN IF NOT EXISTS 保留既有專案與資料。
        conn.execute(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS annotation_instructions TEXT NOT NULL DEFAULT ''"
        )
        _fix_pipe_labels(conn)
        if seed_admin:
            _ensure_admin(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fix_pipe_labels(conn: DatabaseConnection) -> None:
    """Fix legacy labels where pipe-separated values were stored as one JSON item."""

    import json

    for field in ("ai_labels", "ai_emotional_subtypes"):
        rows = conn.execute(
            f"SELECT id, {field} FROM rows WHERE {field} LIKE '%|%'"
        ).fetchall()
        for row in rows:
            value = row[field]
            if not value:
                continue
            try:
                items = json.loads(value)
            except Exception:
                continue
            fixed: list[str] = []
            changed = False
            for item in items:
                if "|" in item:
                    fixed.extend(part.strip() for part in item.split("|") if part.strip())
                    changed = True
                else:
                    fixed.append(item)
            if changed:
                conn.execute(
                    f"UPDATE rows SET {field} = ? WHERE id = ?",
                    (json.dumps(fixed, ensure_ascii=False), row["id"]),
                )


def _ensure_admin(conn: DatabaseConnection) -> None:
    from .auth import hash_password

    existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        return
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "admin")
    conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
        (username, hash_password(password)),
    )
