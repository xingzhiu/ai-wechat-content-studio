from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from .models import ArticleStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceOut(ORMModel):
    id: int
    name: str
    kind: str
    url: str
    official: bool
    enabled: bool
    health: str


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    url: str | None = None


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    url: str
    official: bool = False


class WorkflowSourceUpdate(BaseModel):
    id: int
    enabled: bool
    url: str


class WorkflowOneSettingsUpdate(BaseModel):
    item_limit: int = Field(ge=1, le=20)
    article_limit: int = Field(default=5, ge=1, le=5)
    sources: list[WorkflowSourceUpdate]


class ArticleOut(ORMModel):
    id: int
    event_id: int
    title: str
    title_options: list[str]
    content: dict[str, Any]
    status: ArticleStatus
    risk_notes: list[str]
    originality_notes: str
    created_at: datetime
    updated_at: datetime


class ArticleUpdate(BaseModel):
    title: str | None = None
    content: dict[str, Any] | None = None
    status: ArticleStatus | None = None
    originality_notes: str | None = None


class IngestItem(BaseModel):
    source: str
    title: str
    url: str
    summary: str = ""
    author: str = ""
    published_at: datetime | None = None


class WebsiteArticleCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    preserve_images: bool = False


class BrandUpdate(BaseModel):
    account_name: str | None = None
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    font_name: str | None = None
