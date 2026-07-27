from __future__ import annotations

from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import textwrap
import zipfile
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import cairosvg
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Article, Asset, BrandSettings, FeedItem


FONT_STACK = "Noto Sans CJK SC, Microsoft YaHei, PingFang SC, sans-serif"
SECTION_SPECS = [
    ("发生了什么", ("fact_summary", "facts"), "事实脉络"),
    ("为什么重要", ("value_interpretation", "analysis"), "价值判断"),
    ("对普通用户的影响", ("impact_on_general_users", "user_impact"), "用户影响"),
    ("开发者关注点", ("developer_focus", "developer_notes"), "开发视角"),
]


def _texts(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.splitlines() if part.strip()]
    if isinstance(value, dict):
        for key in ("fact", "text", "content", "summary", "value"):
            if value.get(key):
                return _texts(value[key])
        return [json.dumps(value, ensure_ascii=False)]
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_texts(item))
        return result
    return [str(value)]


def _content(article: Article, keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        values = _texts((article.content or {}).get(key))
        if values:
            return values
    return []


def _wrap_svg_text(value: str, width: int = 18, lines: int = 3) -> list[str]:
    value = re.sub(r"\s+", " ", value).strip()
    chunks = textwrap.wrap(value, width=width, break_long_words=True, break_on_hyphens=False)
    if len(chunks) > lines:
        chunks = chunks[:lines]
        chunks[-1] = chunks[-1][:-1] + "…" if len(chunks[-1]) > 1 else "…"
    return chunks or ["暂无内容"]


def _svg_text(lines: list[str], x: int, y: int, size: int, line_height: int, color: str) -> str:
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if index == 0 else line_height}">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="700">{spans}</text>'


def _cover_svg(article: Article, brand: BrandSettings, date_text: str) -> str:
    prefix = f"svga-cover-{article.id}-"
    title_lines = _wrap_svg_text(article.title, 16, 3)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="766" viewBox="0 0 1800 766" role="img" aria-labelledby="{prefix}title {prefix}desc">
<title id="{prefix}title">{escape(article.title)}公众号封面</title>
<desc id="{prefix}desc">以资讯节点和数据连线表达人工审核后的AI公众号文章。</desc>
<defs><linearGradient id="{prefix}accent" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{escape(brand.primary_color)}"/><stop offset="1" stop-color="#20C997"/></linearGradient></defs>
<rect width="1800" height="766" fill="{escape(brand.secondary_color)}"/>
<path d="M1120 120H1650V650H1120Z" fill="#FFFFFF" opacity=".035"/>
<g stroke="#FFFFFF" stroke-opacity=".15" stroke-width="2"><path d="M1210 230L1440 190L1580 350L1400 540L1190 470Z"/><path d="M1210 230L1400 540M1440 190L1190 470M1580 350L1210 230"/></g>
<g fill="url(#{prefix}accent)"><circle cx="1210" cy="230" r="26"/><circle cx="1440" cy="190" r="42"/><circle cx="1580" cy="350" r="31"/><circle cx="1400" cy="540" r="54"/><circle cx="1190" cy="470" r="35"/></g>
<g font-family="{FONT_STACK}">
<rect x="150" y="92" width="360" height="54" rx="12" fill="{escape(brand.primary_color)}"/><text x="180" y="129" fill="#FFFFFF" font-size="26" font-weight="700">{escape(brand.account_name)}</text>
{_svg_text(title_lines, 150, 265, 72, 92, "#F7F8FC")}
<text x="154" y="640" fill="#AAB2C5" font-size="28">AI 工具 · 开源项目 · 实战教程</text>
<text x="154" y="690" fill="#7E879C" font-size="24">{date_text}</text>
</g></svg>"""


def _section_svg(article: Article, index: int, heading: str, label: str, points: list[str], brand: BrandSettings) -> str:
    prefix = f"svga-section-{article.id}-{index}-"
    boxes = []
    for item_index, point in enumerate((points or ["等待人工补充"])[:3]):
        x = 90 + item_index * 350
        lines = _wrap_svg_text(point, 15, 3)
        boxes.append(
            f'<rect x="{x}" y="225" width="320" height="180" rx="18" fill="#171D2A" stroke="#34405A"/>'
            f'<text x="{x + 24}" y="266" fill="{escape(brand.primary_color)}" font-size="20" font-weight="700">0{item_index + 1}</text>'
            f'{_svg_text(lines, x + 24, 312, 25, 38, "#F3F5FA")}'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="500" viewBox="0 0 1200 500" role="img" aria-labelledby="{prefix}title {prefix}desc">
<title id="{prefix}title">{escape(heading)}章节配图</title>
<desc id="{prefix}desc">概括本章节经过人工审核的三个核心要点。</desc>
<rect width="1200" height="500" fill="{escape(brand.secondary_color)}"/>
<rect x="0" y="0" width="14" height="500" fill="{escape(brand.primary_color)}"/>
<g font-family="{FONT_STACK}">
<text x="80" y="95" fill="#8E9AB3" font-size="20" font-weight="700">{escape(label)}</text>
<text x="80" y="154" fill="#F7F8FC" font-size="48" font-weight="700">{escape(heading)}</text>
{''.join(boxes)}
</g></svg>"""


