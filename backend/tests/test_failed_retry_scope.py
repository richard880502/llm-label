from backend.routers.tasks import _eligible_rows


class _EmptyResult:
    def fetchall(self):
        return []


class _RecordingConnection:
    def __init__(self):
        self.sql = ""
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params
        return _EmptyResult()


def test_failure_retry_scope_includes_all_warning_marked_results():
    conn = _RecordingConnection()

    _eligible_rows(conn, project_id=42, target="parse_failed", slot=2)

    normalized_sql = " ".join(conn.sql.split())
    assert "rlr.reason LIKE '⚠️%'" in normalized_sql
    assert "解析失敗" not in normalized_sql
    assert conn.params == (2, 42)
