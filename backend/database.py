import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path("/app/data/annotation.db")


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    NOT NULL UNIQUE,
            password_hash TEXT   NOT NULL,
            role         TEXT    NOT NULL DEFAULT 'reviewer',
            created_at   TEXT    DEFAULT (datetime('now', 'localtime')),
            is_active    INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            filename    TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
            total_rows  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS rows (
            id                           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id                   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_row_number            INTEGER,
            original_data                TEXT    NOT NULL,
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
            reviewed_at                  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_rows_project ON rows(project_id);
        CREATE INDEX IF NOT EXISTS idx_rows_status  ON rows(project_id, status);
    """)
    # migrations
    for ddl in [
        "ALTER TABLE projects ADD COLUMN llm_config TEXT",
        "ALTER TABLE rows ADD COLUMN reviewer_id INTEGER REFERENCES users(id)",
        "ALTER TABLE rows ADD COLUMN llm_updated_at TEXT",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE users ADD COLUMN google_sub TEXT",
        "ALTER TABLE users ADD COLUMN totp_secret TEXT",
        "ALTER TABLE users ADD COLUMN totp_enabled INTEGER DEFAULT 0",
        "ALTER TABLE llm_configs ADD COLUMN concurrency INTEGER DEFAULT 1",
        "ALTER TABLE tasks ADD COLUMN slot INTEGER",
        "ALTER TABLE rows ADD COLUMN version INTEGER DEFAULT 0",
        "ALTER TABLE llm_configs ADD COLUMN extra_body TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN execution_mode TEXT DEFAULT 'api'",
        "ALTER TABLE tasks ADD COLUMN executor_name TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN target TEXT DEFAULT 'pending'",
        "ALTER TABLE tasks ADD COLUMN created_by TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN claimed_by TEXT DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN last_activity_at TEXT",
        "ALTER TABLE tasks ADD COLUMN failed INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(ddl)
            conn.commit()
        except Exception:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            slot        INTEGER,
            status      TEXT DEFAULT 'pending',
            total       INTEGER DEFAULT 0,
            processed   INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now', 'localtime')),
            finished_at TEXT,
            error       TEXT,
            execution_mode TEXT DEFAULT 'api',
            executor_name TEXT DEFAULT '',
            target      TEXT DEFAULT 'pending',
            created_by  TEXT DEFAULT '',
            claimed_by  TEXT DEFAULT '',
            last_activity_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id          INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            row_id           INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
            status           TEXT DEFAULT 'pending',
            lease_token      TEXT,
            lease_expires_at TEXT,
            error            TEXT,
            created_at       TEXT DEFAULT (datetime('now', 'localtime')),
            completed_at     TEXT,
            UNIQUE(task_id, row_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_items_task_status ON task_items(task_id, status)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_tokens (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            name         TEXT NOT NULL DEFAULT 'Codex / Claude MCP',
            token_hash   TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now', 'localtime')),
            last_used_at TEXT,
            revoked_at   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_tokens_username ON api_tokens(username)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_configs (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id         INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            slot               INTEGER NOT NULL,
            name               TEXT    DEFAULT '',
            api_url            TEXT    DEFAULT '',
            api_key            TEXT    DEFAULT '',
            model              TEXT    DEFAULT '',
            prompt_template    TEXT    DEFAULT '',
            examples_mode      TEXT    DEFAULT 'corrected_only',
            examples_per_label INTEGER DEFAULT 3,
            concurrency        INTEGER DEFAULT 1,
            extra_body         TEXT DEFAULT '',
            UNIQUE(project_id, slot)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_configs_project ON llm_configs(project_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS row_llm_results (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            row_id     INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
            slot       INTEGER NOT NULL,
            relevance  TEXT,
            labels     TEXT    DEFAULT '[]',
            subtypes   TEXT    DEFAULT '[]',
            reason     TEXT    DEFAULT '',
            updated_at TEXT    DEFAULT (datetime('now', 'localtime')),
            UNIQUE(row_id, slot)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_row_llm_results_row ON row_llm_results(row_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL,
            row_id      INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
            username    TEXT    NOT NULL,
            status      TEXT,
            relevance   TEXT,
            labels      TEXT,
            changed_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_row ON audit_log(row_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS presence (
            username    TEXT    NOT NULL,
            row_id      INTEGER NOT NULL REFERENCES rows(id) ON DELETE CASCADE,
            project_id  INTEGER NOT NULL,
            last_seen   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (username, row_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_presence_project ON presence(project_id)")
    _fix_pipe_labels(conn)
    _ensure_admin(conn)
    conn.commit()
    conn.close()


def _fix_pipe_labels(conn: sqlite3.Connection) -> None:
    """Fix rows where ai_labels or ai_emotional_subtypes contain pipe-separated values stored as a single string."""
    for field in ("ai_labels", "ai_emotional_subtypes"):
        rows = conn.execute(
            f"SELECT id, {field} FROM rows WHERE {field} LIKE '%|%'"
        ).fetchall()
        for row in rows:
            val = row[field]
            if not val:
                continue
            try:
                items = json.loads(val)
            except Exception:
                continue
            fixed = []
            changed = False
            for item in items:
                if "|" in item:
                    fixed.extend([x.strip() for x in item.split("|") if x.strip()])
                    changed = True
                else:
                    fixed.append(item)
            if changed:
                conn.execute(
                    f"UPDATE rows SET {field} = ? WHERE id = ?",
                    (json.dumps(fixed, ensure_ascii=False), row["id"]),
                )
    conn.commit()


def _ensure_admin(conn: sqlite3.Connection) -> None:
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
