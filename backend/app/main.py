from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
import ipaddress
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import Article, ArticleStatus, ArticleVersion, Asset, BrandSettings, Citation, EventCluster, FeedItem, PublishAttempt, Source, WorkflowRun, WorkflowSettings
from .schemas import ArticleOut, ArticleUpdate, BrandUpdate, IngestItem, SourceCreate, SourceOut, SourceUpdate, WebsiteArticleCreate, WorkflowOneSettingsUpdate
from .services import analyze_event, create_cover, export_package, generate_article, ingest, restore_version, save_version, wechat_draft
from .collectors import collect_all, enrich_item, refresh_event_items, DEFAULT_HEADERS
from .publication import generate_wechat_publication
from .website_import import (
    MAX_UPLOAD_BYTES,
    WEBSITE_IMPORT_SOURCE_KIND,
    WebsiteImportError,
    create_article_from_file,
    create_article_from_website,
)
import httpx

def initialize_database():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        defaults = [
            ("OpenAI News", "rss", "https://openai.com/news/rss.xml", True),
            ("Anthropic News", "sitemap", "https://www.anthropic.com/sitemap.xml", True),
            ("Hugging Face Blog", "rss", "https://huggingface.co/blog/feed.xml", True),
            ("Hacker News", "api", "https://hacker-news.firebaseio.com/v0", False),
            ("arXiv AI", "rss", "https://export.arxiv.org/rss/cs.AI", True),
            ("GitHub", "api", "https://api.github.com", False),
        ]
        for name, kind, url, official in defaults:
            if not db.scalar(select(Source).where(Source.name == name)): db.add(Source(name=name, kind=kind, url=url, official=official))
        legacy_sources = db.scalars(select(Source).where(Source.kind.in_(["website", WEBSITE_IMPORT_SOURCE_KIND]))).all()
        for legacy_source in legacy_sources:
            db.query(FeedItem).filter(FeedItem.source_id == legacy_source.id).delete(synchronize_session=False)
            db.delete(legacy_source)
        if not db.get(BrandSettings, 1): db.add(BrandSettings(id=1))
        if not db.scalar(select(WorkflowSettings).where(WorkflowSettings.workflow_number == 1)):
            db.add(WorkflowSettings(workflow_number=1, config={"item_limit": 5}))
        db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="AI公众号自动生产系统", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:8080"], allow_methods=["*"], allow_headers=["*"])
settings.export_dir.mkdir(parents=True, exist_ok=True)
app.mount("/generated", StaticFiles(directory=settings.export_dir), name="generated")


def auth():
    return None


def internal(x_internal_api_key: str = Header(default="")):
    if x_internal_api_key != settings.internal_api_key:
        raise HTTPException(401, "内部密钥错误")


@app.get("/api/health")
def health(): return {"status": "ok", "wechat_mode": settings.wechat_mode, "openai_configured": bool(settings.openai_api_key)}


@app.get("/api/sources", response_model=list[SourceOut], dependencies=[Depends(auth)])
def sources(db: Session = Depends(get_db)):
    return db.scalars(select(Source).where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND])).order_by(Source.id)).all()


@app.post("/api/sources", response_model=SourceOut, dependencies=[Depends(auth)])
def source_create(body: SourceCreate, db: Session = Depends(get_db)):
    name = " ".join(body.name.split())
    if db.scalar(select(Source).where(func.lower(Source.name) == name.lower())):
        raise HTTPException(409, "信息源名称已存在")
    source = Source(name=name, kind="rss", url=_safe_source_url(body.url), official=body.official, enabled=True, health="unknown")
    db.add(source); db.commit(); db.refresh(source); return source


@app.patch("/api/sources/{source_id}", response_model=SourceOut, dependencies=[Depends(auth)])
def source_update(source_id: int, body: SourceUpdate, db: Session = Depends(get_db)):
    obj = db.get(Source, source_id) or (_ for _ in ()).throw(HTTPException(404, "来源不存在"))
    if body.enabled is not None: obj.enabled = body.enabled
    if body.url is not None: obj.url = _safe_source_url(body.url)
    db.commit(); db.refresh(obj); return obj


