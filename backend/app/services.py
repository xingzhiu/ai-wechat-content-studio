import base64
import hashlib
import io
import json
import re
import shutil
import time
import zipfile
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import httpx
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .config import settings
from .models import Article, ArticleStatus, ArticleVersion, Asset, BrandSettings, Citation, EventCluster, FeedItem, PublishAttempt, Source


TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"}


class ModelOutputError(RuntimeError):
    pass


def parse_model_json(response) -> dict:
    raw = (getattr(response, "output_text", "") or "").strip()
    if not raw:
        output_types = [getattr(item, "type", "unknown") for item in (getattr(response, "output", None) or [])]
        status = getattr(response, "status", None) or "unknown"
        raise ModelOutputError(f"模型返回空文本（status={status}, output_types={output_types}）")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelOutputError(f"模型返回非 JSON 内容：{raw[:160]}") from exc
    if not isinstance(value, dict):
        raise ModelOutputError("模型返回的 JSON 顶层不是对象")
    return value


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_KEYS))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def title_tokens(title: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", title.lower()))


def similarity(a: str, b: str) -> float:
    x, y = title_tokens(a), title_tokens(b)
    return len(x & y) / max(1, len(x | y))


def cluster_item(db: Session, item: FeedItem) -> EventCluster:
    candidates = db.scalars(select(EventCluster).order_by(EventCluster.created_at.desc()).limit(200)).all()
    best = max(candidates, key=lambda e: similarity(item.title, e.canonical_title), default=None)
    if best and similarity(item.title, best.canonical_title) >= 0.55:
        item.event_id = best.id
        return best
    event = EventCluster(canonical_title=item.title, primary_item_id=item.id)
    db.add(event)
    db.flush()
    item.event_id = event.id
    return event


def ingest(db: Session, data) -> FeedItem:
    source = db.scalar(select(Source).where(Source.name == data.source))
    if not source:
        source = Source(name=data.source, kind="api", url="", official=False, health="ok")
        db.add(source)
        db.flush()
    normalized = normalize_url(data.url)
    existing = db.scalar(select(FeedItem).where(FeedItem.normalized_url == normalized))
    if existing:
        return existing
    item = FeedItem(source_id=source.id, title=data.title, summary=data.summary, author=data.author,
                    url=data.url, normalized_url=normalized, published_at=data.published_at)
    db.add(item)
    db.flush()
    cluster_item(db, item)
    db.commit()
    db.refresh(item)
    return item


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "enum": ["AI工具", "开源项目", "实战教程", "模型更新", "行业动态"]},
        "scores": {"type": "object", "properties": {k: {"type": "number", "minimum": 0, "maximum": 10} for k in ["timeliness", "usefulness", "impact", "fit", "truth_risk"]}, "required": ["timeliness", "usefulness", "impact", "fit", "truth_risk"], "additionalProperties": False},
        "total_score": {"type": "number", "minimum": 0, "maximum": 10},
        "facts": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "forbidden_claims": {"type": "array", "items": {"type": "string"}},
        "needs_review": {"type": "boolean"}
    },
    "required": ["topic", "scores", "total_score", "facts", "unknowns", "forbidden_claims", "needs_review"],
    "additionalProperties": False
}


def _client() -> OpenAI | None:
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url, timeout=120.0, max_retries=1) if settings.openai_api_key else None


def analyze_event(db: Session, event: EventCluster) -> dict:
    items = db.scalars(select(FeedItem).where(FeedItem.event_id == event.id)).all()
    evidence = [{
        "evidence_id": f"item-{i.id}", "title": i.title, "summary": i.summary[:1500],
        "published_at": i.published_at.isoformat() if i.published_at else None,
        "body": (i.raw or {}).get("body_text", "")[:12000],
        "body_status": (i.raw or {}).get("body_status", "missing"),
        "url": i.url, "official": i.source.official,
    } for i in items]
    client = _client()
    if not client:
        analysis = {"topic": "行业动态", "scores": {"timeliness": 6, "usefulness": 6, "impact": 6, "fit": 7, "truth_risk": 5}, "total_score": 6.2, "facts": [i.title for i in items], "unknowns": ["未配置 OpenAI API，需人工核验"], "forbidden_claims": [], "needs_review": True}
    else:
        last_error = None
        for attempt in range(1, 4):
            try:
                response = client.responses.create(
                    model=settings.openai_text_model,
                    input=[{"role": "system", "content": "你是严谨的中文AI资讯编辑。只能使用提供的证据，不得补充未证实事实。scores 中每一项以及 total_score 都必须使用 0 到 10 的十分制，不得使用 0 到 1 的小数制；truth_risk 越高代表风险越高。needs_review 仅在核心事件无法由证据确认、来源互相冲突、来源身份可疑或证据不足以写出任何安全事实时设为 true。发布日期、价格、规格、开放范围等非核心细节未知时，应写入 unknowns 和 forbidden_claims，但只要官方来源已明确确认事件本身，就将 needs_review 设为 false，并据现有事实写一篇克制的候选稿。"}, {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}],
                    text={"format": {"type": "json_schema", "name": "event_analysis", "schema": ANALYSIS_SCHEMA, "strict": True}},
                    reasoning={"effort": "low"},
                    max_output_tokens=2200,
                )
                analysis = parse_model_json(response)
                break
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2 ** attempt)
        else:
            raise ModelOutputError(f"事件 {event.id} 连续 3 次评分失败：{last_error}") from last_error
    event.topic = analysis["topic"]
    event.score = analysis["total_score"]
    event.needs_review = analysis["needs_review"] or not any(i.source.official for i in items)
    event.analysis = analysis
    db.commit()
    return analysis


