from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import socket
import zipfile
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from docx import Document
import httpx
from legacy_doc import extract_text as extract_legacy_doc
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors import DEFAULT_HEADERS, _extract_page
from .config import settings
from .models import Article, ArticleStatus, ArticleVersion, Asset, EventCluster
from .services import _client, normalize_url, parse_model_json


MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_SOURCE_IMAGES = 6
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 5
WEBSITE_IMPORT_SOURCE_KIND = "website_import"
SUPPORTED_UPLOADS = {".txt", ".md", ".markdown", ".html", ".htm", ".json", ".doc", ".docx", ".pdf"}


class WebsiteImportError(RuntimeError):
    pass


def _validate_public_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebsiteImportError("请输入有效的 HTTP 或 HTTPS 网站地址")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "postgres", "backend", "n8n", "adminer"} or hostname.endswith(".local"):
        raise WebsiteImportError("不能读取本机或内部服务地址")
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise WebsiteImportError("网站域名无法解析") from exc
    if not addresses:
        raise WebsiteImportError("网站域名没有可用地址")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise WebsiteImportError("不能读取内网、回环或保留地址")
    return value


def fetch_website(url: str) -> dict:
    current = _validate_public_url(url)
    with httpx.Client(timeout=45, follow_redirects=False, headers=DEFAULT_HEADERS) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                target = response.headers.get("location")
                if not target:
                    raise WebsiteImportError("网站重定向缺少目标地址")
                current = _validate_public_url(urljoin(current, target))
                continue
            if response.status_code in {401, 403}:
                raise WebsiteImportError(f"网站拒绝读取（HTTP {response.status_code}），请换用公开文章地址")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                raise WebsiteImportError("该地址不是可读取的网页 HTML")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise WebsiteImportError("网页内容超过 3 MB，无法安全处理")
            body, published_at = _extract_page(response.text)
            if len(body) < 200:
                raise WebsiteImportError("没有提取到足够正文，网站可能需要登录或依赖动态加载")
            soup = BeautifulSoup(response.text, "html.parser")
            title = ""
            og_title = soup.find("meta", attrs={"property": "og:title"})
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            if not title and soup.title:
                title = soup.title.get_text(" ", strip=True)
            title = title or urlparse(current).hostname or "网站文章"
            author_node = soup.find("meta", attrs={"name": "author"})
            author = author_node.get("content", "").strip() if author_node else ""
            image_urls = []
            image_nodes = soup.select("article img, main img") or soup.find_all("img")
            for node in image_nodes:
                candidate = (
                    node.get("data-src")
                    or node.get("data-original")
                    or node.get("data-lazy-src")
                    or node.get("src")
                    or ""
                ).strip()
                if not candidate or candidate.startswith(("data:", "blob:")):
                    continue
                absolute = urljoin(current, candidate)
                if absolute not in image_urls:
                    image_urls.append(absolute)
                if len(image_urls) >= MAX_SOURCE_IMAGES:
                    break
            return {
                "url": current,
                "title": title[:500],
                "author": author[:200],
                "body": body[:30000],
                "published_at": published_at,
                "images": image_urls,
            }
    raise WebsiteImportError("网站重定向次数过多")


