from typing import Any, Literal

from pydantic import BaseModel, Field


class LabelDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    parent_id: str | None = None
    examples: list[str] = Field(default_factory=list)
    enabled: bool = True


class RelevanceValue(BaseModel):
    id: str
    name: str


class RelevanceSchema(BaseModel):
    enabled: bool = True
    values: list[RelevanceValue] = Field(default_factory=list)


class SchemaConstraints(BaseModel):
    max_depth: int = 2
    max_labels: int | None = None
    child_requires_parent: bool = True
    require_child_for: list[str] = Field(default_factory=list)


class AnnotationSchema(BaseModel):
    version: int = 1
    mode: Literal["single_label", "multi_label"] = "multi_label"
    labels: list[LabelDefinition] = Field(default_factory=list)
    constraints: SchemaConstraints = Field(default_factory=SchemaConstraints)
    relevance: RelevanceSchema | None = None


class LabelFieldMapping(BaseModel):
    field: str
    format: Literal["single", "delimiter", "json"] = "single"
    delimiter: str | None = None


class HierarchyFieldMapping(BaseModel):
    parent_field: str | None = None
    child_field: str | None = None


class InputMapping(BaseModel):
    text_field: str
    id_field: str | None = None
    labels: LabelFieldMapping | None = None
    hierarchy: HierarchyFieldMapping | None = None
    metadata_fields: list[str] = Field(default_factory=list)
    context_fields: list[str] = Field(default_factory=list)


class CanonicalDatasetRow(BaseModel):
    id: str | None = None
    text: str
    source_labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    original_data: dict[str, Any] = Field(default_factory=dict)


class AnnotationResult(BaseModel):
    relevance: str | None = None
    labels: list[str] = Field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