def generate_article(db: Session, event: EventCluster, force: bool = False) -> Article | None:
    if event.needs_review or event.score < 7:
        return None
    existing = db.scalar(select(Article).where(Article.event_id == event.id))
    if existing and not force:
        return existing
    items = db.scalars(select(FeedItem).where(FeedItem.event_id == event.id)).all()
    facts = event.analysis.get("facts", [])
    client = _client()
    if client:
        prompt = {"event": event.canonical_title, "topic": event.topic, "facts": facts, "sources": [{"evidence_id": f"item-{i.id}", "title": i.title, "url": i.url, "published_at": i.published_at.isoformat() if i.published_at else None} for i in items], "requirements": "仅输出JSON对象，固定英文键：titles(3个标题数组)、lead、fact_summary(数组，每项含fact、evidence_id、source_url)、value_interpretation、impact_on_general_users、developer_focus(数组)、action_recommendations(数组)、sources(数组)。事实概述必须逐条绑定 evidence_id 和 source_url；数字、日期、型号不得脱离facts。"}
        response = client.responses.create(
            model=settings.openai_text_model,
            input=json.dumps(prompt, ensure_ascii=False),
            text={"format": {"type": "json_object"}},
            reasoning={"effort": "low"},
            max_output_tokens=2200,
        )
        content = json.loads(response.output_text)
    else:
        content = {"titles": [event.canonical_title, f"{event.topic}｜{event.canonical_title}", f"这条 AI 动态值得关注：{event.canonical_title}"], "lead": "这是一篇待人工核验的演示稿。", "facts": facts, "analysis": "请配置 OpenAI API 后重新生成。", "user_impact": "待补充", "developer_notes": "待补充", "actions": ["阅读原始来源", "核验关键信息"]}
    titles = content.get("titles") or content.get("标题") or [event.canonical_title]
    if existing:
        save_version(db, existing)
        article = existing
        article.title, article.title_options, article.content = titles[0], titles[:3], content
        article.risk_notes = event.analysis.get("unknowns", [])
        article.originality_notes = "由官方证据重写；关键事实已附来源，正文不可读取时会明确标注，发布前仍需人工终审。"
    else:
        article = Article(event_id=event.id, title=titles[0], title_options=titles[:3], content=content, risk_notes=event.analysis.get("unknowns", []), originality_notes="由官方证据重写；关键事实已附来源，正文不可读取时会明确标注，发布前仍需人工终审。")
        db.add(article); db.flush(); save_version(db, article)
    db.query(Citation).filter(Citation.article_id == article.id).delete()
    primary = next((i for i in items if i.id == event.primary_item_id), items[0] if items else None)
    if primary:
        for fact in facts:
            claim = fact if isinstance(fact, str) else fact.get("fact", str(fact))
            db.add(Citation(article_id=article.id, feed_item_id=primary.id, claim=claim))
    db.commit()
    db.refresh(article)
    return article


def save_version(db: Session, article: Article):
    version = (db.scalar(select(func.max(ArticleVersion.version)).where(ArticleVersion.article_id == article.id)) or 0) + 1
    snapshot = {"title": article.title, "title_options": article.title_options, "content": article.content, "status": article.status.value, "risk_notes": article.risk_notes, "originality_notes": article.originality_notes}
    db.add(ArticleVersion(article_id=article.id, version=version, snapshot=snapshot))


