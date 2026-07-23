#!/usr/bin/env python3
"""One-time, non-destructive migration from annotation.db to PostgreSQL."""

import argparse
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from backend.database import DATABASE_URL, init_db


TABLES = [
    "users",
    "projects",
    "rows",
    "tasks",
    "task_items",
    "api_tokens",
    "llm_configs",
    "row_llm_results",
    "audit_log",
    "presence",
]


def sqlite_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def postgres_columns(connection: psycopg.Connection, table: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    return [row[0] for row in rows]


def migrate_table(
    source: sqlite3.Connection,
    target: psycopg.Connection,
    table: str,
) -> int:
    source_columns = sqlite_columns(source, table)
    target_columns = postgres_columns(target, table)
    columns = [column for column in source_columns if column in target_columns]
    if not columns:
        return 0

    rows = source.execute(
        sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.Identifier(table),
        ).as_string(),
    ).fetchall()
    if not rows:
        return 0

    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    with target.cursor() as cursor:
        cursor.executemany(statement, [tuple(row) for row in rows])
    return len(rows)


def reset_identity(connection: psycopg.Connection, table: str) -> None:
    if "id" not in postgres_columns(connection, table):
        return
    connection.execute(
        sql.SQL(
            """
            SELECT setval(
                pg_get_serial_sequence(%s, 'id'),
                GREATEST(COALESCE((SELECT MAX(id) FROM {}), 1), 1),
                COALESCE((SELECT MAX(id) FROM {}), 0) > 0
            )
            """
        ).format(sql.Identifier(table), sql.Identifier(table)),
        (table,),
    )


def count_rows(connection: Any, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sqlite-path",
        default=os.getenv("SQLITE_SOURCE_PATH", "/app/legacy-data/annotation.db"),
    )
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="Allow import into a non-empty PostgreSQL database; duplicates are skipped.",
    )
    args = parser.parse_args()

    source_path = Path(args.sqlite_path)
    if not source_path.exists():
        raise SystemExit(f"找不到 SQLite 來源檔：{source_path}")

    init_db(seed_admin=False)
    temporary_source = tempfile.TemporaryDirectory(prefix="annotation-sqlite-")
    copied_path = Path(temporary_source.name) / source_path.name
    shutil.copy2(source_path, copied_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source_path}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{copied_path}{suffix}"))

    source = sqlite3.connect(str(copied_path))
    source.row_factory = sqlite3.Row
    target = psycopg.connect(DATABASE_URL)

    try:
        existing = {
            table: count_rows(target, table)
            for table in TABLES
        }
        if not args.allow_nonempty and any(existing.values()):
            details = ", ".join(
                f"{table}={count}" for table, count in existing.items() if count
            )
            raise SystemExit(
                "PostgreSQL 已有資料，為避免覆蓋已停止遷移："
                f"{details}。若確定要合併，請加 --allow-nonempty。"
            )

        migrated: dict[str, int] = {}
        for table in TABLES:
            migrated[table] = migrate_table(source, target, table)
        for table in TABLES:
            reset_identity(target, table)
        target.commit()

        mismatches = []
        for table in TABLES:
            source_count = count_rows(source, table)
            target_count = count_rows(target, table)
            if target_count < source_count:
                mismatches.append(
                    f"{table}: SQLite={source_count}, PostgreSQL={target_count}"
                )
            print(
                f"{table}: imported={migrated[table]}, "
                f"SQLite={source_count}, PostgreSQL={target_count}"
            )
        if mismatches:
            raise SystemExit("資料筆數驗證失敗：" + "; ".join(mismatches))
        print("SQLite → PostgreSQL 遷移與筆數驗證完成。舊 SQLite 檔未被修改。")
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
        temporary_source.cleanup()


if __name__ == "__main__":
    main()