def _validate_svg(svg: str, width: int, height: int, prefix: str):
    lowered = svg.lower()
    forbidden = ("<script", "<foreignobject", "data:", 'href="http://', 'href="https://')
    if any(token in lowered for token in forbidden):
        raise ValueError("SVG 包含不允许的外部资源或脚本")
    root = ElementTree.fromstring(svg)
    if root.attrib.get("width") != str(width) or root.attrib.get("height") != str(height):
        raise ValueError("SVG 尺寸不正确")
    if root.attrib.get("viewBox") != f"0 0 {width} {height}":
        raise ValueError("SVG viewBox 不正确")
    if not any(child.tag.endswith("title") for child in root):
        raise ValueError("SVG 缺少 title")
    if not any(child.tag.endswith("desc") for child in root):
        raise ValueError("SVG 缺少 desc")
    for element in root.iter():
        element_id = element.attrib.get("id")
        if element_id and not element_id.startswith(prefix):
            raise ValueError("SVG ID 前缀不正确")


def _render_jpg(svg_path: Path, jpg_path: Path, width: int, height: int):
    png_path = jpg_path.with_suffix(".png")
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=width, output_height=height)
    with Image.open(png_path) as image:
        image.convert("RGB").save(jpg_path, "JPEG", quality=92, optimize=True)
    png_path.unlink(missing_ok=True)
    with Image.open(jpg_path) as image:
        if image.size != (width, height):
            raise ValueError(f"JPG 尺寸错误：{image.size}")


def _source_items(db: Session, article: Article) -> list[FeedItem]:
    items = db.scalars(
        select(FeedItem).where(FeedItem.event_id == article.event_id).order_by(FeedItem.published_at.desc())
    ).all()
    seen, result = set(), []
    for item in items:
        if item.url and item.url not in seen:
            seen.add(item.url)
            result.append(item)
    for item in (article.content or {}).get("sources", []):
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            result.append(SimpleNamespace(title=item.get("title") or url, url=url))
    return result