def _safe_source_url(value: str):
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "信息源地址必须是有效的 HTTP/HTTPS URL")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "postgres", "backend", "n8n", "adminer"} or hostname.endswith(".local"):
        raise HTTPException(400, "信息源地址不能指向本机或内部服务")
    try:
        if ipaddress.ip_address(hostname).is_private:
            raise HTTPException(400, "信息源地址不能使用私有 IP")
    except ValueError:
        pass
    return value


@app.get("/api/workflows/1/settings", dependencies=[Depends(auth)])
def workflow_one_settings(db: Session = Depends(get_db)):
    setting = db.scalar(select(WorkflowSettings).where(WorkflowSettings.workflow_number == 1))
    config = setting.config or {}
    return {
        "item_limit": config.get("item_limit", 5),
        "article_limit": config.get("article_limit", 5),
        "sources": db.scalars(
            select(Source).where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND])).order_by(Source.id)
        ).all(),
    }


@app.put("/api/workflows/1/settings", dependencies=[Depends(auth)])
def workflow_one_settings_update(body: WorkflowOneSettingsUpdate, db: Session = Depends(get_db)):
    existing_ids = set(db.scalars(
        select(Source.id).where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
    ).all())
    if {item.id for item in body.sources} != existing_ids:
        raise HTTPException(400, "信息源列表与数据库不一致，请刷新后重试")
    for item in body.sources:
        source = db.get(Source, item.id); source.enabled = item.enabled; source.url = _safe_source_url(item.url)
    setting = db.scalar(select(WorkflowSettings).where(WorkflowSettings.workflow_number == 1))
    if not setting: setting = WorkflowSettings(workflow_number=1, config={}); db.add(setting)
    setting.config = {"item_limit": body.item_limit, "article_limit": body.article_limit}
    db.commit()
    return workflow_one_settings(db)


@app.get("/api/items", dependencies=[Depends(auth)])
def items(db: Session = Depends(get_db)): return db.scalars(select(FeedItem).order_by(FeedItem.collected_at.desc()).limit(200)).all()


@app.post("/api/items/ingest", dependencies=[Depends(internal)])
def item_ingest(body: IngestItem, db: Session = Depends(get_db)): return {"id": ingest(db, body).id}


