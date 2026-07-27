import calendar
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo
import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import Article, ArticleVersion, Asset, Citation, EventCluster, FeedItem, PublishAttempt, Source, WorkflowSettings
from .services import ingest


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
AI_KEYWORDS = (" ai ", "artificial intelligence", "llm", "gpt", "claude", "gemini", "agent", "machine learning", "openai", "anthropic", "hugging face")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _in_recent_date_window(value):
    if not value:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local_date = value.astimezone(SHANGHAI_TZ).date()
    today = datetime.now(SHANGHAI_TZ).date()
    return local_date in {today, today - timedelta(days=1)}


def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _feed_date(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc) if parsed else None


def _save(db: Session, source: str, title: str, url: str, summary="", author="", published_at=None):
    item = ingest(db, SimpleNamespace(source=source, title=title.strip(), url=url, summary=summary or "", author=(author or "")[:200], published_at=published_at))
    return item.id


def _extract_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    published = None
    for attrs in ({"property": "article:published_time"}, {"name": "date"}, {"name": "datePublished"}):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            published = _dt(node["content"])
            if published:
                break
    if not published:
        node = soup.find("time", datetime=True)
        published = _dt(node.get("datetime")) if node else None
    for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body
    lines, seen = [], set()
    for line in (root.get_text("\n", strip=True) if root else "").splitlines():
        line = " ".join(line.split())
        if len(line) >= 20 and line not in seen:
            lines.append(line); seen.add(line)
    return "\n".join(lines)[:30000], published


def enrich_item(db: Session, item: FeedItem, client: httpx.Client):
    if not item.source.official or not item.url.startswith(("https://", "http://")):
        return item
    raw = dict(item.raw or {})
    try:
        response = client.get(item.url)
        if response.status_code == 403:
            raw.update({"body_status": "restricted", "body_error": "官方页面拒绝自动读取（HTTP 403）；保留 RSS 证据，不绕过访问限制。", "body_fetched_at": datetime.now(timezone.utc).isoformat()})
            item.raw = raw; db.commit(); db.refresh(item); return item
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            raw.update({"body_status": "unsupported", "body_content_type": response.headers.get("content-type", "")})
        else:
            body, published = _extract_page(response.text)
            raw.update({"body_status": "ok" if body else "empty", "body_text": body, "body_length": len(body), "body_fetched_at": datetime.now(timezone.utc).isoformat(), "body_fetch_method": "httpx"})
            if published and not item.published_at:
                item.published_at = published
    except Exception as exc:
        raw.update({"body_status": "error", "body_error": str(exc)[:500], "body_fetched_at": datetime.now(timezone.utc).isoformat()})
    item.raw = raw
    db.commit(); db.refresh(item)
    return item