def _write_article(source: dict) -> dict:
    client = _client()
    if not client:
        raise WebsiteImportError("尚未配置 AI 接口，无法生成公众号文章")
    prompt = {
        "source": {
            "title": source["title"],
            "url": source["url"],
            "author": source["author"],
            "published_at": source["published_at"].isoformat() if source["published_at"] else None,
            "body": source["body"],
        },
        "requirements": [
            "只使用 source 中明确出现的信息，不补充外部知识，不虚构体验、数据、版本、日期或结论",
            "输出适合中文公众号审核后台的 JSON，不输出 Markdown 或代码围栏",
            "固定英文键：titles、lead、fact_summary、value_interpretation、impact_on_general_users、developer_focus、action_recommendations、sources",
            "titles 必须是 3 个标题；fact_summary 每项包含 fact、evidence_id、source_url",
            "value_interpretation 与 impact_on_general_users 使用自然中文段落；developer_focus 与 action_recommendations 使用数组",
            "以编辑者第一人称表达观察，但不得声称亲自测试、使用或采访",
            "删除空洞套话、夸张词和未经来源支持的判断；不确定信息明确写为待核验",
        ],
    }
    response = client.responses.create(
        model=settings.openai_text_model,
        input=[
            {"role": "system", "content": "你是严谨的中文公众号技术编辑。你只能改写用户提供的网页证据，任何事实都必须能回溯到该网页。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        text={"format": {"type": "json_object"}},
        reasoning={"effort": "low"},
        max_output_tokens=3500,
    )
    content = parse_model_json(response)
    titles = content.get("titles")
    if not isinstance(titles, list) or not titles or not all(isinstance(item, str) and item.strip() for item in titles):
        raise WebsiteImportError("AI 返回的标题格式不完整，请重试")
    content["titles"] = titles[:3]
    content["sources"] = [{"title": source["title"], "url": source["url"]}]
    return content


def _save_source_images(db: Session, article: Article, image_urls: list[str]) -> list[dict]:
    if not image_urls:
        return []
    target_dir = settings.asset_dir / "imports" / f"article-{article.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    with httpx.Client(timeout=30, follow_redirects=False, headers=DEFAULT_HEADERS) as client:
        for index, original_url in enumerate(image_urls[:MAX_SOURCE_IMAGES], start=1):
            try:
                current = _validate_public_url(original_url)
                response = None
                for _ in range(MAX_REDIRECTS + 1):
                    response = client.get(current)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        current = _validate_public_url(urljoin(current, response.headers.get("location", "")))
                        continue
                    response.raise_for_status()
                    break
                if response is None or len(response.content) > MAX_IMAGE_BYTES:
                    continue
                if not response.headers.get("content-type", "").lower().startswith("image/"):
                    continue
                with Image.open(BytesIO(response.content)) as image:
                    image.load()
                    if image.width < 320 or image.height < 180:
                        continue
                    path = target_dir / f"source-{index:02d}.jpg"
                    image.convert("RGB").save(path, "JPEG", quality=90, optimize=True)
                    metadata = {
                        "original_url": original_url,
                        "width": image.width,
                        "height": image.height,
                    }
                db.add(Asset(article_id=article.id, kind="source_image", path=str(path), metadata_json=metadata))
                saved.append({"path": str(path), **metadata})
            except Exception:
                continue
    return saved


def _persist_article(
    db: Session,
    source_data: dict,
    source_mode: str,
    identity: str,
    preserve_images: bool = False,
) -> tuple[Article, bool]:
    imported_events = db.scalars(select(EventCluster).where(EventCluster.needs_review.is_(True))).all()
    for imported_event in imported_events:
        analysis = imported_event.analysis or {}
        if analysis.get("source_mode") == source_mode and analysis.get("source_identity") == identity:
            existing_article = db.scalar(select(Article).where(Article.event_id == imported_event.id))
            if existing_article:
                return existing_article, True

    content = _write_article(source_data)
    source_label = "网页" if source_mode == "user_supplied_website" else "上传文件"
    source_url = source_data.get("url", "")
    sources = [{"title": source_data["title"], "url": source_url}] if source_url else [{"title": source_data["title"], "url": ""}]
    content["sources"] = sources
    event = EventCluster(
        canonical_title=source_data["title"],
        topic="行业动态",
        primary_item_id=None,
        score=0,
        needs_review=True,
        analysis={
            "source_mode": source_mode,
            "source_identity": identity,
            "source_url": source_url,
            "facts": [entry.get("fact", "") for entry in content.get("fact_summary", []) if isinstance(entry, dict)],
            "unknowns": [f"当前仅依据用户提供的单一{source_label}生成，发布前需人工核验关键事实。"],
        },
    )
    db.add(event)
    db.flush()

    titles = content["titles"]
    article = Article(
        event_id=event.id,
        title=titles[0],
        title_options=titles,
        content=content,
        status=ArticleStatus.pending,
        risk_notes=[f"当前仅依据用户提供的单一{source_label}生成，数字、日期、价格和产品范围需在发布前人工核验。"],
        originality_notes=f"已基于{source_label}正文重新组织表达；保留原意但不逐字复制，生成结果需人工终审。",
    )
    db.add(article)
    db.flush()
    if preserve_images:
        saved_images = _save_source_images(db, article, source_data.get("images", []))
        article.content = {**article.content, "source_images": saved_images, "preserve_source_images": True}
    db.add(ArticleVersion(
        article_id=article.id,
        version=1,
        snapshot={
            "title": article.title,
            "title_options": article.title_options,
            "content": article.content,
            "status": article.status.value,
            "risk_notes": article.risk_notes,
            "originality_notes": article.originality_notes,
        },
    ))
    db.commit()
    db.refresh(article)
    return article, False


def create_article_from_website(db: Session, url: str, preserve_images: bool = False) -> tuple[Article, bool]:
    source_data = fetch_website(url)
    normalized = normalize_url(source_data["url"])
    return _persist_article(
        db,
        source_data,
        "user_supplied_website",
        f"{normalized}|images={preserve_images}",
        preserve_images,
    )


def extract_uploaded_file(filename: str, data: bytes) -> dict:
    if len(data) > MAX_UPLOAD_BYTES:
        raise WebsiteImportError("上传文件超过 15 MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_UPLOADS:
        raise WebsiteImportError("仅支持 TXT、Markdown、HTML、JSON、DOC、DOCX 和 PDF 文件")
    images: list[str] = []
    if suffix in {".txt", ".md", ".markdown"}:
        body = data.decode("utf-8-sig", errors="replace")
    elif suffix == ".json":
        try:
            parsed_json = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebsiteImportError("JSON 文件格式无效，请检查编码、引号和逗号") from exc
        if not isinstance(parsed_json, (dict, list)):
            raise WebsiteImportError("JSON 顶层内容必须是对象或数组")
        body = json.dumps(parsed_json, ensure_ascii=False, indent=2)
    elif suffix in {".html", ".htm"}:
        soup = BeautifulSoup(data.decode("utf-8", errors="replace"), "html.parser")
        body = soup.get_text("\n", strip=True)
    elif suffix in {".doc", ".docx"} and (suffix == ".docx" or data.startswith(b"PK\x03\x04")):
        document = Document(BytesIO(data))
        body = "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
        with zipfile.ZipFile(BytesIO(data)) as archive:
            media_names = [name for name in archive.namelist() if name.startswith("word/media/")][:MAX_SOURCE_IMAGES]
            images = [f"embedded:{name}" for name in media_names]
            source_media = {f"embedded:{name}": archive.read(name) for name in media_names}
    elif suffix == ".doc":
        try:
            legacy_result = extract_legacy_doc(data)
            body = legacy_result.text
        except Exception as exc:
            raise WebsiteImportError("旧版 DOC 文件无法解析，可能已损坏、加密或不是 Word 97–2003 格式") from exc
        source_media = {}
    else:
        reader = PdfReader(BytesIO(data))
        body = "\n".join(page.extract_text() or "" for page in reader.pages)
        source_media = {}
    if suffix not in {".doc", ".docx"} or not data.startswith(b"PK\x03\x04"):
        source_media = {}
    body = body.strip()
    if len(body) < 100:
        raise WebsiteImportError("文件中没有提取到足够正文；扫描版 PDF 请先进行 OCR")
    return {
        "url": "",
        "title": Path(filename).stem[:500] or "上传文件",
        "author": "",
        "body": body[:30000],
        "published_at": None,
        "images": images,
        "_embedded_media": source_media,
    }


def _save_embedded_images(db: Session, article: Article, source_data: dict) -> list[dict]:
    target_dir = settings.asset_dir / "imports" / f"article-{article.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for index, (name, data) in enumerate(source_data.get("_embedded_media", {}).items(), start=1):
        try:
            with Image.open(BytesIO(data)) as image:
                image.load()
                if image.width < 320 or image.height < 180:
                    continue
                path = target_dir / f"source-{index:02d}.jpg"
                image.convert("RGB").save(path, "JPEG", quality=90, optimize=True)
                metadata = {"original_url": name, "width": image.width, "height": image.height}
            db.add(Asset(article_id=article.id, kind="source_image", path=str(path), metadata_json=metadata))
            saved.append({"path": str(path), **metadata})
        except Exception:
            continue
    return saved


def create_article_from_file(
    db: Session,
    filename: str,
    data: bytes,
    preserve_images: bool = False,
) -> tuple[Article, bool]:
    import hashlib
    source_data = extract_uploaded_file(filename, data)
    identity = f"{hashlib.sha256(data).hexdigest()}|images={preserve_images}"
    article, reused = _persist_article(db, source_data, "user_supplied_file", identity, False)
    if preserve_images and not reused:
        saved = _save_embedded_images(db, article, source_data)
        article.content = {**article.content, "source_images": saved, "preserve_source_images": True}
        db.commit()
        db.refresh(article)
    return article, reused