@app.post("/api/items/{item_id}/refresh", dependencies=[Depends(internal)])
def item_refresh(item_id: int, db: Session = Depends(get_db)):
    item = db.get(FeedItem, item_id) or (_ for _ in ()).throw(HTTPException(404, "资讯不存在"))
    with httpx.Client(timeout=45, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        enrich_item(db, item, client)
    return {"id": item.id, "body_status": item.raw.get("body_status"), "body_length": item.raw.get("body_length", 0), "published_at": item.published_at}


@app.post("/api/events/{event_id}/refresh", dependencies=[Depends(internal)])
def event_refresh(event_id: int, db: Session = Depends(get_db)):
    if not db.get(EventCluster, event_id): raise HTTPException(404, "事件不存在")
    items = refresh_event_items(db, event_id)
    return {"event_id": event_id, "items": [{"id": i.id, "body_status": i.raw.get("body_status"), "body_length": i.raw.get("body_length", 0)} for i in items]}


@app.post("/api/collect/all", dependencies=[Depends(internal)])
def collect_every_source(db: Session = Depends(get_db)):
    return collect_all(db)


@app.get("/api/events", dependencies=[Depends(auth)])
def events(today: bool = False, db: Session = Depends(get_db)):
    query = select(EventCluster)
    if today:
        tz = ZoneInfo("Asia/Shanghai")
        start = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
        end = start + timedelta(days=1)
        query = query.join(FeedItem, EventCluster.primary_item_id == FeedItem.id).where(
            FeedItem.published_at >= start,
            FeedItem.published_at < end,
        )
    return db.scalars(query.order_by(EventCluster.score.desc(), EventCluster.created_at.desc()).limit(200)).all()


@app.post("/api/events/{event_id}/analyze", dependencies=[Depends(internal)])
def event_analyze(event_id: int, db: Session = Depends(get_db)):
    event = db.get(EventCluster, event_id) or (_ for _ in ()).throw(HTTPException(404, "事件不存在")); return analyze_event(db, event)


@app.post("/api/events/{event_id}/article", dependencies=[Depends(internal)])
def event_article(event_id: int, db: Session = Depends(get_db)):
    event = db.get(EventCluster, event_id) or (_ for _ in ()).throw(HTTPException(404, "事件不存在")); article = generate_article(db, event); return {"article_id": article.id if article else None, "blocked": article is None}


@app.post("/api/events/{event_id}/article/regenerate", dependencies=[Depends(internal)])
def event_article_regenerate(event_id: int, db: Session = Depends(get_db)):
    event = db.get(EventCluster, event_id) or (_ for _ in ()).throw(HTTPException(404, "事件不存在"))
    article = generate_article(db, event, force=True)
    return {"article_id": article.id if article else None, "blocked": article is None}


@app.get("/api/articles", response_model=list[ArticleOut], dependencies=[Depends(auth)])
def articles(db: Session = Depends(get_db)): return db.scalars(select(Article).order_by(Article.updated_at.desc())).all()


@app.post("/api/articles/from-website", dependencies=[Depends(auth)])
def article_from_website(body: WebsiteArticleCreate, db: Session = Depends(get_db)):
    try:
        article, reused = create_article_from_website(db, body.url, body.preserve_images)
    except WebsiteImportError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    except httpx.HTTPError as exc:
        db.rollback()
        raise HTTPException(409, f"网站读取失败：{str(exc)[:300]}")
    return {"article_id": article.id, "title": article.title, "status": article.status.value, "reused": reused}


@app.post("/api/articles/from-file", dependencies=[Depends(auth)])
async def article_from_file(
    file: UploadFile = File(...),
    preserve_images: bool = Form(False),
    db: Session = Depends(get_db),
):
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        article, reused = create_article_from_file(db, file.filename or "上传文件.txt", data, preserve_images)
    except WebsiteImportError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    finally:
        await file.close()
    return {"article_id": article.id, "title": article.title, "status": article.status.value, "reused": reused}


@app.get("/api/articles/{article_id}", response_model=ArticleOut, dependencies=[Depends(auth)])
def article(article_id: int, db: Session = Depends(get_db)): return db.get(Article, article_id) or (_ for _ in ()).throw(HTTPException(404, "文章不存在"))


@app.patch("/api/articles/{article_id}", response_model=ArticleOut, dependencies=[Depends(auth)])
def article_update(article_id: int, body: ArticleUpdate, db: Session = Depends(get_db)):
    obj = db.get(Article, article_id) or (_ for _ in ()).throw(HTTPException(404, "文章不存在")); save_version(db, obj)
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(obj, key, value)
    db.commit(); db.refresh(obj); return obj


@app.delete("/api/articles/{article_id}", dependencies=[Depends(auth)])
def article_delete(article_id: int, db: Session = Depends(get_db)):
    obj = db.get(Article, article_id) or (_ for _ in ()).throw(HTTPException(404, "文章不存在"))
    db.delete(obj)
    db.commit()
    return {"ok": True, "article_id": article_id}


@app.get("/api/articles/{article_id}/versions", dependencies=[Depends(auth)])
def versions(article_id: int, db: Session = Depends(get_db)): return db.scalars(select(ArticleVersion).where(ArticleVersion.article_id == article_id).order_by(ArticleVersion.version.desc())).all()


@app.post("/api/articles/{article_id}/versions/{version_id}/restore", dependencies=[Depends(auth)])
def version_restore(article_id: int, version_id: int, db: Session = Depends(get_db)):
    obj, version = db.get(Article, article_id), db.get(ArticleVersion, version_id)
    if not obj or not version or version.article_id != article_id: raise HTTPException(404, "版本不存在")
    restore_version(db, obj, version); return {"ok": True}


@app.post("/api/articles/{article_id}/cover", dependencies=[Depends(auth)])
def cover(article_id: int, db: Session = Depends(get_db)):
    raise HTTPException(409, "封面生成功能已停用")


@app.get("/api/assets", dependencies=[Depends(auth)])
def assets(db: Session = Depends(get_db)): return db.scalars(select(Asset).order_by(Asset.created_at.desc())).all()


@app.post("/api/exports/{article_id}", dependencies=[Depends(auth)])
def export(article_id: int, db: Session = Depends(get_db)):
    obj = db.get(Article, article_id) or (_ for _ in ()).throw(HTTPException(404, "文章不存在"))
    try: path = export_package(db, obj)
    except ValueError as exc: raise HTTPException(409, str(exc))
    return FileResponse(path, filename="article.md", media_type="text/markdown; charset=utf-8")


@app.post("/api/wechat/drafts/{article_id}", dependencies=[Depends(auth)])
def draft(article_id: int, idempotency_key: str = Header(default=""), db: Session = Depends(get_db)):
    if not idempotency_key: raise HTTPException(400, "缺少 Idempotency-Key")
    obj = db.get(Article, article_id) or (_ for _ in ()).throw(HTTPException(404, "文章不存在")); return wechat_draft(db, obj, idempotency_key)


@app.get("/api/settings", dependencies=[Depends(auth)])
def get_settings(db: Session = Depends(get_db)): return db.get(BrandSettings, 1)


@app.patch("/api/settings", dependencies=[Depends(auth)])
def update_settings(body: BrandUpdate, db: Session = Depends(get_db)):
    obj = db.get(BrandSettings, 1)
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(obj, key, value)
    db.commit(); return obj


@app.get("/api/runs", dependencies=[Depends(auth)])
def runs(db: Session = Depends(get_db)): return db.scalars(select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(100)).all()


DATABASE_TABLES = {
    "sources": Source, "feed_items": FeedItem, "event_clusters": EventCluster,
    "articles": Article, "article_versions": ArticleVersion, "citations": Citation,
    "assets": Asset, "workflow_runs": WorkflowRun, "publish_attempts": PublishAttempt,
    "workflow_settings": WorkflowSettings,
}


def _row_dict(row):
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        result[column.name] = value.value if hasattr(value, "value") else value
    return result


@app.get("/api/database/summary", dependencies=[Depends(auth)])
def database_summary(db: Session = Depends(get_db)):
    result = {name: db.scalar(select(func.count()).select_from(model)) for name, model in DATABASE_TABLES.items()}
    result["sources"] = db.scalar(
        select(func.count()).select_from(Source).where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
    )
    result["feed_items"] = db.scalar(
        select(func.count()).select_from(FeedItem).join(Source, FeedItem.source_id == Source.id)
        .where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
    )
    return result


@app.get("/api/database/{table_name}", dependencies=[Depends(auth)])
def database_rows(table_name: str, page: int = 1, page_size: int = 10,
                  sort_by: str = "id", sort_order: str = "desc", db: Session = Depends(get_db)):
    model = DATABASE_TABLES.get(table_name)
    if not model: raise HTTPException(404, "不支持的数据表")
    page, page_size = max(1, page), max(1, min(page_size, 100))
    allowed_sort_fields = {column.name for column in model.__table__.columns}
    if sort_by not in allowed_sort_fields: raise HTTPException(400, "不支持的排序字段")
    if sort_order not in {"asc", "desc"}: raise HTTPException(400, "不支持的排序方式")
    sort_column = getattr(model, sort_by)
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    query = select(model)
    count_query = select(func.count()).select_from(model)
    if model is Source:
        query = query.where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
        count_query = count_query.where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
    elif model is FeedItem:
        query = query.join(Source, FeedItem.source_id == Source.id).where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
        count_query = count_query.join(Source, FeedItem.source_id == Source.id).where(Source.kind.notin_(["website", WEBSITE_IMPORT_SOURCE_KIND]))
    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(ordering, model.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_row_dict(row) for row in rows], "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}


def _editable_values(model, body: dict):
    values = {}
    for column in model.__table__.columns:
        if column.primary_key or column.name not in body or column.name in {"created_at", "updated_at", "collected_at", "started_at", "finished_at"}:
            continue
        value = body[column.name]
        if value in ("", None) and column.nullable:
            values[column.name] = None; continue
        enum_class = getattr(column.type, "enum_class", None)
        if enum_class and not isinstance(value, enum_class):
            value = enum_class(value)
        elif "DATETIME" in column.type.__class__.__name__.upper() and isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif "JSON" in column.type.__class__.__name__.upper() and isinstance(value, str):
            value = __import__("json").loads(value)
        elif "BOOLEAN" in column.type.__class__.__name__.upper() and isinstance(value, str):
            value = value.lower() in {"true", "1", "yes", "on"}
        elif "INTEGER" in column.type.__class__.__name__.upper() and isinstance(value, str):
            value = int(value)
        elif "FLOAT" in column.type.__class__.__name__.upper() and isinstance(value, str):
            value = float(value)
        values[column.name] = value
    return values


@app.get("/api/database/{table_name}/schema", dependencies=[Depends(auth)])
def database_schema(table_name: str):
    model = DATABASE_TABLES.get(table_name)
    if not model: raise HTTPException(404, "不支持的数据表")
    system_fields = {"id", "created_at", "updated_at", "collected_at", "started_at", "finished_at"}
    return [{
        "name": column.name,
        "type": column.type.__class__.__name__.lower(),
        "nullable": column.nullable,
        "required": not column.nullable and column.default is None and column.server_default is None,
        "editable": not column.primary_key and column.name not in system_fields,
        "enum": [item.value for item in column.type.enum_class] if getattr(column.type, "enum_class", None) else [],
    } for column in model.__table__.columns]


@app.post("/api/database/{table_name}", dependencies=[Depends(auth)])
def database_create(table_name: str, body: dict, db: Session = Depends(get_db)):
    model = DATABASE_TABLES.get(table_name)
    if not model: raise HTTPException(404, "不支持的数据表")
    try:
        row = model(**_editable_values(model, body)); db.add(row); db.commit(); db.refresh(row); return _row_dict(row)
    except (IntegrityError, StatementError, ValueError, TypeError) as exc:
        db.rollback(); raise HTTPException(400, f"新增失败：{str(exc.orig if hasattr(exc, 'orig') else exc)[:500]}")


@app.patch("/api/database/{table_name}/{row_id}", dependencies=[Depends(auth)])
def database_update(table_name: str, row_id: int, body: dict, db: Session = Depends(get_db)):
    model = DATABASE_TABLES.get(table_name)
    if not model: raise HTTPException(404, "不支持的数据表")
    row = db.get(model, row_id)
    if not row: raise HTTPException(404, "记录不存在")
    try:
        for key, value in _editable_values(model, body).items(): setattr(row, key, value)
        db.commit(); db.refresh(row); return _row_dict(row)
    except (IntegrityError, StatementError, ValueError, TypeError) as exc:
        db.rollback(); raise HTTPException(400, f"修改失败：{str(exc.orig if hasattr(exc, 'orig') else exc)[:500]}")


@app.delete("/api/database/{table_name}/{row_id}", dependencies=[Depends(auth)])
def database_delete(table_name: str, row_id: int, db: Session = Depends(get_db)):
    model = DATABASE_TABLES.get(table_name)
    if not model: raise HTTPException(404, "不支持的数据表")
    row = db.get(model, row_id)
    if not row: raise HTTPException(404, "记录不存在")
    try:
        db.delete(row); db.commit(); return {"ok": True, "id": row_id}
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, f"删除失败：{str(exc.orig)[:500]}")


