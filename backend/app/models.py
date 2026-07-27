import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def now():
    return datetime.now(timezone.utc)


class ArticleStatus(str, enum.Enum):
    pending = "待审核"
    editing = "编辑中"
    approved = "已批准"
    exported = "已导出"
    uploaded = "草稿已上传"
    failed = "失败"


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="rss")
    url: Mapped[str] = mapped_column(Text)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health: Mapped[str] = mapped_column(String(30), default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (UniqueConstraint("normalized_url", name="uq_item_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("event_clusters.id", ondelete="CASCADE"), nullable=True)
    source: Mapped[Source] = relationship()


class EventCluster(Base):
    __tablename__ = "event_clusters"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_title: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(40), default="行业动态")
    primary_item_id: Mapped[int | None] = mapped_column(nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Article(Base):
    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event_clusters.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_options: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[ArticleStatus] = mapped_column(Enum(ArticleStatus), default=ArticleStatus.pending)
    risk_notes: Mapped[list] = mapped_column(JSON, default=list)
    originality_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    versions: Mapped[list["ArticleVersion"]] = relationship(cascade="all, delete-orphan")


class ArticleVersion(Base):
    __tablename__ = "article_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    path: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Citation(Base):
    __tablename__ = "citations"
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    feed_item_id: Mapped[int] = mapped_column(ForeignKey("feed_items.id", ondelete="CASCADE"))
    claim: Mapped[str] = mapped_column(Text, default="")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowSettings(Base):
    __tablename__ = "workflow_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_number: Mapped[int] = mapped_column(Integer, unique=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BrandSettings(Base):
    __tablename__ = "brand_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    account_name: Mapped[str] = mapped_column(String(100), default="AI 实战前线")
    primary_color: Mapped[str] = mapped_column(String(20), default="#6D5DFC")
    secondary_color: Mapped[str] = mapped_column(String(20), default="#15152B")
    logo_path: Mapped[str] = mapped_column(Text, default="")
    font_name: Mapped[str] = mapped_column(String(100), default="Microsoft YaHei")
