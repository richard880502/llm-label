import json

from ..database import get_db
from .legacy import fresh_legacy_input_mapping, fresh_legacy_schema


def ensure_annotation_schema_columns() -> None:
    """Add issue #6 generic schema columns without breaking existing projects."""
    schema_json = json.dumps(fresh_legacy_schema().model_dump(mode="json"), ensure_ascii=False)
    mapping_json = json.dumps(fresh_legacy_input_mapping().model_dump(mode="json"), ensure_ascii=False)

    with get_db() as conn:
        conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS input_mapping JSONB")
        conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS label_schema JSONB")
        conn.execute(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS shared_prompt_template TEXT NOT NULL DEFAULT ''"
        )

        conn.execute("ALTER TABLE rows ADD COLUMN IF NOT EXISTS text TEXT")
        conn.execute(
            "ALTER TABLE rows ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
        conn.execute("ALTER TABLE rows ADD COLUMN IF NOT EXISTS prediction JSONB")
        conn.execute("ALTER TABLE rows ADD COLUMN IF NOT EXISTS corrected_result JSONB")

        # Multi-LLM projects need a canonical result per slot; rows.prediction is only
        # the primary (slot 1) projection used by the main review flow.
        conn.execute("ALTER TABLE row_llm_results ADD COLUMN IF NOT EXISTS result JSONB")

        # Each configured model can have a different response speed. Keep its request
        # timeout beside the rest of the slot configuration so API tasks can use it and
        # size their durable row leases to the same request/retry budget.
        conn.execute(
            "ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 180"
        )

        # Tasks keep only a compact rule fingerprint, not prediction history. This lets
        # API and MCP executions detect prompt/codebook drift without storing old outputs.
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS prompt_fingerprint TEXT NOT NULL DEFAULT ''"
        )

        # Existing projects become explicit legacy-schema projects. Runtime fallbacks in
        # project_service remain as a second safety net for partially migrated databases.
        conn.execute(
            "UPDATE projects SET label_schema=?::jsonb WHERE label_schema IS NULL",
            (schema_json,),
        )
        conn.execute(
            "UPDATE projects SET input_mapping=?::jsonb WHERE input_mapping IS NULL",
            (mapping_json,),
        )

        # Promote an existing custom per-slot/legacy prompt to the new project-scoped
        # prompt once. Prefer slot 1, then the first configured slot. Invalid legacy JSON
        # is ignored rather than blocking startup.
        projects = conn.execute(
            "SELECT id, shared_prompt_template, llm_config FROM projects"
        ).fetchall()
        for project in projects:
            if (project["shared_prompt_template"] or "").strip():
                continue
            slot = conn.execute(
                """SELECT prompt_template FROM llm_configs
                   WHERE project_id=? AND COALESCE(prompt_template, '') != ''
                   ORDER BY CASE WHEN slot=1 THEN 0 ELSE 1 END, slot
                   LIMIT 1""",
                (project["id"],),
            ).fetchone()
            candidate = slot["prompt_template"] if slot else ""
            if not candidate and project["llm_config"]:
                try:
                    legacy = json.loads(project["llm_config"])
                    candidate = legacy.get("prompt_template", "")
                except Exception:
                    candidate = ""
            if isinstance(candidate, str) and candidate.strip():
                conn.execute(
                    "UPDATE projects SET shared_prompt_template=? WHERE id=?",
                    (candidate, project["id"],),
                )

        # Canonical text defaults to the current annotation target. Do not overwrite rows
        # that have already been normalized by the generic import pipeline.
        conn.execute(
            """UPDATE rows
               SET text=COALESCE(NULLIF(comment_content, ''), content, '')
               WHERE text IS NULL"""
        )
        conn.commit()