def _choose_articles(db: Session):
    tz = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    events = db.scalars(
        select(EventCluster)
        .join(FeedItem, EventCluster.primary_item_id == FeedItem.id)
        .where(FeedItem.published_at >= start, FeedItem.published_at < end)
        .order_by(EventCluster.score.desc())
    ).all()
    events = [event for event in events if event.analysis]
    setting = db.scalar(select(WorkflowSettings).where(WorkflowSettings.workflow_number == 1))
    article_limit = max(1, min(int((setting.config or {}).get("article_limit", 5)) if setting else 5, 5))
    chosen, topics = [], set()
    for event in sorted(events, key=lambda x: x.score, reverse=True):
        if event.score >= 7 and not event.needs_review and event.topic not in topics:
            article = generate_article(db, event)
            if article: chosen.append(article.id); topics.add(event.topic)
        if len(chosen) == article_limit: break
    return chosen


def _score_today(db: Session):
    tz = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    events = db.scalars(
        select(EventCluster)
        .join(FeedItem, EventCluster.primary_item_id == FeedItem.id)
        .where(FeedItem.published_at >= start, FeedItem.published_at < end)
        .order_by(EventCluster.created_at.desc())
    ).all()
    successful_events, failures = [], []
    for event in events:
        try:
            analyze_event(db, event)
            successful_events.append(event)
        except Exception as exc:
            db.rollback()
            failures.append({"event_id": event.id, "title": event.canonical_title, "error": str(exc)[:500]})
    rankings = [
        {"rank": index, "event_id": event.id, "title": event.canonical_title,
         "topic": event.topic, "score": event.score, "needs_review": event.needs_review}
        for index, event in enumerate(sorted(successful_events, key=lambda item: (-item.score, item.id)), start=1)
    ]
    return {
        "date": start.date().isoformat(), "total_count": len(events), "count": len(rankings),
        "success_count": len(successful_events), "failure_count": len(failures),
        "event_ids": [item["event_id"] for item in rankings], "rankings": rankings,
        "failures": failures,
    }