def refresh_event_items(db: Session, event_id: int):
    items = db.scalars(select(FeedItem).where(FeedItem.event_id == event_id)).all()
    with httpx.Client(timeout=45, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        for item in items:
            enrich_item(db, item, client)
    return items


def prune_feed_items(db: Session, per_source: int = 5):
    removed, affected_events = 0, set()
    for source in db.scalars(select(Source)).all():
        if source.kind == "website_import":
            continue
        items = db.scalars(select(FeedItem).where(FeedItem.source_id == source.id).order_by(FeedItem.published_at.desc().nullslast(), FeedItem.id.desc())).all()
        eligible = [item for item in items if _in_recent_date_window(item.published_at)]
        keep = {item.id for item in eligible[:per_source]}
        for item in items:
            if item.id in keep:
                continue
            if item.event_id: affected_events.add(item.event_id)
            db.query(Citation).filter(Citation.feed_item_id == item.id).delete(synchronize_session=False)
            db.delete(item); removed += 1
    db.flush()
    for event_id in affected_events:
        if db.scalar(select(func.count()).select_from(FeedItem).where(FeedItem.event_id == event_id)):
            continue
        article = db.scalar(select(Article).where(Article.event_id == event_id))
        if article:
            db.query(Citation).filter(Citation.article_id == article.id).delete(synchronize_session=False)
            db.query(PublishAttempt).filter(PublishAttempt.article_id == article.id).delete(synchronize_session=False)
            db.query(Asset).filter(Asset.article_id == article.id).delete(synchronize_session=False)
            db.query(ArticleVersion).filter(ArticleVersion.article_id == article.id).delete(synchronize_session=False)
            db.delete(article); db.flush()
        event = db.get(EventCluster, event_id)
        if event: db.delete(event)
    db.commit()
    return removed


def collect_rss(db: Session, client: httpx.Client, source: str, url: str, limit=5):
    response = client.get(url)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    ids = []
    for entry in feed.entries:
        link, title = entry.get("link"), entry.get("title")
        published_at = _feed_date(entry)
        if link and title and _in_recent_date_window(published_at):
            item_id = _save(db, source, title, link, entry.get("summary", "")[:3000], entry.get("author", ""), published_at)
            item = db.get(FeedItem, item_id)
            if item and item.source.official:
                enrich_item(db, item, client)
            ids.append(item_id)
            if len(ids) >= limit:
                break
    return ids


def collect_anthropic(db: Session, client: httpx.Client, url: str, limit=5):
    response = client.get(url)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    rows = []
    for node in root.findall("{*}url"):
        loc = node.findtext("{*}loc", "")
        if "/news/" not in loc:
            continue
        lastmod = _dt(node.findtext("{*}lastmod", ""))
        slug = urlparse(loc).path.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").strip().title()
        rows.append((lastmod or datetime.min.replace(tzinfo=timezone.utc), title, loc))
    rows.sort(reverse=True)
    return [_save(db, "Anthropic News", title, loc, "Anthropic 官方新闻页面", published_at=lastmod) for lastmod, title, loc in rows if _in_recent_date_window(lastmod)][:limit]


def collect_hacker_news(db: Session, client: httpx.Client, url: str, limit=5):
    base = url.rstrip("/")
    ids, matches = client.get(f"{base}/topstories.json").json(), []
    for story_id in ids[:80]:
        story = client.get(f"{base}/item/{story_id}.json").json()
        title = (story or {}).get("title", "")
        haystack = f" {title.lower()} "
        published_at = datetime.fromtimestamp(story["time"], timezone.utc) if (story or {}).get("time") else None
        if title and _in_recent_date_window(published_at) and any(keyword in haystack for keyword in AI_KEYWORDS):
            matches.append(story)
        if len(matches) >= limit:
            break
    return [_save(db, "Hacker News", story["title"], story.get("url") or f"https://news.ycombinator.com/item?id={story['id']}", f"Hacker News 热度：{story.get('score', 0)}", story.get("by", ""), datetime.fromtimestamp(story["time"], timezone.utc) if story.get("time") else None) for story in matches]


def collect_github(db: Session, client: httpx.Client, url: str, limit=5):
    params = {"q": "topic:llm stars:>100", "sort": "updated", "order": "desc", "per_page": 30}
    response = client.get(f"{url.rstrip('/')}/search/repositories", params=params, headers={"Accept": "application/vnd.github+json"})
    response.raise_for_status()
    recent = [repo for repo in response.json().get("items", []) if _in_recent_date_window(_dt(repo.get("pushed_at")))]
    return [_save(db, "GitHub", repo["full_name"], repo["html_url"], (repo.get("description") or "")[:3000], repo["owner"]["login"], _dt(repo.get("pushed_at"))) for repo in recent[:limit]]


def collect_all(db: Session):
    setting = db.scalar(select(WorkflowSettings).where(WorkflowSettings.workflow_number == 1))
    limit = max(1, min(int((setting.config or {}).get("item_limit", 5)) if setting else 5, 20))
    sources = {source.name: source for source in db.scalars(select(Source)).all()}
    jobs = []
    for source in sources.values():
        if source.name == "Anthropic News":
            job = lambda c, s=source: collect_anthropic(db, c, s.url, limit)
        elif source.name == "Hacker News":
            job = lambda c, s=source: collect_hacker_news(db, c, s.url, limit)
        elif source.name == "GitHub":
            job = lambda c, s=source: collect_github(db, c, s.url, limit)
        elif source.kind == "rss":
            job = lambda c, s=source: collect_rss(db, c, s.name, s.url, limit)
        else:
            continue
        jobs.append((source.name, job))
    results, errors = {}, {}
    with httpx.Client(timeout=30, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        for name, job in jobs:
            source = db.scalar(select(Source).where(Source.name == name))
            if source and not source.enabled:
                results[name] = {"status": "disabled", "count": 0}
                continue
            try:
                ids = job(client)
                results[name] = {"status": "ok", "count": len(ids), "item_ids": ids}
                if source:
                    source.health = "ok"; source.last_checked_at = datetime.now(timezone.utc); db.commit()
            except Exception as exc:
                db.rollback()
                errors[name] = str(exc)
                results[name] = {"status": "error", "count": 0}
                source = db.scalar(select(Source).where(Source.name == name))
                if source:
                    source.health = "error"; source.last_checked_at = datetime.now(timezone.utc); db.commit()
    removed = prune_feed_items(db, per_source=limit)
    return {"sources": results, "errors": errors, "ok": not errors, "pruned": removed, "item_limit": limit}