def restore_version(db: Session, article: Article, version: ArticleVersion):
    save_version(db, article)
    s = version.snapshot
    article.title, article.title_options, article.content = s["title"], s["title_options"], s["content"]
    article.status, article.risk_notes, article.originality_notes = ArticleStatus(s["status"]), s["risk_notes"], s["originality_notes"]
    db.commit()


def _font(size: int):
    for path in ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def create_cover(db: Session, article: Article) -> Asset:
    brand = db.get(BrandSettings, 1) or BrandSettings(id=1)
    if not db.get(BrandSettings, 1): db.add(brand); db.flush()
    canvas = None
    client = _client()
    if client:
        try:
            result = client.images.generate(model=settings.openai_image_model, prompt=f"为中文AI科技公众号生成一张无文字横版封面底图。主题：{article.title}。蓝紫科技杂志风，干净留白，高对比度，禁止出现任何文字、字母、数字、Logo或水印。", size="1536x1024")
            item = result.data[0]
            if item.b64_json:
                canvas = Image.open(io.BytesIO(base64.b64decode(item.b64_json))).convert("RGB")
            elif item.url:
                canvas = Image.open(io.BytesIO(httpx.get(item.url, timeout=30).content)).convert("RGB")
            if canvas:
                canvas = canvas.resize((900, 600)).crop((0, 108, 900, 491))
        except Exception:
            canvas = None
    generated_background = canvas is not None
    if canvas is None:
        canvas = Image.new("RGB", (900, 383), brand.secondary_color)
    draw = ImageDraw.Draw(canvas)
    if not generated_background:
        for x in range(900):
            ratio = x / 900
            base = tuple(int(21 + ratio * v) for v in (35, 18, 90))
            draw.line((x, 0, x, 383), fill=base)
    else:
        overlay = Image.new("RGBA", canvas.size, (8, 8, 28, 105))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((45, 35, 240, 82), 16, fill=brand.primary_color)
    draw.text((65, 44), brand.account_name, font=_font(24), fill="white")
    title = article.title
    lines, current = [], ""
    for ch in title:
        if draw.textlength(current + ch, font=_font(48)) > 760:
            lines.append(current); current = ch
        else: current += ch
    if current: lines.append(current)
    y = 125
    for line in lines[:3]:
        draw.text((65, y), line, font=_font(48), fill="white"); y += 66
    draw.text((65, 335), datetime.now().strftime("%Y.%m.%d  ·  AI 工具 / 开源 / 实战"), font=_font(20), fill="#C9C7FF")
    settings.asset_dir.mkdir(parents=True, exist_ok=True)
    path = settings.asset_dir / f"article-{article.id}-cover.jpg"
    canvas.save(path, quality=92)
    asset = Asset(article_id=article.id, kind="cover", path=str(path), metadata_json={"width": 900, "height": 383})
    db.add(asset); db.commit(); db.refresh(asset)
    return asset


def _article_sections(content: dict):
    facts = content.get("fact_summary") or content.get("facts") or []
    facts = [x.get("fact", "") if isinstance(x, dict) else str(x) for x in facts]
    developer = content.get("developer_focus") or content.get("developer_notes") or []
    actions = content.get("action_recommendations") or content.get("actions") or []
    actions = [x.get("action", "") if isinstance(x, dict) else str(x) for x in actions]
    return [
        ("发生了什么", facts),
        ("为什么重要", content.get("value_interpretation") or content.get("analysis") or ""),
        ("对普通用户的影响", content.get("impact_on_general_users") or content.get("user_impact") or ""),
        ("开发者关注点", developer),
        ("行动建议", actions),
    ]


def article_markdown(article: Article, urls: list[str]) -> str:
    c = article.content
    sections = _article_sections(c)
    out = [f"# {article.title}", "", c.get("lead", ""), ""]
    for heading, value in sections:
        out += [f"## {heading}", ""]
        out += [f"- {x}" for x in value] if isinstance(value, list) else [str(value)]
        out.append("")
    out += ["## 信息来源", ""] + [f"- {u}" for u in urls]
    return "\n".join(out)