def _background_workflow(number: int, run_id: int):
    with SessionLocal() as db:
        run = db.get(WorkflowRun, run_id)
        try:
            result_status = "success"
            if number == 1:
                collection = collect_all(db)
                scoring = _score_today(db)
                ids = _choose_articles(db)
                selection = {
                    "date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                    "count": len(ids), "article_ids": ids,
                    "note": "仅从今天已成功评分的事件中选题，未评分或评分失败事件已跳过",
                }
                details = {
                    "date": scoring["date"],
                    "collection": collection,
                    "scoring": scoring,
                    "selection": selection,
                    "rankings": scoring["rankings"],
                    "article_ids": ids,
                    "count": len(ids),
                }
                has_success = bool(scoring["success_count"] or ids or collection.get("ok"))
                has_failure = bool(collection.get("errors") or scoring["failures"])
                if has_failure:
                    result_status = "partial_success" if has_success else "failed"
            elif number == 4:
                approved_statuses = [ArticleStatus.approved, ArticleStatus.exported]
                articles = db.scalars(
                    select(Article).where(Article.status.in_(approved_statuses)).order_by(Article.updated_at.desc())
                ).all()
                publications, failures = [], []
                for article in articles:
                    try:
                        publications.append(generate_wechat_publication(db, article))
                    except Exception as exc:
                        db.rollback()
                        failures.append({"article_id": article.id, "title": article.title, "error": str(exc)[:500]})
                details = {"count": len(publications), "failure_count": len(failures),
                           "publications": publications, "failures": failures}
                if failures:
                    result_status = "partial_success" if publications else "failed"
            else:
                failed = db.scalars(select(WorkflowRun).where(WorkflowRun.status.in_(["failed", "partial_success"])).order_by(WorkflowRun.started_at.desc()).limit(50)).all()
                details = {"count": len(failed), "failed_run_ids": [item.id for item in failed]}
            run.status, run.details = result_status, details
        except Exception as exc:
            db.rollback(); run = db.get(WorkflowRun, run_id)
            run.status, run.details = "failed", {"error": str(exc)[:1000]}
        run.finished_at = datetime.now(ZoneInfo("UTC")); db.commit()


@app.post("/api/workflows/{number}/run", dependencies=[Depends(auth)])
def workflow_run(number: int, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    names = {1: "01 资讯到候选稿", 4: "04 公众号成品生成", 5: "05 失败检查"}
    if number not in names: raise HTTPException(404, "工作流不存在")
    running = db.scalar(select(WorkflowRun).where(WorkflowRun.name == names[number], WorkflowRun.status == "running"))
    if running: return {"run_id": running.id, "status": "running", "already_running": True}
    run = WorkflowRun(name=names[number], status="running", details={})
    db.add(run); db.commit(); db.refresh(run)
    tasks.add_task(_background_workflow, number, run.id)
    return {"run_id": run.id, "status": "running", "already_running": False}


@app.post("/api/pipeline/daily", dependencies=[Depends(internal)])
def daily_pipeline(db: Session = Depends(get_db)):
    run = WorkflowRun(name="每日选题成稿", status="running", details={})
    db.add(run); db.commit()
    chosen = _choose_articles(db)
    run.status = "success"; run.details = {"article_ids": chosen, "count": len(chosen)}
    from datetime import datetime, timezone
    run.finished_at = datetime.now(timezone.utc); db.commit()
    return run.details