def _build_markdown(
    article: Article,
    sources: list[FeedItem],
    source_image_names: list[str] | None = None,
) -> tuple[str, list[dict]]:
    lead = _texts((article.content or {}).get("lead"))
    lines = [f"# {article.title}", ""]
    lines.extend(lead or ["本文基于已核验来源整理，内容已经人工审核。"])
    lines.append("")
    plan = []
    for index, (heading, keys, label) in enumerate(SECTION_SPECS, start=1):
        points = _content(article, keys)
        lines.extend([f"## {heading}", "", f"![图 {index:02d}：{heading}](images/{index:02d}-section.jpg)", ""])
        if source_image_names and index <= len(source_image_names):
            lines.extend([
                f"![原文配图 {index:02d}](images/{source_image_names[index - 1]})",
                "",
                "> 原文配图，版权归原作者或原网站所有。",
                "",
            ])
        if not points:
            points = ["该部分尚无可核验内容，请在发布前人工补充。"]
        for point_index, point in enumerate(points[:3], start=1):
            lines.extend([f"#### {'①②③'[point_index - 1]} {label}{point_index}", "", point, ""])
        plan.append({"index": index, "heading": heading, "label": label, "points": points[:3]})
    actions = _content(article, ("action_recommendations", "actions"))
    lines.extend(["## 写在最后", ""])
    lines.extend(actions or ["重要信息请回到原始来源核验，并根据自己的实际需求决定是否行动。"])
    if article.risk_notes:
        lines.extend(["", "#### 风险提示", ""])
        lines.extend([f"- {item}" for item in article.risk_notes])
    if sources:
        lines.extend(["", "#### 参考资料", ""])
        for item in sources:
            lines.append(f"- [{item.title}]({item.url})")
    return "\n".join(lines).strip() + "\n", plan