def article_html(article: Article, urls: list[str], include_cover: bool = False) -> str:
    def block(value):
        if isinstance(value, list):
            items = "".join(f'<li style="margin:8px 0;line-height:1.8;">{escape(str(x))}</li>' for x in value if x)
            return f'<ul style="padding-left:22px;margin:8px 0 20px;">{items}</ul>'
        return f'<p style="margin:8px 0 20px;line-height:1.9;color:#30303a;">{escape(str(value))}</p>' if value else ""
    cover = '<img src="cover.jpg" alt="封面" style="display:block;width:100%;height:auto;border-radius:10px;margin:0 0 24px;" />' if include_cover else ""
    sections = "".join(f'<h2 style="margin:28px 0 10px;font-size:22px;color:#171725;border-left:4px solid #6d5dfc;padding-left:12px;">{heading}</h2>{block(value)}' for heading, value in _article_sections(article.content))
    sources = "".join(f'<li style="margin:8px 0;word-break:break-all;"><a href="{escape(url, quote=True)}" style="color:#5b4be7;">{escape(url)}</a></li>' for url in urls)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(article.title)}</title></head><body style="margin:0;background:#f5f5f7;"><article style="box-sizing:border-box;max-width:760px;margin:0 auto;padding:32px 28px;background:#fff;font-family:-apple-system,BlinkMacSystemFont,'Microsoft YaHei',sans-serif;color:#252532;">{cover}<h1 style="font-size:30px;line-height:1.35;margin:0 0 20px;color:#11111a;">{escape(article.title)}</h1><p style="font-size:17px;line-height:1.9;color:#4a4a58;margin:0 0 26px;">{escape(str(article.content.get('lead', '')))}</p>{sections}<h2 style="margin:28px 0 10px;font-size:22px;color:#171725;border-left:4px solid #6d5dfc;padding-left:12px;">信息来源</h2><ul style="padding-left:22px;line-height:1.7;">{sources}</ul></article></body></html>'''


def export_package(db: Session, article: Article) -> Path:
    if article.status not in {ArticleStatus.approved, ArticleStatus.exported, ArticleStatus.uploaded}:
        raise ValueError("文章必须先批准")
    items = db.scalars(select(FeedItem).join(EventCluster, FeedItem.event_id == EventCluster.id).where(EventCluster.id == article.event_id)).all()
    urls = [i.url for i in items]
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = settings.export_dir / f"article-{article.id}.md"
    markdown_path.write_text(article_markdown(article, urls), encoding="utf-8")
    article.status = ArticleStatus.exported; db.commit()
    return markdown_path


def wechat_draft(db: Session, article: Article, key: str) -> dict:
    prior = db.scalar(select(PublishAttempt).where(PublishAttempt.idempotency_key == key))
    if prior: return prior.response
    if settings.wechat_mode == "mock" or not (settings.wechat_app_id and settings.wechat_app_secret):
        result = {"mode": "mock", "success": True, "message": "公众号尚未配置，已完成草稿请求模拟", "article_id": article.id}
    else:
        try:
            token = httpx.get("https://api.weixin.qq.com/cgi-bin/token", params={"grant_type": "client_credential", "appid": settings.wechat_app_id, "secret": settings.wechat_app_secret}, timeout=20).json()
            if "access_token" not in token: raise RuntimeError(json.dumps(token, ensure_ascii=False))
            access_token = token["access_token"]
            cover = db.scalar(select(Asset).where(Asset.article_id == article.id, Asset.kind == "cover").order_by(Asset.id.desc())) or create_cover(db, article)
            with open(cover.path, "rb") as fh:
                media = httpx.post("https://api.weixin.qq.com/cgi-bin/material/add_material", params={"access_token": access_token, "type": "thumb"}, files={"media": ("cover.jpg", fh, "image/jpeg")}, timeout=30).json()
            if "media_id" not in media: raise RuntimeError(json.dumps(media, ensure_ascii=False))
            items = db.scalars(select(FeedItem).where(FeedItem.event_id == article.event_id)).all()
            md = article_markdown(article, [i.url for i in items])
            html = article_html(article, [i.url for i in items], include_cover=False)
            payload = {"articles": [{"title": article.title, "author": "AI 实战前线", "digest": article.content.get("lead", "")[:120], "content": html, "content_source_url": items[0].url if items else "", "thumb_media_id": media["media_id"], "need_open_comment": 0, "only_fans_can_comment": 0}]}
            draft = httpx.post("https://api.weixin.qq.com/cgi-bin/draft/add", params={"access_token": access_token}, json=payload, timeout=30).json()
            if "media_id" not in draft: raise RuntimeError(json.dumps(draft, ensure_ascii=False))
            result = {"mode": "real", "success": True, "message": "草稿已创建，仍需人工登录公众号后台发布", "media_id": draft["media_id"]}
            article.status = ArticleStatus.uploaded
        except Exception as exc:
            result = {"mode": "fallback", "success": False, "message": str(exc), "export": str(export_package(db, article))}
    attempt = PublishAttempt(article_id=article.id, idempotency_key=key, mode=result["mode"], status="ok" if result["success"] else "fallback", response=result)
    db.add(attempt); db.commit()
    return result
