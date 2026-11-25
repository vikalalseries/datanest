from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ColumnType = Literal["text", "number", "currency", "date", "boolean", "email", "url", "status", "tags"]


class WorkspaceOut(BaseModel):
    id: UUID
    name: str


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    created_at: datetime
    workspace: WorkspaceOut


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------- sheets ----------
class ColumnIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: ColumnType = "text"
    options: list[str] | None = Field(default=None, max_length=100)


class ColumnOut(BaseModel):
    id: str
    name: str
    type: ColumnType
    options: list[str] | None = None


class SheetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str = Field(default="general", max_length=60)
    columns: list[ColumnIn] = Field(default_factory=list, max_length=100)


class SheetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=60)


class ColumnUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    type: ColumnType | None = None
    options: list[str] | None = Field(default=None, max_length=100)
    force: bool = False  # change type even if some values cannot convert (they become empty)


class ColumnOrder(BaseModel):
    ids: list[str] = Field(max_length=100)


class SheetOut(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    category: str
    columns: list[ColumnOut]
    record_count: int = 0
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------- records ----------
class RecordCreate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class RecordUpdate(BaseModel):
    data: dict[str, Any]  # partial: only the given columns change; null clears a cell


class RecordOut(BaseModel):
    id: UUID
    sheet_id: UUID
    data: dict[str, Any]
    source_type: str
    source_url: str | None = None
    source_file_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    sheet_name: str | None = None


class RecordPage(BaseModel):
    items: list[RecordOut]
    total: int
    limit: int
    offset: int


class IdList(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=500)


class MoveRecords(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=500)
    target_sheet_id: UUID
    add_missing_columns: bool = False


class ExtractedRowIn(BaseModel):
    values: dict[str, Any]  # keyed by column NAME (as shown in the preview)


class SheetFromExtraction(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: str = Field(default="general", max_length=60)
    columns: list[ColumnIn] = Field(min_length=1, max_length=100)
    records: list[ExtractedRowIn] = Field(max_length=500)
    source_type: Literal["image", "url", "text", "ai_assistant"] = "text"
    source_url: str | None = Field(default=None, max_length=2048)
    source_file_id: UUID | None = None


# ---------- Phase 4: smart save ----------
class ExtractedColumnIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: ColumnType = "text"


class ExtractionIn(BaseModel):
    """The (possibly user-edited) extraction, as shown in the preview."""
    category: str = Field(default="general", max_length=60)
    columns: list[ExtractedColumnIn] = Field(max_length=100)
    records: list[ExtractedRowIn] = Field(max_length=500)


class MatchRequest(BaseModel):
    sheet_id: UUID
    extraction: ExtractionIn
    use_ai: bool = True


class ColumnAction(BaseModel):
    action: Literal["map", "create", "skip"]
    column_id: str | None = None  # for "map"
    type: ColumnType | None = None  # for "create" (defaults to the extracted type)


class BulkAddRequest(BaseModel):
    columns: list[ExtractedColumnIn] = Field(max_length=100)  # extracted columns (name + type)
    mapping: dict[str, ColumnAction]  # keyed by extracted column name
    records: list[ExtractedRowIn] = Field(min_length=1, max_length=500)
    source_type: Literal["image", "url", "text", "ai_assistant"] = "text"
    source_url: str | None = Field(default=None, max_length=2048)
    source_file_id: UUID | None = None


class DuplicateCheckRequest(BaseModel):
    columns: list[ExtractedColumnIn] = Field(max_length=100)
    mapping: dict[str, ColumnAction]
    records: list[ExtractedRowIn] = Field(min_length=1, max_length=500)


class MergeRequest(BaseModel):
    source_sheet_id: UUID
    add_missing_columns: bool = False
    trash_source: bool = False