def _markdown_html(markdown: str) -> str:
    body, paragraph = [], []

    def flush():
        if paragraph:
            body.append(f"<p>{escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("![") and "](" in line:
            flush()
            match = re.match(r"!\[(.+?)\]\((.+?)\)", line)
            if match:
                body.append(f'<figure><img src="{escape(match.group(2))}" alt="{escape(match.group(1))}"></figure>')
        elif line.startswith("# "):
            flush(); body.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            flush(); body.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("#### "):
            flush(); body.append(f"<h4>{escape(line[5:])}</h4>")
        elif line.startswith("- ["):
            flush()
            match = re.match(r"- \[(.+?)\]\((.+?)\)", line)
            if match:
                body.append(f'<p class="source"><a href="{escape(match.group(2))}" target="_blank" rel="noopener">{escape(match.group(1))}</a></p>')
        elif line.startswith("- "):
            flush(); body.append(f'<p class="risk">{escape(line[2:])}</p>')
        else:
            paragraph.append(line)
    flush()
    return "\n".join(body)


def _preview_html(article: Article, markdown: str, cover_path: str, brand: BrandSettings) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(article.title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#eef1f5;color:#20242b;font-family:{FONT_STACK};line-height:1.85}}
.toolbar{{position:sticky;top:0;z-index:2;padding:12px 20px;background:#fff;border-bottom:1px solid #e5e7eb;color:#667085}}
main{{width:min(100% - 32px,780px);margin:30px auto 60px;padding:48px 54px;background:#fff}}
.cover,figure img{{display:block;width:100%;height:auto}}.cover{{margin-bottom:34px}}figure{{margin:24px -12px 30px}}
h1{{font-size:34px;line-height:1.35;margin:0 0 26px}}h2{{margin:52px 0 22px;padding-left:14px;border-left:5px solid {escape(brand.primary_color)};font-size:25px}}
h4{{margin:30px 0 8px;font-size:19px}}p{{font-size:17px;margin:13px 0;text-align:justify;overflow-wrap:anywhere}}
.risk{{padding:12px 15px;background:#fff7ed;border-left:4px solid #f59e0b}}.source{{font-size:14px;margin:7px 0}}a{{color:{escape(brand.primary_color)}}}
@media(max-width:720px){{main{{width:100%;margin:0;padding:28px 20px 48px}}h1{{font-size:29px}}figure{{margin-inline:-6px}}}}
</style></head><body><div class="toolbar">{escape(brand.account_name)} · 公众号网页预览</div>
<main><img class="cover" src="{escape(cover_path)}" alt="公众号封面">{_markdown_html(markdown)}</main></body></html>"""


def generate_wechat_publication(db: Session, article: Article) -> dict:
    brand = db.get(BrandSettings, 1) or BrandSettings(id=1)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    relative_dir = Path("publications") / f"article-{article.id}" / stamp
    output_dir = settings.export_dir / relative_dir
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=False)

    sources = _source_items(db, article)
    source_image_names = []
    asset_root = settings.asset_dir.resolve()
    for index, item in enumerate((article.content or {}).get("source_images", [])[:6], start=1):
        try:
            source_path = Path(item.get("path", "")).resolve()
            if asset_root not in source_path.parents or not source_path.is_file():
                continue
            name = f"source-original-{index:02d}.jpg"
            shutil.copy2(source_path, images_dir / name)
            source_image_names.append(name)
        except (OSError, RuntimeError, AttributeError):
            continue
    markdown, plan = _build_markdown(article, sources, source_image_names)
    (output_dir / "article.md").write_text(markdown, encoding="utf-8")

    cover_svg = _cover_svg(article, brand, now.strftime("%Y-%m-%d"))
    _validate_svg(cover_svg, 1800, 766, f"svga-cover-{article.id}-")
    cover_svg_path = output_dir / "cover.svg"
    cover_svg_path.write_text(cover_svg, encoding="utf-8")
    _render_jpg(cover_svg_path, output_dir / "cover.jpg", 1800, 766)

    asset_rows = [
        Asset(article_id=article.id, kind="publication_markdown", path=str(output_dir / "article.md"),
              metadata_json={"relative_path": str(relative_dir / "article.md")}),
        Asset(article_id=article.id, kind="publication_cover", path=str(output_dir / "cover.jpg"),
              metadata_json={"svg_path": str(cover_svg_path), "width": 1800, "height": 766}),
    ]
    for item in plan:
        index = item["index"]
        svg = _section_svg(article, index, item["heading"], item["label"], item["points"], brand)
        prefix = f"svga-section-{article.id}-{index}-"
        _validate_svg(svg, 1200, 500, prefix)
        svg_path = images_dir / f"{index:02d}-section.svg"
        jpg_path = images_dir / f"{index:02d}-section.jpg"
        svg_path.write_text(svg, encoding="utf-8")
        _render_jpg(svg_path, jpg_path, 1200, 500)
        asset_rows.append(Asset(
            article_id=article.id, kind="publication_illustration", path=str(jpg_path),
            metadata_json={"svg_path": str(svg_path), "width": 1200, "height": 500, "section": item["heading"]},
        ))

    (output_dir / "illustration-plan.json").write_text(
        json.dumps({"article_id": article.id, "items": plan}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    preview = _preview_html(article, markdown, "cover.jpg", brand)
    preview_path = output_dir / "preview.html"
    preview_path.write_text(preview, encoding="utf-8")
    asset_rows.append(Asset(
        article_id=article.id, kind="publication_html", path=str(preview_path),
        metadata_json={"relative_path": str(relative_dir / "preview.html")},
    ))
    manifest = {
        "article_id": article.id,
        "title": article.title,
        "generated_at": now.isoformat(),
        "preview_url": f"/generated/{relative_dir.as_posix()}/preview.html",
        "markdown": "article.md",
        "cover": {"jpg": "cover.jpg", "svg": "cover.svg"},
        "illustrations": len(plan),
        "source_count": len(sources),
    }
    base_url = f"/generated/{relative_dir.as_posix()}"
    manifest.update({
        "html_url": f"{base_url}/preview.html",
        "markdown_url": f"{base_url}/article.md",
        "cover_url": f"{base_url}/cover.jpg",
        "illustration_urls": [f"{base_url}/images/{item['index']:02d}-section.jpg" for item in plan],
        "bundle_url": f"{base_url}/公众号完整素材包.zip",
    })
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    bundle_path = output_dir / "公众号完整素材包.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in output_dir.rglob("*"):
            if path.is_file() and path != bundle_path:
                archive.write(path, path.relative_to(output_dir))
    db.add_all(asset_rows)
    db.commit()
    return manifest
