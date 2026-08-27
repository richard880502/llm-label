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

        conn.execute("ALTER TABLE rows ADD COLUMN IF NOT EXISTS text TEXT")
        conn.execute(
            "ALTER TABLE rows ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
        conn.execute("ALTER TABLE rows ADD COLUMN IF NOT EXISTS prediction JSONB")
        conn.execute("ALTER TABLE rows ADD COLUMN IF NOT EXISTS corrected_result JSONB")

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

        # Canonical text defaults to the current annotation target. Do not overwrite rows
        # that have already been normalized by the generic import pipeline.
        conn.execute(
            """UPDATE rows
               SET text=COALESCE(NULLIF(comment_content, ''), content, '')
               WHERE text IS NULL"""
        )
        conn.commit()
