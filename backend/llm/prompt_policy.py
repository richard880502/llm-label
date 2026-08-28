import hashlib

from ..annotation.models import AnnotationSchema
from ..database import DatabaseConnection
from .generic_prompt_builder import build_generic_prompt
from .prompt_builder import DEFAULT_TEMPLATE


_FINGERPRINT_TEXT = "__TASK_PROMPT_FINGERPRINT_TEXT__"


def get_shared_prompt_template(conn: DatabaseConnection, project_id: int) -> str:
    """Return the project-scoped prompt template used by every model and MCP task.

    New projects store the canonical template on ``projects.shared_prompt_template``.
    For upgraded databases we fall back to the old slot/legacy settings so existing
    custom prompts keep working until they are saved again through the UI.
    """
    project = conn.execute(
        "SELECT shared_prompt_template, llm_config FROM projects WHERE id=?",
        (project_id,),
    ).fetchone()
    if project and (project["shared_prompt_template"] or "").strip():
        return project["shared_prompt_template"]

    slot = conn.execute(
        """SELECT prompt_template FROM llm_configs
           WHERE project_id=? AND COALESCE(prompt_template, '') != ''
           ORDER BY CASE WHEN slot=1 THEN 0 ELSE 1 END, slot
           LIMIT 1""",
        (project_id,),
    ).fetchone()
    if slot and (slot["prompt_template"] or "").strip():
        return slot["prompt_template"]

    if project and project["llm_config"]:
        import json

        try:
            legacy = json.loads(project["llm_config"])
            legacy_prompt = legacy.get("prompt_template", "")
            if isinstance(legacy_prompt, str) and legacy_prompt.strip():
                return legacy_prompt
        except Exception:
            pass

    return DEFAULT_TEMPLATE


def set_shared_prompt_template(
    conn: DatabaseConnection,
    project_id: int,
    template: str,
) -> str:
    """Persist one canonical prompt for the project.

    Slot prompt columns are also synchronized for backward compatibility with old
    clients, but runtime code reads the project-scoped value above.
    """
    effective = template if template.strip() else DEFAULT_TEMPLATE
    updated = conn.execute(
        "UPDATE projects SET shared_prompt_template=? WHERE id=?",
        (effective, project_id),
    )
    if updated.rowcount == 0:
        raise ValueError("Project not found")
    conn.execute(
        "UPDATE llm_configs SET prompt_template=? WHERE project_id=?",
        (effective, project_id),
    )
    return effective


def prompt_fingerprint(
    template: str,
    examples: list[dict],
    project_instructions: str,
    schema: AnnotationSchema,
) -> str:
    """Fingerprint every rule-bearing part of an effective prompt except row text.

    Few-shot examples are included because they are injected into the prompt and can
    otherwise make an MCP task change behavior between batches.
    """
    effective_prompt = build_generic_prompt(
        template,
        examples,
        _FINGERPRINT_TEXT,
        project_instructions,
        schema,
    )
    return hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest()
